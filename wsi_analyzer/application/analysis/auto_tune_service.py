from wsi_analyzer.infrastructure.hardware import HardwareProfiler


class AutoTuneService:
    @staticmethod
    def apply(config, io_speed: float, model_size_mb: float):
        from wsi_analyzer.application.analysis.analysis_config import AnalysisConfig

        auto_params = HardwareProfiler.calculate_auto_tune_params(
            io_speed, config.patch_size, model_size_mb
        )
        return AnalysisConfig.from_raw(
            patch_size=int(auto_params.get("patch_size", config.patch_size)),
            stride=int(auto_params.get("stride", config.stride)),
            nms_iou_thresh=float(auto_params.get("nms_iou_thresh", config.nms_iou_thresh)),
            conf_thresh=float(auto_params.get("conf_thresh", config.conf_thresh)),
            device=config.device,
            batch_size=config.batch_size,
            target_mpp=config.target_mpp,
        )
