from wsi_analyzer.config import config
from wsi_analyzer.application.analysis.analysis_config import AnalysisConfig


class AnalysisConfigResolver:
    @staticmethod
    def resolve(raw) -> "AnalysisConfig":
        return AnalysisConfig.from_raw(
            patch_size=raw.get("patch_size", 512),
            stride=raw.get("stride", 400),
            nms_iou_thresh=raw.get("nms_iou_thresh", 0.25),
            conf_thresh=raw.get("conf_thresh", 0.5),
            device=raw.get("device", "cpu"),
            batch_size=raw.get("batch_size", 16),
            target_mpp=raw.get("target_mpp")
            if raw.get("target_mpp") is not None
            else getattr(config, "AI_MODEL_TARGET_MPP", 2.0),
            patch_size_min=getattr(config, "AI_PATCH_SIZE_MIN", 128),
            patch_size_max=getattr(config, "AI_PATCH_SIZE_MAX", 4096),
            stride_min=getattr(config, "AI_STRIDE_MIN", 64),
            stride_max=getattr(config, "AI_STRIDE_MAX", 4096),
            iou_min=getattr(config, "AI_NMS_IOU_THRESH_MIN", 0.01),
            iou_max=getattr(config, "AI_NMS_IOU_THRESH_MAX", 1.0),
            conf_min=getattr(config, "AI_CONF_THRESH_MIN", 0.01),
            conf_max=getattr(config, "AI_CONF_THRESH_MAX", 1.0),
            batch_cap=getattr(config, "BATCH_SIZE_CAP_NVME_SSD", 64),
        )
