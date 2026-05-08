from PIL import Image

from wsi_analyzer.domain.slide.coordinates import PatchCoordinate


class PatchReader:
    def __init__(self, engine, target_level: int, target_downsample: float, patch_size: int):
        self._engine = engine
        self._target_level = target_level
        self._target_downsample = target_downsample
        self._patch_size = patch_size
        _resample = getattr(Image, "Resampling", Image).LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
        self._resample = _resample

    def read(self, coord: PatchCoordinate) -> Image.Image:
        x, y = coord.x, coord.y
        if self._target_level == 0:
            patch_rgba = self._engine.read_region((x, y), 0, (self._patch_size, self._patch_size))
            return patch_rgba.convert("RGB")

        ts = max(1, int(self._patch_size / self._target_downsample))
        patch_rgba = self._engine.read_region((x, y), self._target_level, (ts, ts))
        patch_rgb = patch_rgba.convert("RGB")
        if patch_rgb.size != (self._patch_size, self._patch_size):
            patch_rgb = patch_rgb.resize((self._patch_size, self._patch_size), self._resample)
        return patch_rgb
