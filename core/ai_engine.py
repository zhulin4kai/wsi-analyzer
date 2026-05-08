import config
from wsi_analyzer.application.analysis.analysis_config import AnalysisConfig
from wsi_analyzer.application.analysis.analysis_service import FullSlideAnalysisService
from wsi_analyzer.application.analysis.analysis_session import AnalysisSession
from wsi_analyzer.domain.analysis.tissue_mask import TissueMaskGenerator
from wsi_analyzer.infrastructure.imaging.patch_reader import PatchReader
from wsi_analyzer.infrastructure.inference.batch_inferencer import BatchInferencer
from .image_server import ImageServer
from .model_adapters import ModelAdapterFactory
from wsi_analyzer.infrastructure.logging.logger import logger


class WSIAnalyzer:
    def __init__(
        self,
        svs_path,
        model_path,
        patch_size=512,
        stride=400,
        nms_iou_thresh=0.25,
        conf_thresh=0.5,
        device="cpu",
        batch_size=16,
        target_mpp=None,
    ):
        self.svs_path = svs_path
        self._config = AnalysisConfig.from_raw(
            patch_size=patch_size, stride=stride,
            nms_iou_thresh=nms_iou_thresh, conf_thresh=conf_thresh,
            device=device, batch_size=batch_size,
            target_mpp=target_mpp if target_mpp is not None else getattr(config, "AI_MODEL_TARGET_MPP", 2.0),
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

        logger.info(f"[*] 使用计算设备: {self._config.device}, Batch Size: {self._config.batch_size}")
        logger.info(f"[*] 正在加载模型: {model_path}")
        self._adapter = ModelAdapterFactory.create_adapter(model_path)

        logger.info(f"[*] 正在打开 WSI 文件: {svs_path}")
        self._engine = ImageServer.instance().acquire_engine(svs_path)

        target_level = self._engine.get_best_level_for_mpp(self._config.target_mpp)
        target_downsample = self._engine.slide.level_downsamples[target_level]

        self._reader = PatchReader(self._engine, target_level, target_downsample, self._config.patch_size)

        self._inferencer = BatchInferencer(
            self._adapter, self._reader, self._config.device,
            self._config.batch_size, self._config.conf_thresh,
        )

        self._session = AnalysisSession(self._config)

        self._service = FullSlideAnalysisService(
            mask_generator=TissueMaskGenerator(
                getattr(config, "AI_MIN_AREA_RATIO", 0.001)
            ),
            patch_reader=self._reader,
            inferencer=self._inferencer,
            config=self._config,
            session=self._session,
            engine=self._engine,
        )

    def cancel(self):
        self._session.cancel()

    def process(self, resume_data=None, progress_callback=None, status_callback=None, roi_bbox=None):
        return self._service.run(
            progress_callback=progress_callback,
            status_callback=status_callback,
            roi_bbox=roi_bbox,
            resume_data=resume_data,
        )

    def close(self):
        if hasattr(self, "_engine") and self._engine is not None:
            ImageServer.instance().release_engine(self.svs_path)
            self._engine = None
        if hasattr(self, "_adapter") and self._adapter is not None:
            del self._adapter
            self._adapter = None
