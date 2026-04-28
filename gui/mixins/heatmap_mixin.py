import math
from typing import Tuple

import cv2
import numpy as np
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QCheckBox

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


class HeatmapMixin:
    def _init_heatmap_ui(self):
        from PySide6.QtGui import QAction

        self.chk_show_heatmap = QAction("热力图", self)
        self.chk_show_heatmap.setCheckable(True)
        self.chk_show_heatmap.setChecked(False)
        self.chk_show_heatmap.toggled.connect(self.toggle_heatmap_visibility)
        self._ai_toolbar.insertAction(self.export_separator, self.chk_show_heatmap)

        self.viewer.zoom_changed.connect(self._on_zoom_changed_lod)

    def toggle_heatmap_visibility(self, checked):
        if not hasattr(self, "heatmap_layer_item"):
            return
        visible = bool(checked)
        self.heatmap_layer_item.setVisible(visible)
        # 立即同步 LOD 透明度，防止从隐藏状态重新显示时停留在旧 opacity
        if visible and hasattr(self, "viewer"):
            self._on_zoom_changed_lod(self.viewer.transform().m11())

    def _on_zoom_changed_lod(self, scale: float):
        if not hasattr(self, "heatmap_layer_item"):
            return
        # 热力图被用户手动隐藏时，LOD 不干预
        if hasattr(self, "chk_show_heatmap") and not self.chk_show_heatmap.isChecked():
            return

        if scale < HEATMAP_LOD_MACRO_THRESH:
            # 宏观全片视野：热力图完全不透明，是空间分布的主要信息来源
            self.heatmap_layer_item.setOpacity(1.0)
        elif scale < HEATMAP_LOD_MID_THRESH:
            # 中等倍率：热力图半透明，与矩形检测框协同显示
            self.heatmap_layer_item.setOpacity(0.7)
        else:
            # 高倍率局部：热力图退为辅助，降低不透明度防止遮挡细节
            self.heatmap_layer_item.setOpacity(0.4)

    def _update_heatmap_layer(self):
        if not hasattr(self, "heatmap_layer_item"):
            return

        if not self.current_ai_results:
            self._clear_heatmap()
            return

        if not getattr(self.viewer, "_metadata", None):
            return

        wsi_w, wsi_h = self.viewer._metadata.level_0_dim
        grid = self._compute_heatmap(self.current_ai_results, wsi_w, wsi_h)
        qimage, rgba = self._grid_to_qimage(grid)

        pixmap = QPixmap.fromImage(qimage)
        self.heatmap_layer_item.setPixmap(pixmap)
        self.heatmap_layer_item.setPos(0.0, 0.0)
        self.heatmap_layer_item.setScale(float(HEATMAP_BIN_SIZE))
        self.heatmap_layer_item.setVisible(self.chk_show_heatmap.isChecked())

        self._on_zoom_changed_lod(self.viewer.transform().m11())

        self._update_minimap_heatmap(rgba)

    def _clear_heatmap(self):
        if hasattr(self, "heatmap_layer_item"):
            self.heatmap_layer_item.setPixmap(QPixmap())

        # 同步清空鹰眼图热力图叠层
        if hasattr(self, "minimap") and hasattr(self.minimap, "heatmap_mini_item"):
            self.minimap.heatmap_mini_item.setPixmap(QPixmap())

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
            # clamp 至格子范围，防止浮点计算导致越界
            gx = min(int(cx / bin_size), grid_w - 1)
            gy = min(int(cy / bin_size), grid_h - 1)
            gx = max(0, gx)
            gy = max(0, gy)
            grid[gy, gx] += confidence

        # 自适应高斯平滑（方向一）
        base_sigma = float(HEATMAP_BLUR_SIGMA)
        if base_sigma > 0 and grid.max() > 1e-8:
            n = len(results)
            if n < 50:
                sigma = 5.0
            elif n < 500:
                sigma = base_sigma
            else:
                sigma = max(2.0, base_sigma * 0.6)

            # 核大小：取 ceil(3σ)×2+1 覆盖 99.7% 高斯能量
            k = int(math.ceil(3.0 * sigma)) * 2 + 1
            k = max(3, k)

            # 防御：核大小不超过格子矩阵短边的一半（避免极小矩阵过度平滑）
            short_side = min(grid_h, grid_w)
            k_max = max(3, short_side // 2 * 2 - 1)
            k = min(k, k_max)

            grid = cv2.GaussianBlur(grid, (k, k), sigma)

        # 归一化至 [0, 1]
        max_val = float(grid.max())
        if max_val > 1e-8:
            grid = grid / max_val

        return grid.astype(np.float32)

    def _grid_to_qimage(self, grid_norm: np.ndarray) -> Tuple[QImage, np.ndarray]:
        gray_u8 = np.clip(grid_norm * 255.0, 0, 255).astype(np.uint8)

        colormap_bgr = cv2.applyColorMap(gray_u8, int(HEATMAP_COLORMAP))

        rgba = cv2.cvtColor(colormap_bgr, cv2.COLOR_BGR2RGBA)

        alpha_channel = np.clip(
            np.power(grid_norm, gamma) * float(HEATMAP_ALPHA), 0, 255
        ).astype(np.uint8)
        rgba[:, :, 3] = alpha_channel

        h, w = rgba.shape[:2]
        bytes_per_line = w * 4

        qimage = QImage(rgba.data, w, h, bytes_per_line, QImage.Format_RGBA8888)

        return qimage.copy(), rgba

    def _update_minimap_heatmap(self, rgba: np.ndarray) -> None:
        if not (
            hasattr(self, "minimap")
            and hasattr(self.minimap, "heatmap_mini_item")
            and hasattr(self.minimap, "bg_item")
        ):
            return

        if rgba is None or rgba.ndim != 3 or rgba.shape[2] != 4:
            return

        mini_size = self.minimap.bg_item.pixmap().size()
        if mini_size.isEmpty():
            # 切片尚未加载，底图为空，跳过
            return

        mini_w, mini_h = mini_size.width(), mini_size.height()

        mini_rgba = cv2.resize(
            rgba,
            (mini_w, mini_h),
            interpolation=cv2.INTER_LINEAR,
        )

        extra_sigma = float(HEATMAP_MINI_BLUR_SIGMA)
        if extra_sigma > 0:
            k = int(math.ceil(3.0 * extra_sigma)) * 2 + 1
            k = max(3, k)
            k = min(k, max(3, min(mini_h, mini_w) // 2 * 2 - 1))
            mini_rgba[:, :, :3] = cv2.GaussianBlur(
                mini_rgba[:, :, :3], (k, k), extra_sigma
            )
            mini_rgba[:, :, 3] = cv2.GaussianBlur(
                mini_rgba[:, :, 3], (k, k), extra_sigma
            )

        bytes_per_line = mini_w * 4
        mini_qi = QImage(
            mini_rgba.data, mini_w, mini_h, bytes_per_line, QImage.Format_RGBA8888
        ).copy()

        self.minimap.heatmap_mini_item.setPixmap(QPixmap.fromImage(mini_qi))
        self.minimap.heatmap_mini_item.setPos(0.0, 0.0)
