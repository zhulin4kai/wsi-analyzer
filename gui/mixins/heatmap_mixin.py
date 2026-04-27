import math
from typing import Tuple

import cv2
import numpy as np
from PySide6.QtGui import QImage, QPixmap, QTransform
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
    """AI 检测结果的空间密度热力图叠加层。

    职责范围：
    - 工具栏复选框的构建与信号绑定
    - 基于 current_ai_results 的格子矩阵计算与自适应高斯平滑
    - 幂函数 Alpha 伪彩色映射及 QImage/QPixmap 生成
    - heatmap_layer_item 的刷新、清空与可见性控制
    - zoom_changed 驱动的 LOD 透明度自适应（方向二）

    依赖约定：
    - 宿主类须在 __init__ 中创建 self.heatmap_layer_item (QGraphicsPixmapItem)
      并调用 self._init_heatmap_ui()。
    - 宿主类须暴露 self.current_ai_results、self.viewer.slide_engine 两个属性。
    - AnalysisToolbarMixin._init_ai_ui() 须将工具栏引用存为 self._ai_toolbar。
    - WSIView 须发出 zoom_changed(float) 信号，_init_heatmap_ui() 内部订阅它。
    """

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    def _init_heatmap_ui(self):
        """在 AI 工具栏末尾追加热力图显隐复选框，并绑定 LOD 缩放信号。

        须在 _init_ai_ui() 之后、_init_menu() 之前调用，
        以保证 self._ai_toolbar 已存在且 _init_menu 可访问
        self.chk_show_heatmap。
        """
        self._ai_toolbar.addSeparator()
        self.chk_show_heatmap = QCheckBox("显示热力图")
        self.chk_show_heatmap.setChecked(False)
        self.chk_show_heatmap.stateChanged.connect(self.toggle_heatmap_visibility)
        self._ai_toolbar.addWidget(self.chk_show_heatmap)

        # 方向二：订阅缩放信号，驱动 LOD 透明度自适应
        # zoom_changed 由 WSIView 在每次变换后发出，携带当前 m11 值
        self.viewer.zoom_changed.connect(self._on_zoom_changed_lod)

    # ------------------------------------------------------------------
    # 可见性控制
    # ------------------------------------------------------------------

    def toggle_heatmap_visibility(self, state):
        """响应"显示热力图"复选框，切换热力图层整体可见性。

        可见性打开时立即应用当前缩放级别的 LOD 透明度，无需等待
        下一次 zoom_changed 信号才能恢复正确的不透明度。

        Args:
            state: stateChanged 信号传入的 int（0=未选, 2=已选）。
                   注意：此 PySide6 版本中 stateChanged 发出 int 而非
                   Qt.CheckState 枚举，直接用 bool() 转换，避免 enum != int
                   的比较永远为 False 的问题。
        """
        if not hasattr(self, "heatmap_layer_item"):
            return
        visible = bool(state)
        self.heatmap_layer_item.setVisible(visible)
        # 立即同步 LOD 透明度，防止从隐藏状态重新显示时停留在旧 opacity
        if visible and hasattr(self, "viewer"):
            self._on_zoom_changed_lod(self.viewer.transform().m11())

    # ------------------------------------------------------------------
    # LOD 透明度自适应（方向二）
    # ------------------------------------------------------------------

    def _on_zoom_changed_lod(self, scale: float):
        """根据当前缩放级别自适应调整热力图透明度。

        阈值设计：
          scale < MACRO_THRESH (0.25×)  → opacity 1.0  热力图为主要信息
          scale < MID_THRESH   (0.50×)  → opacity 0.7  热力图与检测框并重
          scale ≥ MID_THRESH             → opacity 0.4  热力图退为背景参考

        设计约束：
          - 只修改 heatmap_layer_item 的 opacity，不接触 ai_layer_group，
            避免与 _on_interaction_start / _on_interaction_finish 的
            setVisible 逻辑产生冲突（见规范文档方向二风险 2）。
          - 用户已隐藏热力图时（isChecked=False）直接返回，不干预可见性。

        Args:
            scale: viewer.transform().m11()，即 Level-0 像素在屏幕上的像素数。
        """
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

    # ------------------------------------------------------------------
    # 生命周期管理
    # ------------------------------------------------------------------

    def _update_heatmap_layer(self):
        """基于 current_ai_results 重新计算并刷新热力图层。

        须在主线程调用（QPixmap 不可在子线程创建）。
        若结果为空则自动清空显示。
        计算完成后立即触发一次 LOD 透明度同步，确保热力图在
        初次显示或从数据库加载时就具有正确的不透明度（修复方向二风险 4：
        推理/缓存加载后若用户未缩放，LOD 不会因 zoom_changed 触发）。
        """
        if not hasattr(self, "heatmap_layer_item"):
            return

        if not self.current_ai_results:
            self._clear_heatmap()
            return

        if not (hasattr(self.viewer, "slide_engine") and self.viewer.slide_engine):
            return

        wsi_w, wsi_h = self.viewer.slide_engine.level_0_dim
        grid = self._compute_heatmap(self.current_ai_results, wsi_w, wsi_h)
        qimage, rgba = self._grid_to_qimage(grid)

        pixmap = QPixmap.fromImage(qimage)
        self.heatmap_layer_item.setPixmap(pixmap)
        self.heatmap_layer_item.setPos(0.0, 0.0)
        self.heatmap_layer_item.setScale(float(HEATMAP_BIN_SIZE))
        self.heatmap_layer_item.setVisible(self.chk_show_heatmap.isChecked())

        # 立即应用 LOD，不依赖下一次 zoom_changed 信号
        self._on_zoom_changed_lod(self.viewer.transform().m11())

        # 方向三：同步更新鹰眼图热力图叠层
        self._update_minimap_heatmap(rgba)

    def _clear_heatmap(self):
        """清空热力图显示。

        在切换切片或用户清除分析结果时调用，仅清除 pixmap 内容，
        不销毁 Scene item（item 由 MainWindow 统一管理生命周期）。
        """
        if hasattr(self, "heatmap_layer_item"):
            self.heatmap_layer_item.setPixmap(QPixmap())

        # 同步清空鹰眼图热力图叠层
        if hasattr(self, "minimap") and hasattr(self.minimap, "heatmap_mini_item"):
            self.minimap.heatmap_mini_item.setPixmap(QPixmap())

    # ------------------------------------------------------------------
    # 核心计算（方向一：自适应 sigma）
    # ------------------------------------------------------------------

    def _compute_heatmap(self, results: list, wsi_w: int, wsi_h: int) -> np.ndarray:
        """将检测结果映射到归一化热力网格。

        以每个检测框的中心点为采样位置，将其置信度累加到对应格子。
        随后通过自适应高斯模糊消除离散感，最后归一化至 [0, 1]。

        自适应 sigma 策略（方向一）：
          检测框稀疏时使用更大 sigma 使热点扩散成可见云团；
          密集时减小 sigma 保留空间分辨率。
          - n < 50   → sigma = 5.0（极稀疏，最大扩散）
          - n < 500  → sigma = HEATMAP_BLUR_SIGMA（3.5，典型场景）
          - n ≥ 500  → sigma = max(2.0, HEATMAP_BLUR_SIGMA × 0.6)（密集，保细节）

        核大小防御（方向一风险 3）：
          当格子矩阵很小（小切片或极大 bin_size）时，防止卷积核超过
          图像短边导致 OpenCV 过度平滑。

        Args:
            results: AI 检测结果列表，每项含 "bbox" [x,y,x,y] 和 "confidence"。
            wsi_w:   WSI Level-0 宽度（像素）。
            wsi_h:   WSI Level-0 高度（像素）。

        Returns:
            归一化 float32 格子矩阵，shape (grid_h, grid_w)，值域 [0, 1]。
        """
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

    # ------------------------------------------------------------------
    # 伪彩色映射（方向一：幂函数 Alpha + HOT 调色板）
    # ------------------------------------------------------------------

    def _grid_to_qimage(self, grid_norm: np.ndarray) -> Tuple[QImage, np.ndarray]:
        """将归一化热力网格转换为带 alpha 通道的 QImage，同时返回 rgba 数组。

        转换流程：
          float32 [0,1] → uint8 灰度 → cv2 伪彩色 (BGR, COLORMAP_HOT)
          → RGBA（幂函数 alpha，低值骤降趋近透明） → QImage (RGBA8888) → 深拷贝

        幂函数 Alpha（方向一）：
          alpha = (value ^ GAMMA) × HEATMAP_ALPHA
          GAMMA=2.0 时，value=0.1 → alpha≈1.8（接近透明，消除噪点底色），
          value=1.0 → alpha=180（完全不透明热点）。
          相比线性映射，低值区噪点几乎消失，热点边界对比更锐利。

        深拷贝（qimage.copy()）是必须步骤：QImage 的无拷贝构造函数仅持有
        numpy 数组的裸指针，一旦 numpy 数组被 GC 回收就会产生野指针访问。

        同时返回 rgba 数组供调用方复用（方向三鹰眼图叠层），避免重复伪彩色计算。

        Args:
            grid_norm: 归一化 float32 矩阵，shape (H, W)，值域 [0, 1]。

        Returns:
            (QImage, rgba_ndarray)：
              - QImage：RGBA8888 格式，已深拷贝，与 numpy 缓冲区完全脱离。
              - rgba_ndarray：uint8 RGBA 数组，shape (H, W, 4)，供鹰眼图 resize 复用。
        """
        # 1. float32 → uint8 灰度（clip 防止浮点误差越界）
        gray_u8 = np.clip(grid_norm * 255.0, 0, 255).astype(np.uint8)

        # 2. cv2 伪彩色映射 → BGR uint8，shape (H, W, 3)
        #    HEATMAP_COLORMAP=2 对应 cv2.COLORMAP_JET（蓝→绿→黄→红）
        #    低密度区为蓝/绿，高密度热点为红色，配合幂函数 alpha 后低值透明
        colormap_bgr = cv2.applyColorMap(gray_u8, int(HEATMAP_COLORMAP))

        # 3. BGR → RGBA，shape (H, W, 4)
        rgba = cv2.cvtColor(colormap_bgr, cv2.COLOR_BGR2RGBA)

        # 4. Alpha 通道：幂函数映射，低值骤降趋近 0，高值保持高不透明度
        #    公式：alpha = (value ^ GAMMA) × HEATMAP_ALPHA
        #    相比线性映射消除了低密度区的半透明噪点底色
        gamma = float(HEATMAP_ALPHA_GAMMA)
        alpha_channel = np.clip(
            np.power(grid_norm, gamma) * float(HEATMAP_ALPHA), 0, 255
        ).astype(np.uint8)
        rgba[:, :, 3] = alpha_channel

        # 5. 构建 QImage 并立即深拷贝，脱离 numpy 缓冲区生命周期
        h, w = rgba.shape[:2]
        bytes_per_line = w * 4
        # rgba.data 是一个 memoryview；须确保 rgba 数组在 QImage 构造期间存活，
        # copy() 调用后 rgba 可安全释放。
        qimage = QImage(rgba.data, w, h, bytes_per_line, QImage.Format_RGBA8888)
        # 返回深拷贝 QImage 与 rgba 数组；rgba 数组由调用方（_update_heatmap_layer）
        # 持有，用于方向三鹰眼图叠层的 cv2.resize，此后可安全释放。
        return qimage.copy(), rgba

    # ------------------------------------------------------------------
    # 鹰眼图热力图叠层（方向三）
    # ------------------------------------------------------------------

    def _update_minimap_heatmap(self, rgba: np.ndarray) -> None:
        """将热力图 rgba 数组缩放到鹰眼图尺寸并更新 heatmap_mini_item。

        关键设计：resize 目标为鹰眼图 widget 的**显示像素尺寸**（约 160~250px），
        而非 bg_item.pixmap() 的缩略图原始像素尺寸（可能高达 1500px+）。
        这样 HEATMAP_MINI_BLUR_SIGMA 的单位与视觉像素对齐，sigma=8 就意味着
        热点在屏幕上扩散约 ±8px，不会因缩略图分辨率过高而被稀释成一个小点。

        坐标系修正：
          pixmap 是以 widget 显示尺寸生成的（小图），但 scene 坐标系以缩略图
          原始像素为单位。通过 QTransform.fromScale(sx, sy) 将 item 缩放回
          正确的 scene 尺寸，保证热力叠层与 bg_item 完美对齐。

        防御策略：
          - bg_item pixmap 为空（切片未加载）→ 跳过。
          - minimap.width() / height() 为 0（widget 未完成布局）→ 回退到
            bg_item 像素尺寸（sigma 此时视觉效果不佳，但不崩溃）。
          - rgba 格式异常 → 跳过。

        Args:
            rgba: uint8 RGBA 数组，shape (H, W, 4)，由 _grid_to_qimage 返回。
        """
        if not (
            hasattr(self, "minimap")
            and hasattr(self.minimap, "heatmap_mini_item")
            and hasattr(self.minimap, "bg_item")
        ):
            return

        if rgba is None or rgba.ndim != 3 or rgba.shape[2] != 4:
            return

        # scene 坐标参考：缩略图原始像素尺寸（可能 1000~1500px）
        thumb_size = self.minimap.bg_item.pixmap().size()
        if thumb_size.isEmpty():
            return

        # 显示像素尺寸：widget 实际渲染尺寸（约 160~250px）
        # 若 widget 尚未完成布局（width=0），回退到缩略图尺寸
        vis_w = self.minimap.width()
        vis_h = self.minimap.height()
        if vis_w <= 0 or vis_h <= 0:
            vis_w, vis_h = thumb_size.width(), thumb_size.height()

        # Step 1: 将 rgba grid 缩放到 widget 显示尺寸（小图，约 160~250px）
        # 在此尺寸上 blur，sigma 的单位与视觉像素直接对应
        mini_rgba = cv2.resize(
            rgba,
            (vis_w, vis_h),
            interpolation=cv2.INTER_LINEAR,
        )

        # Step 2: 额外高斯扩散，在显示像素空间施加，使热点视觉上更大更明显
        # RGB 与 Alpha 分开处理以保留色彩饱和度
        extra_sigma = float(HEATMAP_MINI_BLUR_SIGMA)
        if extra_sigma > 0:
            # 核大小：ceil(3σ)×2+1，覆盖 99.7% 高斯能量
            k = int(math.ceil(3.0 * extra_sigma)) * 2 + 1
            k = max(3, k)
            # 防止核超过图像短边
            k = min(k, max(3, min(vis_h, vis_w) // 2 * 2 - 1))
            mini_rgba[:, :, :3] = cv2.GaussianBlur(
                mini_rgba[:, :, :3], (k, k), extra_sigma
            )
            mini_rgba[:, :, 3] = cv2.GaussianBlur(
                mini_rgba[:, :, 3], (k, k), extra_sigma
            )

        # Step 3: 构建 QImage/QPixmap（显示尺寸小图，深拷贝脱离 numpy 缓冲区）
        bytes_per_line = vis_w * 4
        mini_qi = QImage(
            mini_rgba.data, vis_w, vis_h, bytes_per_line, QImage.Format_RGBA8888
        ).copy()

        self.minimap.heatmap_mini_item.setPixmap(QPixmap.fromImage(mini_qi))
        self.minimap.heatmap_mini_item.setPos(0.0, 0.0)

        # Step 4: 用 QTransform 将显示尺寸的 pixmap 缩放回 scene 坐标尺寸，
        # 使热力叠层与 bg_item（缩略图原始像素尺寸）完美对齐
        sx = thumb_size.width() / vis_w
        sy = thumb_size.height() / vis_h
        self.minimap.heatmap_mini_item.setTransform(QTransform.fromScale(sx, sy))
