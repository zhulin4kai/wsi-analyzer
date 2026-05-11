from wsi_analyzer.infrastructure.hardware import HardwareProfiler


class AutoTuneService:
    @staticmethod
    def apply(config, io_speed: float, model_size_mb: float, has_metadata: bool = False):
        from wsi_analyzer.application.analysis.analysis_config import InferenceScaleConfig

        auto_params = HardwareProfiler.calculate_auto_tune_params(
            io_speed, config.model_input_size, model_size_mb
        )
        return InferenceScaleConfig.from_raw(
            # When metadata is present, model_input_size comes from sidecar, not auto-tune
            patch_size=config.model_input_size,
            stride=int(auto_params.get("stride", config.level0_stride)),
            nms_iou_thresh=(
                float(auto_params.get("nms_iou_thresh", config.nms_iou_thresh))
                if has_metadata else config.nms_iou_thresh
            ),
            conf_thresh=(
                float(auto_params.get("conf_thresh", config.conf_thresh))
                if has_metadata else config.conf_thresh
            ),
            device=config.device,
            batch_size=config.batch_size,
            target_mpp=config.target_mpp,
        )
