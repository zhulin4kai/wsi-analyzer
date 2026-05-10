from typing import Optional

from wsi_analyzer.domain.analysis import PatchPlanner, ROIPlanner
from wsi_analyzer.domain.analysis.inference_geometry import InferenceGeometry
from wsi_analyzer.domain.slide.coordinates import PatchCoordinate
from wsi_analyzer.domain.slide.slide_read_port import SlideReadPort


class AnalysisCoordinateService:
    def __init__(self, mask_generator, geometry: InferenceGeometry, slide_port: SlideReadPort):
        self._mask_generator = mask_generator
        self._geometry = geometry
        self._slide_port = slide_port

    def build_full_slide_coords(self) -> list[PatchCoordinate]:
        level, dim, ds = self._slide_port.get_level_info(3)
        mask = self._mask_generator.generate(self._slide_port.read_thumbnail_rgb(level))

        planner = PatchPlanner(self._geometry)
        return planner.plan(
            solid_mask=mask,
            level_0_dim=self._slide_port.level0_dimensions,
            downsample_factor=ds,
        )

    def build_roi_coords(self, roi_bbox: tuple) -> list[PatchCoordinate]:
        level, dim, ds = self._slide_port.get_level_info(3)
        mask = self._mask_generator.generate(self._slide_port.read_thumbnail_rgb(level))

        # ROI mode: denser stride for better coverage in a limited region
        roi_stride = max(1, self._geometry.level0_window_size // 2)
        geom = InferenceGeometry(
            model_input_size=self._geometry.model_input_size,
            target_mpp=self._geometry.target_mpp,
            slide_mpp=self._geometry.slide_mpp,
            level0_window_size=self._geometry.level0_window_size,
            level0_stride=roi_stride,
            read_level=self._geometry.read_level,
            read_downsample=self._geometry.read_downsample,
        )

        planner = ROIPlanner(geom)
        return planner.plan(
            roi_bbox=roi_bbox,
            level_0_dim=self._slide_port.level0_dimensions,
            solid_mask=mask,
            downsample_factor=ds,
        )

    def build_coords(self, roi_bbox: Optional[tuple] = None) -> list[PatchCoordinate]:
        if roi_bbox:
            return self.build_roi_coords(roi_bbox)
        return self.build_full_slide_coords()
