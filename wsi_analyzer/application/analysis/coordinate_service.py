from typing import Optional

from wsi_analyzer.domain.analysis import PatchPlanner, ROIPlanner
from wsi_analyzer.domain.slide.coordinates import PatchCoordinate


class AnalysisCoordinateService:
    def __init__(self, mask_generator, config, engine):
        self._mask_generator = mask_generator
        self._config = config
        self._engine = engine

    @property
    def engine(self):
        return self._engine

    def resolve_target_level(self) -> tuple:
        """Returns (target_level, target_downsample)."""
        level = self._engine.get_best_level_for_mpp(self._config.target_mpp)
        ds = self._engine.slide.level_downsamples[level]
        return level, ds

    def build_full_slide_coords(
        self, target_level: int, target_downsample: float
    ) -> list[PatchCoordinate]:
        level, dim, ds = self._engine.get_level_info(3)
        thumb = self._engine.read_region((0, 0), level, dim).convert("RGB")

        import numpy as np
        mask = self._mask_generator.generate(np.array(thumb))

        planner = PatchPlanner(self._config.patch_size, self._config.stride)
        return planner.plan(
            solid_mask=mask,
            level_0_dim=self._engine.level_0_dim,
            downsample_factor=ds,
            target_level=target_level,
            target_downsample=target_downsample,
        )

    def build_roi_coords(
        self, roi_bbox: tuple, target_level: int, target_downsample: float
    ) -> list[PatchCoordinate]:
        level, dim, ds = self._engine.get_level_info(3)
        thumb = self._engine.read_region((0, 0), level, dim).convert("RGB")

        import numpy as np
        mask = self._mask_generator.generate(np.array(thumb))

        roi_stride = int(self._config.patch_size * 0.5)
        planner = ROIPlanner(self._config.patch_size, roi_stride)
        return planner.plan(
            roi_bbox=roi_bbox,
            level_0_dim=self._engine.level_0_dim,
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
