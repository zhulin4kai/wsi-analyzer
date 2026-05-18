import numpy as np

from wsi_analyzer.domain.analysis.inference_geometry import InferenceGeometry
from wsi_analyzer.domain.slide.coordinates import PatchCoordinate


class PatchPlanner:
    """Generate PatchCoordinate list by sliding a Level-0 window over tissue mask."""

    def __init__(self, geometry: InferenceGeometry):
        self._geom = geometry

    def plan(
        self,
        solid_mask: np.ndarray,
        level_0_dim: tuple[int, int],
        downsample_factor: float,
    ) -> list[PatchCoordinate]:
        """Slide over Level-0 space, emit a PatchCoordinate wherever the
        patch contains enough tissue area.

        Parameters:
            solid_mask:      2D uint8 array (255 = tissue, 0 = background).
            level_0_dim:     (w, h) of WSI Level-0 in pixels.
            downsample_factor: mask downsample relative to Level-0.
        """
        geom = self._geom
        w, h = level_0_dim
        win = geom.level0_window_size
        stride = geom.level0_stride

        x_positions = _grid_positions(w, win, stride)
        y_positions = _grid_positions(h, win, stride)

        coords: list[PatchCoordinate] = []
        for y in y_positions:
            for x in x_positions:
                if _has_tissue(
                    solid_mask=solid_mask,
                    x=x,
                    y=y,
                    win=win,
                    downsample_factor=downsample_factor,
                ):
                    coords.append(PatchCoordinate(
                        x=x,
                        y=y,
                        level0_size=win,
                        model_input_size=geom.model_input_size,
                        read_level=geom.read_level,
                        read_downsample=geom.read_downsample,
                    ))
        return coords


def _grid_positions(size: int, win: int, stride: int) -> list[int]:
    if size <= win:
        return [0]
    positions = list(range(0, size - win + 1, stride))
    last = size - win
    if positions[-1] != last:
        positions.append(last)
    return positions


def _has_tissue(
    solid_mask: np.ndarray,
    x: int,
    y: int,
    win: int,
    downsample_factor: float,
    min_tissue_ratio: float = 0.01,
) -> bool:
    mx1 = min(max(int(x / downsample_factor), 0), solid_mask.shape[1] - 1)
    my1 = min(max(int(y / downsample_factor), 0), solid_mask.shape[0] - 1)
    mx2 = min(max(int((x + win) / downsample_factor), mx1 + 1), solid_mask.shape[1])
    my2 = min(max(int((y + win) / downsample_factor), my1 + 1), solid_mask.shape[0])
    patch_mask = solid_mask[my1:my2, mx1:mx2]
    if patch_mask.size == 0:
        return False
    tissue_ratio = float(np.count_nonzero(patch_mask == 255)) / float(patch_mask.size)
    return tissue_ratio >= min_tissue_ratio
