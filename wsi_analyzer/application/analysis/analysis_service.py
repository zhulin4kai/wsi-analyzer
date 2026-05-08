import numpy as np
from typing import Optional

from wsi_analyzer.application.analysis.analysis_config import AnalysisConfig
from wsi_analyzer.application.analysis.analysis_session import AnalysisSession
from wsi_analyzer.application.analysis.coordinate_service import AnalysisCoordinateService
from wsi_analyzer.application.analysis.result_builder import AnalysisResultBuilder
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
    ) -> dict:
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
            valid_coords = resume_data["valid_coords"]
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

            patch_coords = self._coordinate_service.build_coords(
                roi_bbox=roi_bbox,
                target_level=target_level,
                target_downsample=target_downsample,
            )
            valid_coords = [(pc.x, pc.y) for pc in patch_coords]

            if not roi_bbox:
                if session.is_cancelled:
                    return AnalysisResultBuilder.error("分析已取消")
                if status_callback:
                    status_callback("阶段 2/4: 正在计算有效滑动窗口坐标...")

        if not valid_coords:
            return AnalysisResultBuilder.error("未提取到有效的组织区域。")

        total_patches = len(valid_coords)
        remaining = valid_coords[session.processed_count:]

        # ── inference ───────────────────────────────────────────────

        if status_callback:
            phase = "阶段 2/2" if roi_bbox else "阶段 3/4"
            status_callback(
                f"{phase}: 开始模型推理 (共 {total_patches} 个图像块，剩余 {len(remaining)} 个)..."
            )

        new_boxes, new_scores, new_classes, current = self._inferencer.infer(
            remaining,
            progress_callback=progress_callback,
            cancel_check=lambda: session.is_cancelled,
        )

        global_boxes.extend(new_boxes)
        global_scores.extend(new_scores)
        global_classes.extend(new_classes)
        final_processed = session.processed_count + current

        # ── NMS + result ────────────────────────────────────────────

        results = self._apply_nms(global_boxes, global_scores, global_classes)

        if session.is_cancelled:
            return AnalysisResultBuilder.interrupted(
                results=results,
                raw_boxes=global_boxes,
                raw_scores=global_scores,
                raw_classes=global_classes,
                valid_coords=valid_coords,
                processed_patches=final_processed,
                total_patches=total_patches,
            )

        if status_callback:
            status_callback(f"分析完成！共检测到 {len(results)} 个病灶。")
        return AnalysisResultBuilder.completed(
            results=results,
            valid_coords=valid_coords,
            processed_patches=final_processed,
            total_patches=total_patches,
        )

    def _apply_nms(self, boxes, scores, classes) -> list:
        if not boxes:
            return []
        boxes_arr = np.array(boxes, dtype=np.float32)
        scores_arr = np.array(scores, dtype=np.float32)
        keep = nms_numpy(boxes_arr, scores_arr, self._config.nms_iou_thresh)
        return [
            {
                "bbox": [round(float(b), 2) for b in boxes_arr[idx]],
                "confidence": round(float(scores_arr[idx]), 4),
                "class_id": int(classes[idx]),
            }
            for idx in keep
        ]
