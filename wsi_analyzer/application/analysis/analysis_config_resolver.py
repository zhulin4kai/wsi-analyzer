import os

from wsi_analyzer.config import config
from wsi_analyzer.application.analysis.analysis_config import AnalysisConfig
from wsi_analyzer.application.analysis.auto_tune_service import AutoTuneService
from wsi_analyzer.infrastructure.hardware import HardwareProfiler


class AnalysisConfigResolver:
    def __init__(self, db):
        self._db = db

    def resolve(self, svs_path: str, model_path: str) -> AnalysisConfig:
        patch_size = self._db.get_setting("ai_patch_size", config.AI_PATCH_SIZE)
        stride = self._db.get_setting("ai_stride", config.AI_STRIDE)
        nms_iou_thresh = self._db.get_setting("ai_nms_iou_thresh", config.AI_NMS_IOU_THRESH)
        conf_thresh = self._db.get_setting("ai_conf_thresh", config.AI_CONF_THRESH)
        target_mpp = float(self._db.get_setting("ai_model_target_mpp", config.AI_MODEL_TARGET_MPP))

        drive_prefix = HardwareProfiler.get_storage_key(svs_path)
        profile = self._db.get_system_profile(drive_prefix)

        if profile:
            device = profile.get("device", HardwareProfiler.get_compute_device())
            batch_size = profile.get("batch_size", 16)
        else:
            device = HardwareProfiler.get_compute_device()
            batch_size = 16

        analysis_config = AnalysisConfig.from_raw(
            patch_size=patch_size, stride=stride,
            nms_iou_thresh=nms_iou_thresh, conf_thresh=conf_thresh,
            device=device, batch_size=batch_size, target_mpp=target_mpp,
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

        if self._db.get_auto_tune_enabled():
            io_speed = profile.get("io_speed", 50.0) if profile else 50.0
            model_size_mb = os.path.getsize(model_path) / (1024 * 1024)
            analysis_config = AutoTuneService.apply(analysis_config, io_speed, model_size_mb)

        return analysis_config
