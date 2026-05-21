import numpy as np
import time
from typing import Optional

from wsi_analyzer.application.analysis.analysis_config import InferenceScaleConfig
from wsi_analyzer.application.analysis.analysis_session import AnalysisSession
from wsi_analyzer.application.analysis.coordinate_service import AnalysisCoordinateService
from wsi_analyzer.application.analysis.result_builder import AnalysisResultBuilder
from wsi_analyzer.domain.analysis.inference_geometry import InferenceGeometry
from wsi_analyzer.domain.analysis.result import AnalysisResult
from wsi_analyzer.domain.slide.coordinates import PatchCoordinate
from wsi_analyzer.domain.detection import nms_numpy
from wsi_analyzer.infrastructure.inference import BatchInferencer
from wsi_analyzer.infrastructure.logging import logger


class FullSlideAnalysisService:
    def __init__(
        self,
        coordinate_service: AnalysisCoordinateService,
        inferencer: BatchInferencer,
        config: InferenceScaleConfig,
        session: AnalysisSession,
        geometry: InferenceGeometry,
    ):
        self._coordinate_service = coordinate_service
        self._inferencer = inferencer
        self._config = config
        self._session = session
        self._geometry = geometry

    def run(
        self,
        progress_callback=None,
        status_callback=None,
        roi_bbox: Optional[tuple] = None,
        resume_data: Optional[dict] = None,
    ) -> AnalysisResult:
        session = self._session
        session._cancelled = False

        # raw detections accumulated across batches (pre-NMS)
        raw_boxes: list = []
        raw_scores: list = []
        raw_classes: list = []

        # ── coordinate generation ───────────────────────────────────

        if resume_data and resume_data.get("valid_coords"):
            # Verify cached geometry matches current geometry
            geom = self._geometry
            cached_l0 = resume_data.get("level0_window_size")
            cached_mi = resume_data.get("model_input_size")
            cached_rl = resume_data.get("read_level")
            cached_rd = resume_data.get("read_downsample")
            cached_stride = resume_data.get("level0_stride")
            if cached_l0 is not None and cached_mi is not None:
                geom_match = (
                    cached_l0 == geom.level0_window_size
                    and cached_mi == geom.model_input_size
                    and (cached_stride is None or cached_stride == geom.level0_stride)
                    and (cached_rl is None or cached_rl == geom.read_level)
                    and (cached_rd is None or cached_rd == geom.read_downsample)
                )
                if not geom_match:
                    msg = (
                        "推理几何已变更 (model_input_size=%d->%d, "
                        "level0_window=%d->%d). 请重新启动全片分析。"
                    ) % (
                        cached_mi, geom.model_input_size,
                        cached_l0, geom.level0_window_size,
                    )
                    if status_callback:
                        status_callback(msg)
                    return AnalysisResultBuilder.error(msg)

            if status_callback:
                status_callback("phase 1/4: resume detected, skipping mask generation ...")
            raw_coords = resume_data["valid_coords"]
            session.processed_count = min(
                int(resume_data.get("processed_patches", 0)),
                len(raw_coords),
            )

            if "raw_boxes" in resume_data:
                raw_boxes = list(resume_data["raw_boxes"])
                raw_scores = list(resume_data["raw_scores"])
                raw_classes = list(resume_data["raw_classes"])
            else:
                # old format: results were NMS-filtered; treat as raw for forward compat
                for r in resume_data.get("results", []):
                    raw_boxes.append(r["bbox"])
                    raw_scores.append(r["confidence"])
                    raw_classes.append(r["class_id"])
        else:
            phase_prefix = "phase 1/2" if roi_bbox else "phase 1/4"
            if status_callback:
                status_callback(
                    f"{phase_prefix}: extracting tissue mask and computing scan coords ..."
                )

            raw_coords = self._coordinate_service.build_coords(roi_bbox=roi_bbox)

            if not roi_bbox:
                if session.is_cancelled:
                    return AnalysisResultBuilder.error("analysis cancelled")
                if status_callback:
                    status_callback("phase 2/4: computing valid patch coordinates ...")

        if not raw_coords:
            return AnalysisResultBuilder.error("no valid tissue region found.")

        # restore PatchCoordinate from resume (old format may be bare tuples)
        if resume_data and resume_data.get("valid_coords"):
            valid_coords_for_result = list(raw_coords)
            geom = self._geometry
            patch_coords = [
                PatchCoordinate(
                    x=c[0], y=c[1],
                    level0_size=geom.level0_window_size,
                    model_input_size=geom.model_input_size,
                    read_level=geom.read_level,
                    read_downsample=geom.read_downsample,
                )
                for c in raw_coords
            ]
        else:
            patch_coords = raw_coords
            valid_coords_for_result = [(pc.x, pc.y) for pc in patch_coords]

        total_patches = len(patch_coords)
        remaining = patch_coords[session.processed_count:]

        # ── inference ───────────────────────────────────────────────

        if status_callback:
            phase = "phase 2/2" if roi_bbox else "phase 3/4"
            status_callback(
                f"{phase}: running model inference ({total_patches} patches, "
                f"{len(remaining)} remaining) ..."
            )

        new_boxes, new_scores, new_classes, current = self._inferencer.infer(
            remaining,
            progress_callback=(
                lambda p: progress_callback(
                    min(100, max(0, int((session.processed_count + p) / total_patches * 100)))
                )
            ) if progress_callback else None,
            cancel_check=lambda: session.is_cancelled,
        )

        raw_boxes.extend(new_boxes)
        raw_scores.extend(new_scores)
        raw_classes.extend(new_classes)
        final_processed = session.processed_count + current

        # ── NMS on ALL raw detections → final detections ─────────────

        if session.is_cancelled:
            # Interrupted: show NMS result for UI, save PRE-NMS raw for resume
            nms_b, nms_s, nms_c = self._apply_nms(raw_boxes, raw_scores, raw_classes)
            return AnalysisResultBuilder.interrupted(
                # final (for display): NMS on whatever raw accumulated so far
                final_boxes=nms_b,
                final_scores=nms_s,
                final_classes=nms_c,
                # raw (for resume): pre-NMS, merged on next run
                raw_boxes=raw_boxes,
                raw_scores=raw_scores,
                raw_classes=raw_classes,
                valid_coords=valid_coords_for_result,
                processed_patches=final_processed,
                total_patches=total_patches,
                geometry=self._geometry,
            )

        nms_boxes, nms_scores, nms_classes = self._apply_nms(raw_boxes, raw_scores, raw_classes)
        count = len(nms_boxes)

        if status_callback:
            status_callback(f"analysis complete: {count} lesions detected.")
        return AnalysisResultBuilder.completed(
            raw_boxes=nms_boxes,
            raw_scores=nms_scores,
            raw_classes=nms_classes,
            valid_coords=valid_coords_for_result,
            processed_patches=final_processed,
            total_patches=total_patches,
            raw_boxes_all=raw_boxes,
            raw_scores_all=raw_scores,
            raw_classes_all=raw_classes,
        )

    def _apply_nms(self, boxes, scores, classes) -> tuple:
        if not boxes:
            return [], [], []
        boxes_arr = np.array(boxes, dtype=np.float32)
        scores_arr = np.array(scores, dtype=np.float32)
        nms_start = time.perf_counter()
        keep = nms_numpy(boxes_arr, scores_arr, self._config.nms_iou_thresh)
        logger.info(
            "[nms timing] input_boxes=%d kept=%d elapsed=%.3fs",
            len(boxes_arr), len(keep), time.perf_counter() - nms_start,
        )
        return (
            [boxes_arr[idx].tolist() for idx in keep],
            [round(float(scores_arr[idx]), 4) for idx in keep],
            [int(classes[idx]) for idx in keep],
        )
