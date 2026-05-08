import cv2
import numpy as np


class TissueMaskGenerator:
    def __init__(self, min_area_ratio: float = 0.001):
        self._min_area_ratio = min_area_ratio

    def generate(self, thumbnail_rgb: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(thumbnail_rgb, cv2.COLOR_RGB2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        binary_cleaned = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

        contours, _ = cv2.findContours(
            binary_cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        solid_mask = np.zeros_like(gray)

        total_area = gray.shape[0] * gray.shape[1]
        min_area = total_area * self._min_area_ratio

        valid_contours = [cnt for cnt in contours if cv2.contourArea(cnt) > min_area]
        cv2.drawContours(solid_mask, valid_contours, -1, 255, thickness=-1)

        return solid_mask
