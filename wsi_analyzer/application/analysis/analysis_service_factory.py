import config

from wsi_analyzer.application.analysis.analysis_config_resolver import AnalysisConfigResolver
from wsi_analyzer.application.analysis.analysis_service import FullSlideAnalysisService
from wsi_analyzer.application.analysis.analysis_session import AnalysisSession
from wsi_analyzer.application.analysis.coordinate_service import AnalysisCoordinateService
from wsi_analyzer.domain.analysis.inference_geometry import InferenceGeometry
from wsi_analyzer.domain.analysis.tissue_mask import TissueMaskGenerator
from wsi_analyzer.infrastructure.imaging.openslide_read_adapter import OpenSlideReadAdapter
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
    def __init__(self, database, image_server):
        self._database = database
        self._image_server = image_server

    def create(self, svs_path, model_path) -> AnalysisServiceHandle:
        resolver = AnalysisConfigResolver(self._database)
        analysis_config = resolver.resolve(svs_path, model_path)
        logger.info(
            f"[*] device={analysis_config.device}, batch_size={analysis_config.batch_size}"
        )
        logger.info(f"[*] loading model: {model_path}")
        adapter = ModelAdapterFactory.create_adapter(model_path)

        logger.info(f"[*] opening WSI: {svs_path}")
        engine = self._image_server.acquire_engine(svs_path)
        slide_port = OpenSlideReadAdapter(engine)

        read_level, read_downsample = slide_port.resolve_target_level(analysis_config.target_mpp)
        slide_mpp = slide_port.slide_mpp

        geometry = InferenceGeometry.from_config_and_slide(
            model_input_size=analysis_config.model_input_size,
            target_mpp=analysis_config.target_mpp,
            level0_stride=analysis_config.level0_stride,
            slide_mpp=slide_mpp,
            objective_power=slide_port.objective_power,
            read_level=read_level,
            read_downsample=read_downsample,
        )
        logger.info(
            f"[*] model_input_size=%d, target_mpp=%.4f",
            geometry.model_input_size, geometry.target_mpp,
        )
        logger.info(
            f"[*] slide_mpp=%s",
            f"{geometry.slide_mpp:.4f}" if geometry.slide_mpp else "None",
        )
        logger.info(
            f"[*] level0_window_size=%d, local_to_level0_scale=%.3f",
            geometry.level0_window_size, geometry.local_to_level0_scale,
        )
        logger.info(
            f"[*] read_level=%d, read_downsample=%.1f",
            geometry.read_level, geometry.read_downsample,
        )

        reader = PatchReader(engine)
        inferencer = BatchInferencer(
            adapter, reader, analysis_config.device,
            analysis_config.batch_size, analysis_config.conf_thresh,
            model_input_size=geometry.model_input_size,
        )

        mask_generator = TissueMaskGenerator(
            min_area_ratio=getattr(config, "AI_MIN_AREA_RATIO", 0.001)
        )

        coordinate_service = AnalysisCoordinateService(
            mask_generator=mask_generator,
            geometry=geometry,
            slide_port=slide_port,
        )

        session = AnalysisSession(analysis_config)

        service = FullSlideAnalysisService(
            coordinate_service=coordinate_service,
            inferencer=inferencer,
            config=analysis_config,
            session=session,
            geometry=geometry,
        )

        return AnalysisServiceHandle(
            slide_path=svs_path, service=service, session=session,
            adapter=adapter, image_server=self._image_server,
        )
