import numpy as np
from typing import Optional

from wsi_analyzer.application.analysis.analysis_config import AnalysisConfig
from wsi_analyzer.application.analysis.analysis_session import AnalysisSession
from wsi_analyzer.application.analysis.coordinate_service import AnalysisCoordinateService
from wsi_analyzer.application.analysis.result_builder import AnalysisResultBuilder
from wsi_analyzer.domain.analysis.result import AnalysisResult
from wsi_analyzer.domain.slide.coordinates import PatchCoordinate
from wsi_analyzer.domain.detection import nms_numpy
from wsi_analyzer.infrastructure.inference import BatchInferencer


class FullSlideAnalysisService:
    def __init__(
        self,
        coordinate_service: AnalysisCoordinateService,
        inferencer: BatchInferencer,
        config: AnalysisConfig,
        session: AnalysisSession,
    ):
        self._coordinate_service = coordinate_service
        self._inferencer = inferencer
        self._config = config
        self._session = session

    def run(
        self,
        progress_callback=None,
        status_callback=None,
        roi_bbox: Optional[tuple] = None,
        resume_data: Optional[dict] = None,
    ) -> AnalysisResult:
        session = self._session
        session._cancelled = False

        global_boxes = []
        global_scores = []
        global_classes = []

        target_level, target_downsample = self._coordinate_service.resolve_target_level()

        # ── coordinate generation ───────────────────────────────────

        if resume_data and resume_data.get("valid_coords"):
            if status_callback:
                status_callback("阶段 1/4: 发现断点缓存，跳过掩码生成...")
            raw_coords = resume_data["valid_coords"]
            session.processed_count = resume_data.get("processed_patches", 0)

            if "raw_boxes" in resume_data:
                global_boxes = list(resume_data["raw_boxes"])
                global_scores = list(resume_data["raw_scores"])
                global_classes = list(resume_data["raw_classes"])
            else:
                for r in resume_data.get("results", []):
                    global_boxes.append(r["bbox"])
                    global_scores.append(r["confidence"])
                    global_classes.append(r["class_id"])
        else:
            phase_prefix = "阶段 1/2" if roi_bbox else "阶段 1/4"
            if status_callback:
                status_callback(
                    f"{phase_prefix}: 正在提取组织掩码并计算扫描坐标..."
                )
            if not roi_bbox and status_callback:
                status_callback(phase_prefix)

            raw_coords = self._coordinate_service.build_coords(
                roi_bbox=roi_bbox,
                target_level=target_level,
                target_downsample=target_downsample,
            )

            if not roi_bbox:
                if session.is_cancelled:
                    return AnalysisResultBuilder.error("分析已取消")
                if status_callback:
                    status_callback("阶段 2/4: 正在计算有效滑动窗口坐标...")

        if not raw_coords:
            return AnalysisResultBuilder.error("未提取到有效的组织区域。")

        if resume_data and resume_data.get("valid_coords"):
            valid_coords_for_result = list(raw_coords)
            patch_coords = [
                PatchCoordinate(x=c[0], y=c[1], size=0, level=0, downsample=0)
                for c in raw_coords
            ]
        else:
            patch_coords = raw_coords
            valid_coords_for_result = [(pc.x, pc.y) for pc in patch_coords]

        total_patches = len(patch_coords)
        remaining = patch_coords[session.processed_count:]

        # ── inference ───────────────────────────────────────────────

        if status_callback:
            phase = "阶段 2/2" if roi_bbox else "阶段 3/4"
            status_callback(
                f"{phase}: 开始模型推理 (共 {total_patches} 个图像块，剩余 {len(remaining)} 个)..."
            )

        new_boxes, new_scores, new_classes, current = self._inferencer.infer(
            remaining,
            progress_callback=(
                lambda p: progress_callback(int((session.processed_count + p) / total_patches * 100))
            ) if progress_callback else None,
            cancel_check=lambda: session.is_cancelled,
        )

        global_boxes.extend(new_boxes)
        global_scores.extend(new_scores)
        global_classes.extend(new_classes)
        final_processed = session.processed_count + current

        # ── NMS + result ────────────────────────────────────────────

        nms_boxes, nms_scores, nms_classes = self._apply_nms(global_boxes, global_scores, global_classes)
        count = len(nms_boxes)

        if session.is_cancelled:
            return AnalysisResultBuilder.interrupted(
                raw_boxes=nms_boxes,
                raw_scores=nms_scores,
                raw_classes=nms_classes,
                valid_coords=valid_coords_for_result,
                processed_patches=final_processed,
                total_patches=total_patches,
            )

        if status_callback:
            status_callback(f"分析完成！共检测到 {count} 个病灶。")
        return AnalysisResultBuilder.completed(
            raw_boxes=nms_boxes,
            raw_scores=nms_scores,
            raw_classes=nms_classes,
            valid_coords=valid_coords_for_result,
            processed_patches=final_processed,
            total_patches=total_patches,
        )

    def _apply_nms(self, boxes, scores, classes) -> tuple:
        if not boxes:
            return [], [], []
        boxes_arr = np.array(boxes, dtype=np.float32)
        scores_arr = np.array(scores, dtype=np.float32)
        keep = nms_numpy(boxes_arr, scores_arr, self._config.nms_iou_thresh)
        return (
            [boxes_arr[idx].tolist() for idx in keep],
            [round(float(scores_arr[idx]), 4) for idx in keep],
            [int(classes[idx]) for idx in keep],
        )
