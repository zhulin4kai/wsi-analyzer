from typing import Optional

from wsi_analyzer.application.analysis.analysis_config import AnalysisConfig
from wsi_analyzer.application.analysis.analysis_session import AnalysisSession
from wsi_analyzer.domain.analysis.patch_plan import PatchPlanner
from wsi_analyzer.domain.analysis.roi_planner import ROIPlanner
from wsi_analyzer.domain.detection.nms import nms_numpy
from wsi_analyzer.infrastructure.inference.batch_inferencer import BatchInferencer
from wsi_analyzer.infrastructure.imaging.patch_reader import PatchReader


class FullSlideAnalysisService:
    def __init__(
        self,
        mask_generator,
        patch_reader: PatchReader,
        inferencer: BatchInferencer,
        config: AnalysisConfig,
        session: AnalysisSession,
        engine,  # slide engine for thumbnail reading + metadata
    ):
        self._mask_generator = mask_generator
        self._reader = patch_reader
        self._inferencer = inferencer
        self._config = config
        self._session = session
        self._engine = engine

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

        target_level = self._engine.get_best_level_for_mpp(self._config.target_mpp)
        target_downsample = self._engine.slide.level_downsamples[target_level]

        # ── Phase: coordinate generation ────────────────────────────

        if roi_bbox:
            if status_callback:
                status_callback("阶段 1/2: 正在提取组织掩码并计算 ROI 靶向分析坐标...")
            level, dim, ds = self._engine.get_level_info(3)
            thumb = self._engine.read_region((0, 0), level, dim)
            thumb_rgb = thumb.convert("RGB")
            from numpy import array
            mask = self._mask_generator.generate(array(thumb_rgb))
            roi_stride = int(self._config.patch_size * 0.5)
            planner = ROIPlanner(self._config.patch_size, roi_stride)
            valid_patch_coords = planner.plan(
                roi_bbox=roi_bbox,
                level_0_dim=self._engine.level_0_dim,
                solid_mask=mask,
                downsample_factor=ds,
                target_level=target_level,
                target_downsample=target_downsample,
            )
            valid_coords = [(pc.x, pc.y) for pc in valid_patch_coords]
        elif resume_data and resume_data.get("valid_coords"):
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
            if status_callback:
                status_callback("阶段 1/4: 正在提取宏观图像与生成组织掩码...")
            level, dim, ds = self._engine.get_level_info(3)
            thumb = self._engine.read_region((0, 0), level, dim)
            thumb_rgb = thumb.convert("RGB")
            from numpy import array
            mask = self._mask_generator.generate(array(thumb_rgb))

            if session.is_cancelled:
                return {"status": "interrupted", "results": [], "valid_coords": [], "processed_patches": 0, "total_patches": 0}

            if status_callback:
                status_callback("阶段 2/4: 正在计算有效滑动窗口坐标...")
            planner = PatchPlanner(self._config.patch_size, self._config.stride)
            valid_coords = [
                (pc.x, pc.y) for pc in planner.plan(
                    mask, self._engine.level_0_dim, ds, target_level, target_downsample
                )
            ]

        if not valid_coords:
            msg = "未提取到有效的组织区域。"
            return {"status": "error", "message": msg, "results": [], "valid_coords": [], "processed_patches": 0, "total_patches": 0}

        total_patches = len(valid_coords)
        remaining = valid_coords[session.processed_count:]

        if status_callback:
            phase = "阶段 2/2" if roi_bbox else "阶段 3/4"
            status_callback(f"{phase}: 开始模型推理 (共 {total_patches} 个图像块，剩余 {len(remaining)} 个)...")

        new_boxes, new_scores, new_classes, current = self._inferencer.infer(
            remaining,
            progress_callback=progress_callback,
            cancel_check=lambda: session.is_cancelled,
        )

        global_boxes.extend(new_boxes)
        global_scores.extend(new_scores)
        global_classes.extend(new_classes)
        final_processed = session.processed_count + current

        if session.is_cancelled:
            results = self._apply_nms(global_boxes, global_scores, global_classes)
            return {
                "status": "interrupted",
                "results": results,
                "raw_boxes": global_boxes,
                "raw_scores": global_scores,
                "raw_classes": global_classes,
                "valid_coords": valid_coords,
                "processed_patches": final_processed,
                "total_patches": total_patches,
            }

        results = self._apply_nms(global_boxes, global_scores, global_classes)
        if status_callback:
            status_callback(f"分析完成！共检测到 {len(results)} 个病灶。")
        return {
            "status": "completed",
            "results": results,
            "valid_coords": valid_coords,
            "processed_patches": final_processed,
            "total_patches": total_patches,
        }

    def _apply_nms(self, boxes, scores, classes) -> list:
        if not boxes:
            return []
        boxes_arr = __import__("numpy").array(boxes, dtype=__import__("numpy").float32)
        scores_arr = __import__("numpy").array(scores, dtype=__import__("numpy").float32)
        keep = nms_numpy(boxes_arr, scores_arr, self._config.nms_iou_thresh)
        return [
            {
                "bbox": [round(float(b), 2) for b in boxes_arr[idx]],
                "confidence": round(float(scores_arr[idx]), 4),
                "class_id": int(classes[idx]),
            }
            for idx in keep
        ]
