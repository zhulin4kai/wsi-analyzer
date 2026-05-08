from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class SlideMetadata:
    """切片金字塔元数据的不可变快照，可安全跨线程传递。"""

    path: str
    level_0_dim: Tuple[int, int]
    level_count: int
    level_dimensions: List[Tuple[int, int]]
    level_downsamples: List[float]
    mpp: Optional[Tuple[float, float]]
    objective_power: Optional[float]

    def get_best_level_for_downsample(self, target_downsample: float) -> int:
        best = 0
        for i, ds in enumerate(self.level_downsamples):
            if ds <= target_downsample + 1e-6:
                best = i
        return best

    def get_best_level_for_mpp(self, target_mpp: float) -> int:
        if self.mpp is None or self.mpp[0] <= 0:
            return 0
        target_downsample = target_mpp / self.mpp[0]
        best_level = 0
        best_diff = float("inf")
        for i, ds in enumerate(self.level_downsamples):
            diff = abs(ds - target_downsample)
            if diff < best_diff:
                best_diff = diff
                best_level = i
        return best_level
