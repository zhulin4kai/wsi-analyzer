import config

from wsi_analyzer.application.analysis.analysis_config import AnalysisConfig
from wsi_analyzer.application.analysis.analysis_session import AnalysisSession
from wsi_analyzer.application.analysis.analysis_service import FullSlideAnalysisService
from wsi_analyzer.domain.analysis.tissue_mask import TissueMaskGenerator
from wsi_analyzer.infrastructure.imaging.image_server import ImageServer
from wsi_analyzer.infrastructure.imaging.patch_reader import PatchReader
from wsi_analyzer.infrastructure.inference.batch_inferencer import BatchInferencer
from wsi_analyzer.infrastructure.inference.model_factory import ModelAdapterFactory
from wsi_analyzer.infrastructure.logging.logger import logger


class AnalysisServiceHandle:
    def __init__(self, slide_path: str, service, session, adapter):
        self.slide_path = slide_path
        self.service = service
        self.session = session
        self.adapter = adapter
        self._closed = False

    def cancel(self):
        self.session.cancel()

    def close(self):
        if self._closed:
            return
        ImageServer.instance().release_engine(self.slide_path)
        self._closed = True

        if self.adapter is not None:
            del self.adapter
            self.adapter = None


class AnalysisServiceFactory:
    @staticmethod
    def create(
        svs_path,
        model_path,
        patch_size=512,
        stride=400,
        nms_iou_thresh=0.25,
        conf_thresh=0.5,
        device="cpu",
        batch_size=16,
        target_mpp=None,
    ) -> AnalysisServiceHandle:
        analysis_config = AnalysisConfig.from_raw(
            patch_size=patch_size,
            stride=stride,
            nms_iou_thresh=nms_iou_thresh,
            conf_thresh=conf_thresh,
            device=device,
            batch_size=batch_size,
            target_mpp=target_mpp
            if target_mpp is not None
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

        logger.info(
            f"[*] 使用计算设备: {analysis_config.device}, "
            f"Batch Size: {analysis_config.batch_size}"
        )

        logger.info(f"[*] 正在加载模型: {model_path}")
        adapter = ModelAdapterFactory.create_adapter(model_path)

        logger.info(f"[*] 正在打开 WSI 文件: {svs_path}")
        engine = ImageServer.instance().acquire_engine(svs_path)

        target_level = engine.get_best_level_for_mpp(analysis_config.target_mpp)
        target_downsample = engine.slide.level_downsamples[target_level]

        reader = PatchReader(
            engine,
            target_level,
            target_downsample,
            analysis_config.patch_size,
        )

        inferencer = BatchInferencer(
            adapter,
            reader,
            analysis_config.device,
            analysis_config.batch_size,
            analysis_config.conf_thresh,
        )

        session = AnalysisSession(analysis_config)

        service = FullSlideAnalysisService(
            mask_generator=TissueMaskGenerator(
                getattr(config, "AI_MIN_AREA_RATIO", 0.001)
            ),
            patch_reader=reader,
            inferencer=inferencer,
            config=analysis_config,
            session=session,
            engine=engine,
        )

        return AnalysisServiceHandle(
            slide_path=svs_path,
            service=service,
            session=session,
            adapter=adapter,
        )