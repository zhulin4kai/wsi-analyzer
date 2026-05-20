import os

from wsi_analyzer.config import config
from wsi_analyzer.application.analysis.analysis_config import InferenceScaleConfig
from wsi_analyzer.application.analysis.auto_tune_service import AutoTuneService
from wsi_analyzer.infrastructure.hardware import HardwareProfiler
from wsi_analyzer.infrastructure.inference.model_metadata_loader import ModelMetadataLoader
from wsi_analyzer.infrastructure.logging import logger


class AnalysisConfigResolver:
    def __init__(self, db):
        self._db = db
        self._metadata_loader = ModelMetadataLoader()

    def resolve(self, svs_path: str, model_path: str) -> InferenceScaleConfig:
        meta = self._metadata_loader.load(model_path)

        # ── model_input_size priority ────────────────────────────────
        # 1. sidecar metadata
        # 2. YOLO checkpoint imgsz
        # 3. DB ai_patch_size
        # 4. config default
        if meta is not None:
            model_input_size = meta.model_input_size
            meta_source = "sidecar"
        else:
            model_input_size = self._db.get_setting("ai_patch_size", config.AI_PATCH_SIZE)
            meta_source = None

        # ── target_mpp priority ──────────────────────────────────────
        # 1. sidecar metadata
        # 2. DB ai_model_target_mpp
        # 3. config default
        if meta is not None:
            target_mpp = meta.target_mpp
        else:
            target_mpp = float(
                self._db.get_setting("ai_model_target_mpp", config.AI_MODEL_TARGET_MPP)
            )
            logger.warning(
                "No model metadata sidecar found for %s; "
                "target_mpp=%.4f from DB/default may be unreliable",
                os.path.basename(model_path), target_mpp,
            )

        stride = self._db.get_setting("ai_stride", config.AI_STRIDE)
        nms_iou_thresh = self._db.get_setting("ai_nms_iou_thresh", config.AI_NMS_IOU_THRESH)
        conf_thresh = self._db.get_setting("ai_conf_thresh", config.AI_CONF_THRESH)

        drive_prefix = HardwareProfiler.get_storage_key(svs_path)
        profile = self._db.get_system_profile(drive_prefix)

        policy = str(getattr(config, "AI_DEVICE_POLICY", "auto")).lower()
        if policy in {"cuda", "cpu", "mps"}:
            device = policy
        elif profile:
            device = profile.get("device", HardwareProfiler.get_compute_device())
            batch_size = profile.get("batch_size", 16)
        else:
            device = HardwareProfiler.get_compute_device()
            batch_size = 16
        if policy in {"cuda", "cpu", "mps"}:
            batch_size = profile.get("batch_size", 16) if profile else 16

        analysis_config = InferenceScaleConfig.from_raw(
            patch_size=model_input_size, stride=stride,
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
        if device == "cpu":
            cpu_batch = int(getattr(config, "AI_CPU_BATCH_SIZE_DEFAULT", 2))
            cpu_stride_scale = float(getattr(config, "AI_CPU_STRIDE_SCALE", 1.5))
            analysis_config = InferenceScaleConfig.from_raw(
                patch_size=analysis_config.model_input_size,
                stride=max(analysis_config.level0_stride, int(analysis_config.level0_stride * cpu_stride_scale)),
                nms_iou_thresh=analysis_config.nms_iou_thresh,
                conf_thresh=analysis_config.conf_thresh,
                device=device,
                batch_size=max(1, min(cpu_batch, analysis_config.batch_size)),
                target_mpp=analysis_config.target_mpp,
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
            analysis_config = AutoTuneService.apply(
                analysis_config, io_speed, model_size_mb,
                has_metadata=(meta is not None),
            )

        return analysis_config
