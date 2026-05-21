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

        tissue_index = TissueMaskIndex(solid_mask)
        if not tissue_index.has_tissue:
            return []

        x_positions, y_positions = tissue_index.candidate_positions(
            _grid_positions(w, win, stride),
            _grid_positions(h, win, stride),
            win=win,
            downsample_factor=downsample_factor,
        )

        coords: list[PatchCoordinate] = []
        for y in y_positions:
            for x in x_positions:
                if tissue_index.has_tissue_in_window(
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


class TissueMaskIndex:
    """Fast tissue-ratio queries for a binary tissue mask."""

    def __init__(self, solid_mask: np.ndarray):
        self._shape = solid_mask.shape
        tissue = solid_mask == 255
        integral = tissue.astype(np.uint8).cumsum(axis=0, dtype=np.int64).cumsum(
            axis=1, dtype=np.int64
        )
        self._integral = np.pad(integral, ((1, 0), (1, 0)), mode="constant")

        ys, xs = np.nonzero(tissue)
        if len(xs) == 0:
            self.has_tissue = False
            self._bbox = None
        else:
            self.has_tissue = True
            self._bbox = (
                int(xs.min()),
                int(ys.min()),
                int(xs.max()) + 1,
                int(ys.max()) + 1,
            )

    def has_tissue_in_window(
        self,
        x: int,
        y: int,
        win: int,
        downsample_factor: float,
        min_tissue_ratio: float = 0.01,
    ) -> bool:
        mx1, my1, mx2, my2 = _mask_window(
            self._shape, x, y, win, downsample_factor
        )
        area = (mx2 - mx1) * (my2 - my1)
        if area <= 0:
            return False
        tissue_ratio = float(self._rect_sum(mx1, my1, mx2, my2)) / float(area)
        return tissue_ratio >= min_tissue_ratio

    def candidate_positions(
        self,
        x_positions: list[int],
        y_positions: list[int],
        win: int,
        downsample_factor: float,
    ) -> tuple[list[int], list[int]]:
        if not self.has_tissue or self._bbox is None:
            return [], []

        mx1, my1, mx2, my2 = self._bbox
        min_x = mx1 * downsample_factor - win
        max_x = mx2 * downsample_factor
        min_y = my1 * downsample_factor - win
        max_y = my2 * downsample_factor
        return (
            [x for x in x_positions if x <= max_x and x + win >= min_x],
            [y for y in y_positions if y <= max_y and y + win >= min_y],
        )

    def _rect_sum(self, x1: int, y1: int, x2: int, y2: int) -> int:
        integral = self._integral
        return int(
            integral[y2, x2]
            - integral[y1, x2]
            - integral[y2, x1]
            + integral[y1, x1]
        )


def _mask_window(
    mask_shape: tuple[int, int],
    x: int,
    y: int,
    win: int,
    downsample_factor: float,
) -> tuple[int, int, int, int]:
    height, width = mask_shape
    mx1 = min(max(int(x / downsample_factor), 0), width - 1)
    my1 = min(max(int(y / downsample_factor), 0), height - 1)
    mx2 = min(max(int((x + win) / downsample_factor), mx1 + 1), width)
    my2 = min(max(int((y + win) / downsample_factor), my1 + 1), height)
    return mx1, my1, mx2, my2


def _has_tissue(
    solid_mask: np.ndarray,
    x: int,
    y: int,
    win: int,
    downsample_factor: float,
    min_tissue_ratio: float = 0.01,
) -> bool:
    return TissueMaskIndex(solid_mask).has_tissue_in_window(
        x=x,
        y=y,
        win=win,
        downsample_factor=downsample_factor,
        min_tissue_ratio=min_tissue_ratio,
    )
