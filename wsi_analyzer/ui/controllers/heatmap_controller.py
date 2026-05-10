import math

import cv2
import numpy as np
from PySide6.QtGui import QImage, QPixmap

from wsi_analyzer.config.config import (
    HEATMAP_LOD_MACRO_THRESH,
    HEATMAP_LOD_MID_THRESH,
    HEATMAP_MINI_BLUR_SIGMA,
)
from wsi_analyzer.app.dependency_container import container


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

    def toggle_heatmap_visibility(self, checked):
        self._layers.heatmap.set_visible(bool(checked))
        if checked:
            self._on_zoom_changed_lod(self._viewer.transform().m11())

    def _on_zoom_changed_lod(self, scale: float):
        if self.chk_show_heatmap and not self.chk_show_heatmap.isChecked():
            return
        if scale < float(HEATMAP_LOD_MACRO_THRESH):
            self._layers.heatmap.set_opacity(1.0)
        elif scale < float(HEATMAP_LOD_MID_THRESH):
            self._layers.heatmap.set_opacity(0.7)
        else:
            self._layers.heatmap.set_opacity(0.4)

    def update_heatmap_layer(self):
        w = self._window
        layers = self._layers

        show_imported = container.database.settings.get_setting("show_imported_heatmap", True)
        results = list(w.current_ai_results)
        if show_imported and hasattr(w, "current_imported_annotations"):
            results.extend(w.current_imported_annotations)

        if not results:
            self.clear_heatmap()
            return

        md = self._viewer.current_metadata
        if not md:
            return

        wsi_w, wsi_h = md.level_0_dim
        rgba = layers.heatmap.render(results, wsi_w, wsi_h)
        if self.chk_show_heatmap:
            layers.heatmap.set_visible(self.chk_show_heatmap.isChecked())
        self._on_zoom_changed_lod(self._viewer.transform().m11())
        self._update_minimap_heatmap(rgba)
        self._viewer.viewport().update()

    def clear_heatmap(self):
        self._layers.heatmap.clear()
        m = self._minimap
        if m and hasattr(m, "heatmap_mini_item"):
            m.heatmap_mini_item.setPixmap(QPixmap())

    def _update_minimap_heatmap(self, rgba: np.ndarray | None):
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
            k = min(k, max(3, int(min(mini_h, mini_w)) // 2 * 2 - 1))
            mini_rgba[:, :, :3] = cv2.GaussianBlur(mini_rgba[:, :, :3], (k, k), extra_sigma)
            mini_rgba[:, :, 3] = cv2.GaussianBlur(mini_rgba[:, :, 3], (k, k), extra_sigma)

        mini_qi = QImage(
            mini_rgba.data, mini_w, mini_h, mini_w * 4, QImage.Format.Format_RGBA8888
        ).copy()

        m.heatmap_mini_item.setPixmap(QPixmap.fromImage(mini_qi))
        m.heatmap_mini_item.setPos(0.0, 0.0)
