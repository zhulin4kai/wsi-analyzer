import config

from wsi_analyzer.app.dependency_container import container
from wsi_analyzer.application.analysis.analysis_config_resolver import AnalysisConfigResolver
from wsi_analyzer.application.analysis.analysis_service import FullSlideAnalysisService
from wsi_analyzer.application.analysis.analysis_session import AnalysisSession
from wsi_analyzer.application.analysis.coordinate_service import AnalysisCoordinateService
from wsi_analyzer.domain.analysis.tissue_mask import TissueMaskGenerator
from wsi_analyzer.infrastructure.imaging import PatchReader
from wsi_analyzer.infrastructure.inference import BatchInferencer, ModelAdapterFactory
from wsi_analyzer.infrastructure.logging import logger


class AnalysisServiceHandle:
    def __init__(self, slide_path: str, service, session, adapter, image_server):
        self.slide_path = slide_path
        self.service = service
        self.session = session
        self.adapter = adapter
        self._image_server = image_server
        self._closed = False

    def cancel(self):
        self.session.cancel()

    def close(self):
        if self._closed:
            return
        self._image_server.release_engine(self.slide_path)
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
        analysis_config = AnalysisConfigResolver.resolve({
            "patch_size": patch_size, "stride": stride,
            "nms_iou_thresh": nms_iou_thresh, "conf_thresh": conf_thresh,
            "device": device, "batch_size": batch_size,
            "target_mpp": target_mpp,
        })

        logger.info(f"[*] 使用计算设备: {analysis_config.device}, Batch Size: {analysis_config.batch_size}")
        logger.info(f"[*] 正在加载模型: {model_path}")
        adapter = ModelAdapterFactory.create_adapter(model_path)

        logger.info(f"[*] 正在打开 WSI 文件: {svs_path}")
        engine = container.image_server.acquire_engine(svs_path)

        target_level = engine.get_best_level_for_mpp(analysis_config.target_mpp)
        target_downsample = engine.slide.level_downsamples[target_level]

        reader = PatchReader(engine, target_level, target_downsample, analysis_config.patch_size)
        inferencer = BatchInferencer(adapter, reader, analysis_config.device, analysis_config.batch_size, analysis_config.conf_thresh)

        session = AnalysisSession(analysis_config)

        coordinate_service = AnalysisCoordinateService(
            mask_generator=TissueMaskGenerator(getattr(config, "AI_MIN_AREA_RATIO", 0.001)),
            config=analysis_config, engine=engine,
        )

        service = FullSlideAnalysisService(
            coordinate_service=coordinate_service, inferencer=inferencer,
            config=analysis_config, session=session,
        )

        return AnalysisServiceHandle(
            slide_path=svs_path, service=service, session=session,
            adapter=adapter, image_server=container.image_server,
        )
