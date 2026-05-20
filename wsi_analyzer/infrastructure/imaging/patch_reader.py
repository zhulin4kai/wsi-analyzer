from PIL import Image

from wsi_analyzer.domain.slide.coordinates import PatchCoordinate


class PatchReader:
    """Read a physical patch from a WSI engine using PatchCoordinate geometry.

    The scale interpretation is driven entirely by the PatchCoordinate:
      - coord.x, coord.y      → Level-0 top-left origin.
      - coord.level0_size     → physical side length on Level-0.
      - coord.read_level      → OpenSlide pyramid level.
      - coord.read_downsample → downsample of read_level relative to Level-0.
      - coord.model_input_size → final resize target (square).

    The resulting PIL.Image is always resized to model_input_size x model_input_size.
    """

    def __init__(self, engine):
        self._engine = engine
        self._resample = Image.Resampling.LANCZOS

    def read(self, coord: PatchCoordinate) -> Image.Image:
        read_size = max(1, round(coord.level0_size / coord.read_downsample))

        patch_rgba = self._engine.read_region(
            (coord.x, coord.y),
            coord.read_level,
            (read_size, read_size),
        )
        patch_rgb = patch_rgba.convert("RGB")

        if patch_rgb.size != (coord.model_input_size, coord.model_input_size):
            patch_rgb = patch_rgb.resize(
                (coord.model_input_size, coord.model_input_size),
                self._resample,
            )
        return patch_rgb
