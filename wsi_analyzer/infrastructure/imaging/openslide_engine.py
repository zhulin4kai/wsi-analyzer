from typing import Optional, Tuple

import openslide


class OpenSlideEngine:
    def __init__(self, file_path):
        self.file_path = file_path
        self.slide = openslide.OpenSlide(file_path)
        self.level_0_dim = self.slide.dimensions

    def get_thumbnail(self, level_from_last=1):
        level = max(0, self.slide.level_count - level_from_last)
        dim = self.slide.level_dimensions[level]
        thumb_rgba = self.slide.read_region((0, 0), level, dim)
        thumb_img = thumb_rgba.convert("RGB")
        downsample_factor = self.level_0_dim[0] / dim[0]
        return thumb_img, downsample_factor

    def get_level_info(self, target_level):
        level = min(target_level, self.slide.level_count - 1)
        dim = self.slide.level_dimensions[level]
        downsample_factor = self.slide.level_downsamples[level]
        return level, dim, downsample_factor

    def read_region(self, location, level, size):
        return self.slide.read_region(location, level, size)

    def get_mpp(self) -> Optional[Tuple[float, float]]:
        try:
            mpp_x = float(self.slide.properties.get(openslide.PROPERTY_NAME_MPP_X, 0))
            mpp_y = float(self.slide.properties.get(openslide.PROPERTY_NAME_MPP_Y, 0))
            if mpp_x > 0 and mpp_y > 0:
                return mpp_x, mpp_y
        except (ValueError, TypeError):
            pass
        return None

    def get_objective_power(self) -> Optional[float]:
        try:
            power = self.slide.properties.get(openslide.PROPERTY_NAME_OBJECTIVE_POWER, None)
            if power is not None:
                return float(power)
        except (ValueError, TypeError):
            pass
        return None

    def get_best_level_for_mpp(self, target_mpp: float) -> int:
        mpp = self.get_mpp()
        if mpp is None or mpp[0] <= 0:
            return 0
        target_downsample = target_mpp / mpp[0]
        best_level = 0
        best_diff = float("inf")
        for i, ds in enumerate(self.slide.level_downsamples):
            diff = abs(ds - target_downsample)
            if diff < best_diff:
                best_diff = diff
                best_level = i
        return best_level

    def close(self):
        self.slide.close()
