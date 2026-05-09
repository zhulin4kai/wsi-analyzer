from abc import ABC, abstractmethod


class SlideReadPort(ABC):
    @abstractmethod
    def resolve_target_level(self, target_mpp: float) -> tuple:
        """Returns (best_level, downsample_at_that_level)."""

    @abstractmethod
    def read_thumbnail_rgb(self, level: int):
        """Read thumbnail at given level, return RGB numpy array."""

    @abstractmethod
    def get_level_info(self, level: int) -> tuple:
        """Returns (clamped_level, dimensions, downsample_factor)."""

    @property
    @abstractmethod
    def level0_dimensions(self) -> tuple:
        """Width, height at Level 0."""
