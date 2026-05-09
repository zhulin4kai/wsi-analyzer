import numpy as np
from PySide6.QtGui import QImage, QPixmap

from wsi_analyzer.config.config import (
    HEATMAP_ALPHA,
    HEATMAP_ALPHA_GAMMA,
    HEATMAP_BIN_SIZE,
    HEATMAP_BLUR_SIGMA,
    HEATMAP_COLORMAP,
)
from wsi_analyzer.domain.detection.heatmap import compute_heatmap_grid, grid_to_rgba


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
        """Compute heatmap, set pixmap, return RGBA for minimap overlay."""
        if not results:
            self.clear()
            return None

        grid = compute_heatmap_grid(
            results, level_0_w, level_0_h,
            bin_size=HEATMAP_BIN_SIZE,
            blur_sigma=HEATMAP_BLUR_SIGMA,
        )
        rgba = grid_to_rgba(
            grid,
            alpha=HEATMAP_ALPHA,
            alpha_gamma=HEATMAP_ALPHA_GAMMA,
            colormap=HEATMAP_COLORMAP,
        )
        h, w = rgba.shape[:2]
        qimage = QImage(rgba.data, w, h, w * 4, QImage.Format_RGBA8888).copy()

        pixmap = QPixmap.fromImage(qimage)
        self._item.setPixmap(pixmap)
        self._item.setPos(0.0, 0.0)
        self._item.setScale(float(HEATMAP_BIN_SIZE))
        return rgba
