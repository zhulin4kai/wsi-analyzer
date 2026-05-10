import numpy as np

from wsi_analyzer.domain.slide.coordinates import PatchCoordinate


class PatchPlanner:
    def __init__(self, patch_size: int, stride: int):
        self.patch_size = patch_size
        self.stride = stride

    def plan(
        self,
        solid_mask: np.ndarray,
        level_0_dim: tuple,
        downsample_factor: float,
        target_level: int = 0,
        target_downsample: float = 1.0,
    ) -> list[PatchCoordinate]:
        w, h = level_0_dim
        coords = []
        for y in range(0, h - self.patch_size + 1, self.stride):
            for x in range(0, w - self.patch_size + 1, self.stride):
                cx = x + self.patch_size / 2
                cy = y + self.patch_size / 2
                mx = min(max(int(cx / downsample_factor), 0), solid_mask.shape[1] - 1)
                my = min(max(int(cy / downsample_factor), 0), solid_mask.shape[0] - 1)

                if solid_mask[my, mx] == 255:
                    coords.append(PatchCoordinate(
                        x=x, y=y,
                        size=self.patch_size,
                        read_level=target_level,
                        read_level_downsample=target_downsample,
                    ))
        return coords
