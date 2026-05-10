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
        patch centre falls on valid tissue mask.

        Parameters:
            solid_mask:      2D uint8 array (255 = tissue, 0 = background).
            level_0_dim:     (w, h) of WSI Level-0 in pixels.
            downsample_factor: mask downsample relative to Level-0.
        """
        geom = self._geom
        w, h = level_0_dim
        win = geom.level0_window_size
        stride = geom.level0_stride

        coords: list[PatchCoordinate] = []
        for y in range(0, h - win + 1, stride):
            for x in range(0, w - win + 1, stride):
                # centre of the Level-0 window
                cx = x + win / 2
                cy = y + win / 2
                mx = min(max(int(cx / downsample_factor), 0), solid_mask.shape[1] - 1)
                my = min(max(int(cy / downsample_factor), 0), solid_mask.shape[0] - 1)

                if solid_mask[my, mx] == 255:
                    coords.append(PatchCoordinate(
                        x=x,
                        y=y,
                        level0_size=win,
                        model_input_size=geom.model_input_size,
                        read_level=geom.read_level,
                        read_downsample=geom.read_downsample,
                    ))
        return coords
