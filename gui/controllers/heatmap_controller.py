import math

import cv2
import numpy as np
from PySide6.QtGui import QImage, QPixmap

from config import (
    HEATMAP_ALPHA,
    HEATMAP_ALPHA_GAMMA,
    HEATMAP_BIN_SIZE,
    HEATMAP_BLUR_SIGMA,
    HEATMAP_COLORMAP,
    HEATMAP_LOD_MACRO_THRESH,
    HEATMAP_LOD_MID_THRESH,
    HEATMAP_MINI_BLUR_SIGMA,
)
from utils import DatabaseManager


class HeatmapController:
    def __init__(self, window, viewer, layers, minimap, toolbar, export_separator):
        self._window = window
        self._viewer = viewer
        self._layers = layers
        self._minimap = minimap
        self._toolbar = toolbar
        self._export_separator = export_separator
        self.chk_show_heatmap = None

    def setup_ui(self):
        from PySide6.QtGui import QAction

        self.chk_show_heatmap = QAction("热力图", self._window)
        self.chk_show_heatmap.setCheckable(True)
        self.chk_show_heatmap.setChecked(False)
        self.chk_show_heatmap.toggled.connect(self.toggle_heatmap_visibility)
        self._toolbar.insertAction(self._export_separator, self.chk_show_heatmap)

        self._viewer.zoom_changed.connect(self._on_zoom_changed_lod)

    # ── visibility / LOD ───────────────────────────────────────────

    def toggle_heatmap_visibility(self, checked):
        item = self._layers.heatmap_layer_item
        visible = bool(checked)
        item.setVisible(visible)
        if visible:
            self._on_zoom_changed_lod(self._viewer.transform().m11())

    def _on_zoom_changed_lod(self, scale: float):
        item = self._layers.heatmap_layer_item
        if self.chk_show_heatmap and not self.chk_show_heatmap.isChecked():
            return

        if scale < HEATMAP_LOD_MACRO_THRESH:
            item.setOpacity(1.0)
        elif scale < HEATMAP_LOD_MID_THRESH:
            item.setOpacity(0.7)
        else:
            item.setOpacity(0.4)

    # ── heatmap generation ─────────────────────────────────────────

    def _update_heatmap_layer(self):
        w = self._window
        item = self._layers.heatmap_layer_item

        show_imported = DatabaseManager().settings.get_setting("show_imported_heatmap", True)
        results = list(w.current_ai_results)
        if show_imported and hasattr(w, "current_imported_annotations"):
            results.extend(w.current_imported_annotations)

        if not results:
            self._clear_heatmap()
            return

        md = self._viewer.current_metadata
        if not md:
            return

        wsi_w, wsi_h = md.level_0_dim
        grid = self._compute_heatmap(results, wsi_w, wsi_h)
        qimage, rgba = self._grid_to_qimage(grid)

        pixmap = QPixmap.fromImage(qimage)
        item.prepareGeometryChange()
        item.setPixmap(pixmap)
        item.setPos(0.0, 0.0)
        item.setScale(float(HEATMAP_BIN_SIZE))
        if self.chk_show_heatmap:
            item.setVisible(self.chk_show_heatmap.isChecked())

        self._on_zoom_changed_lod(self._viewer.transform().m11())
        self._update_minimap_heatmap(rgba)
        self._viewer.viewport().update()

    def _clear_heatmap(self):
        self._layers.heatmap_layer_item.setPixmap(QPixmap())

        m = self._minimap
        if m and hasattr(m, "heatmap_mini_item"):
            m.heatmap_mini_item.setPixmap(QPixmap())

    # ── computation ────────────────────────────────────────────────

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

    def _grid_to_qimage(self, grid_norm: np.ndarray) -> tuple:
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

    def _update_minimap_heatmap(self, rgba: np.ndarray):
        m = self._minimap
        if not (m and hasattr(m, "heatmap_mini_item") and hasattr(m, "bg_item")):
            return
        if rgba is None or rgba.ndim != 3 or rgba.shape[2] != 4:
            return

        mini_size = m.bg_item.pixmap().size()
        if mini_size.isEmpty():
            return

        mini_w, mini_h = mini_size.width(), mini_size.height()
        mini_rgba = cv2.resize(rgba, (mini_w, mini_h), interpolation=cv2.INTER_LINEAR)

        extra_sigma = float(HEATMAP_MINI_BLUR_SIGMA)
        if extra_sigma > 0:
            k = int(math.ceil(3.0 * extra_sigma)) * 2 + 1
            k = max(3, k)
            k = min(k, max(3, min(mini_h, mini_w) // 2 * 2 - 1))
            mini_rgba[:, :, :3] = cv2.GaussianBlur(mini_rgba[:, :, :3], (k, k), extra_sigma)
            mini_rgba[:, :, 3] = cv2.GaussianBlur(mini_rgba[:, :, 3], (k, k), extra_sigma)

        mini_qi = QImage(
            mini_rgba.data, mini_w, mini_h, mini_w * 4, QImage.Format_RGBA8888
        ).copy()

        m.heatmap_mini_item.setPixmap(QPixmap.fromImage(mini_qi))
        m.heatmap_mini_item.setPos(0.0, 0.0)
