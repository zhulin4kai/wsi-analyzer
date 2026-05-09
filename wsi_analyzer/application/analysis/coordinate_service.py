from typing import Optional

from wsi_analyzer.domain.analysis import PatchPlanner, ROIPlanner
from wsi_analyzer.domain.slide.coordinates import PatchCoordinate
from wsi_analyzer.domain.slide.slide_read_port import SlideReadPort


class AnalysisCoordinateService:
    def __init__(self, mask_generator, config, slide_port: SlideReadPort):
        self._mask_generator = mask_generator
        self._config = config
        self._slide_port = slide_port

    def resolve_target_level(self) -> tuple:
        return self._slide_port.resolve_target_level(self._config.target_mpp)

    def build_full_slide_coords(
        self, target_level: int, target_downsample: float
    ) -> list[PatchCoordinate]:
        level, dim, ds = self._slide_port.get_level_info(3)
        mask = self._mask_generator.generate(self._slide_port.read_thumbnail_rgb(level))

        planner = PatchPlanner(self._config.patch_size, self._config.stride)
        return planner.plan(
            solid_mask=mask,
            level_0_dim=self._slide_port.level0_dimensions,
            downsample_factor=ds,
            target_level=target_level,
            target_downsample=target_downsample,
        )

    def build_roi_coords(
        self, roi_bbox: tuple, target_level: int, target_downsample: float
    ) -> list[PatchCoordinate]:
        level, dim, ds = self._slide_port.get_level_info(3)
        mask = self._mask_generator.generate(self._slide_port.read_thumbnail_rgb(level))

        roi_stride = int(self._config.patch_size * 0.5)
        planner = ROIPlanner(self._config.patch_size, roi_stride)
        return planner.plan(
            roi_bbox=roi_bbox,
            level_0_dim=self._slide_port.level0_dimensions,
            solid_mask=mask,
            downsample_factor=ds,
            target_level=target_level,
            target_downsample=target_downsample,
        )

    def build_coords(
        self,
        roi_bbox: Optional[tuple],
        target_level: int,
        target_downsample: float,
    ) -> list[PatchCoordinate]:
        if roi_bbox:
            return self.build_roi_coords(roi_bbox, target_level, target_downsample)
        return self.build_full_slide_coords(target_level, target_downsample)
