import math

import cv2
import numpy as np
from PySide6.QtGui import QImage, QPixmap

from wsi_analyzer.config.config import (
    HEATMAP_ALPHA,
    HEATMAP_ALPHA_GAMMA,
    HEATMAP_BIN_SIZE,
    HEATMAP_BLUR_SIGMA,
    HEATMAP_COLORMAP,
)


class HeatmapLayer:
    def __init__(self, item):
        self._item = item

    def set_visible(self, visible: bool):
        self._item.setVisible(visible)

    def set_opacity(self, opacity: float):
        self._item.setOpacity(opacity)

    def clear(self):
        self._item.setPixmap(QPixmap())

    def render(self, results: list, level_0_w: int, level_0_h: int) -> np.ndarray | None:
        """Compute heatmap from detection results, set on the pixmap item.

        Returns RGBA numpy array for minimap overlay, or None if empty.
        """
        if not results:
            self.clear()
            return None

        grid = self._compute_heatmap(results, level_0_w, level_0_h)
        qimage, rgba = self._grid_to_qimage(grid)

        pixmap = QPixmap.fromImage(qimage)
        self._item.setPixmap(pixmap)
        self._item.setPos(0.0, 0.0)
        self._item.setScale(float(HEATMAP_BIN_SIZE))
        return rgba

    def _compute_heatmap(self, results: list, wsi_w: int, wsi_h: int) -> np.ndarray:
        bin_size = HEATMAP_BIN_SIZE
        grid_w = max(1, math.ceil(wsi_w / bin_size))
        grid_h = max(1, math.ceil(wsi_h / bin_size))
        grid = np.zeros((grid_h, grid_w), dtype=np.float32)

        for det in results:
            try:
                x_min, y_min, x_max, y_max = det["bbox"]
                confidence = float(det["confidence"])
            except (KeyError, ValueError, TypeError):
                continue

            cx = (x_min + x_max) * 0.5
            cy = (y_min + y_max) * 0.5
            gx = min(int(cx / bin_size), grid_w - 1)
            gy = min(int(cy / bin_size), grid_h - 1)
            gx = max(0, gx)
            gy = max(0, gy)
            grid[gy, gx] += confidence

        base_sigma = float(HEATMAP_BLUR_SIGMA)
        if base_sigma > 0 and grid.max() > 1e-8:
            n = len(results)
            if n < 50:
                sigma = 5.0
            elif n < 500:
                sigma = base_sigma
            else:
                sigma = max(2.0, base_sigma * 0.6)

            k = int(math.ceil(3.0 * sigma)) * 2 + 1
            k = max(3, k)
            short_side = min(grid_h, grid_w)
            k_max = max(3, short_side // 2 * 2 - 1)
            k = min(k, k_max)
            grid = cv2.GaussianBlur(grid, (k, k), sigma)

        max_val = float(grid.max())
        if max_val > 1e-8:
            grid = grid / max_val

        return grid.astype(np.float32)

    def _grid_to_qimage(self, grid_norm: np.ndarray) -> tuple[QImage, np.ndarray]:
        gray_u8 = np.clip(grid_norm * 255.0, 0, 255).astype(np.uint8)
        colormap_bgr = cv2.applyColorMap(gray_u8, int(HEATMAP_COLORMAP))
        rgba = cv2.cvtColor(colormap_bgr, cv2.COLOR_BGR2RGBA)
        alpha_channel = np.clip(
            np.power(grid_norm, HEATMAP_ALPHA_GAMMA) * float(HEATMAP_ALPHA), 0, 255
        ).astype(np.uint8)
        rgba[:, :, 3] = alpha_channel

        h, w = rgba.shape[:2]
        qimage = QImage(rgba.data, w, h, w * 4, QImage.Format_RGBA8888)
        return qimage.copy(), rgba
