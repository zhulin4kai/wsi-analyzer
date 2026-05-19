import cv2
import numpy as np


class TissueMaskGenerator:
    def __init__(
        self,
        min_area_ratio: float = 0.001,
        min_tissue_ratio: float = 0.005,
        use_hsv_saturation: bool = True,
        blur_kernel_size: int = 5,
    ):
        self._min_area_ratio = min_area_ratio
        self._min_tissue_ratio = min_tissue_ratio
        self._use_hsv_saturation = use_hsv_saturation
        self._blur_kernel_size = blur_kernel_size if blur_kernel_size % 2 == 1 else blur_kernel_size + 1
        self._last_stats = {
            "mask_tissue_ratio": 0.0,
            "component_count": 0,
        }

    def generate(self, thumbnail_rgb: np.ndarray) -> np.ndarray:
        channel = self._build_channel(thumbnail_rgb)
        if self._blur_kernel_size > 1:
            channel = cv2.GaussianBlur(channel, (self._blur_kernel_size, self._blur_kernel_size), 0)

        _, binary = cv2.threshold(channel, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        binary_open = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
        binary_cleaned = cv2.morphologyEx(binary_open, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(
            binary_cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        solid_mask = np.zeros(binary_cleaned.shape, dtype=np.uint8)

        total_area = binary_cleaned.shape[0] * binary_cleaned.shape[1]
        min_area = total_area * self._min_area_ratio

        valid_contours = [cnt for cnt in contours if cv2.contourArea(cnt) > min_area]
        cv2.drawContours(solid_mask, valid_contours, -1, 255, thickness=-1)

        tissue_ratio = float(np.count_nonzero(solid_mask == 255)) / float(total_area)
        self._last_stats = {
            "mask_tissue_ratio": tissue_ratio,
            "component_count": len(valid_contours),
        }
        if tissue_ratio < self._min_tissue_ratio:
            return np.zeros_like(solid_mask)
        return solid_mask

    @property
    def last_stats(self) -> dict:
        return dict(self._last_stats)

    def _build_channel(self, thumbnail_rgb: np.ndarray) -> np.ndarray:
        if self._use_hsv_saturation:
            hsv = cv2.cvtColor(thumbnail_rgb, cv2.COLOR_RGB2HSV)
            return hsv[:, :, 1]
        gray = cv2.cvtColor(thumbnail_rgb, cv2.COLOR_RGB2GRAY)
        return cv2.bitwise_not(gray)
