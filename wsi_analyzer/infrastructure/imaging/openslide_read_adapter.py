import numpy as np

from wsi_analyzer.domain.slide.slide_read_port import SlideReadPort


class OpenSlideReadAdapter(SlideReadPort):
    def __init__(self, engine):
        self._engine = engine

    def resolve_target_level(self, target_mpp: float) -> tuple:
        level = self._engine.get_best_level_for_mpp(target_mpp)
        ds = self._engine.slide.level_downsamples[level]
        return level, ds

    def read_thumbnail_rgb(self, level: int) -> np.ndarray:
        _, dim, _ = self._engine.get_level_info(level)
        thumb = self._engine.read_region((0, 0), level, dim).convert("RGB")
        return np.array(thumb)

    def get_level_info(self, level: int) -> tuple:
        return self._engine.get_level_info(level)

    @property
    def level0_dimensions(self) -> tuple:
        return self._engine.level_0_dim
