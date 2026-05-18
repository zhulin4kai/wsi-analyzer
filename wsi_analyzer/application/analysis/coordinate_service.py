from typing import Optional

from wsi_analyzer.domain.analysis import PatchPlanner, ROIPlanner
from wsi_analyzer.domain.slide.coordinates import PatchCoordinate
from wsi_analyzer.domain.slide.slide_read_port import SlideReadPort


class AnalysisCoordinateService:
    def __init__(self, mask_generator, geometry, slide_port: SlideReadPort):
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
        planner = ROIPlanner(self._geometry)
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
