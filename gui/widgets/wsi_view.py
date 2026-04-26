from PIL.ImageQt import ImageQt
from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QMessageBox,
)

from config import IDLE_THRESHOLD_MS, RENDER_DEBOUNCE_MS
from core import WSIDataEngine
from utils.logger import logger
from workers import RenderWorker

from .tile_cache import TileLRUCache

TILE_SIZE = 512


class WSIView(QGraphicsView):
    """
    视口组件：负责处理鼠标交互（平移、缩放）并调度渲染
    """

    view_rect_changed = Signal(QRectF)
    interaction_started = Signal()
    interaction_finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # 1. 初始化场景 (Scene)
        self.scene_canvas = QGraphicsScene(self)
        self.setScene(self.scene_canvas)

        # 底图铺垫层
        self.bg_layer_item = QGraphicsPixmapItem()
        self.bg_layer_item.setZValue(-1)
        self.scene_canvas.addItem(self.bg_layer_item)

        # 2. 渲染载体：瓦片缓存池
        self.tile_cache = TileLRUCache(max_capacity=500)

        # 3. 视图设置
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)  # 开启平滑插值
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # 隐藏滚动条
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # 缩放锚点：以鼠标指针当前位置为中心进行缩放
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

        # 4. 后端引擎与状态变量
        self.slide_engine = None
        self._current_qimg = None  # 保持对当前 QImage 的引用，避免垃圾回收导致异常

        # 交互状态
        self._is_panning = False
        self._last_mouse_pos = None

        # 用于避免连续滚动或拖拽时高频重复发射 interaction_started 信号
        self._is_interaction = False

        # 异步渲染管理
        # 5. 渲染防抖定时器
        # 记录当前请求的版本号
        self.render_version = 0

        # 启动后台渲染线程
        self.render_worker = RenderWorker(self)
        self.render_worker.image_ready.connect(self._on_image_ready)
        self.render_worker.start()

        # 1. 渲染触发定时器
        # 用于定时触发高清图渲染请求
        self.render_timer = QTimer()
        self.render_timer.setSingleShot(True)
        self.render_timer.setInterval(RENDER_DEBOUNCE_MS)  # 50ms 间隔
        self.render_timer.timeout.connect(self._request_high_res_render)

        # 2. 静止状态定时器
        # 在交互完全结束后，允许绘制额外的 UI 图层
        self.idle_timer = QTimer()
        self.idle_timer.setSingleShot(True)
        self.idle_timer.setInterval(IDLE_THRESHOLD_MS)  # 交互结束阈值
        self.idle_timer.timeout.connect(self._on_absolute_idle)

    def _mark_interaction(self):
        """管理交互状态"""
        # 1. 重置静止定时器
        self.idle_timer.start()

        # 2. 如果当前不在交互状态，进入交互并通知主界面
        if not self._is_interaction:
            self._is_interaction = True
            self.interaction_started.emit()

    def _request_high_res_render(self):
        """
        由定时器触发，计算坐标并提交渲染任务。
        """

        def finish_interaction_early():
            if self._is_interaction:
                self._is_interaction = False
                self.interaction_finished.emit()

        if not self.slide_engine:
            finish_interaction_early()
            return

        viewport_rect = self.viewport().rect()
        visible_scene_rect = self.mapToScene(viewport_rect).boundingRect()
        intersected_rect = visible_scene_rect.intersected(self.scene_canvas.sceneRect())

        if intersected_rect.isEmpty():
            finish_interaction_early()
            return

        current_scale = self.transform().m11()
        target_downsample = 1.0 / current_scale

        # 获取最适合的层级
        best_level = self.slide_engine.slide.get_best_level_for_downsample(
            target_downsample
        )
        level_downsample = self.slide_engine.slide.level_downsamples[best_level]
        level_dim = self.slide_engine.slide.level_dimensions[best_level]

        # 仅隐藏比当前需要的层级【分辨率更高】（即 level 值更小）的瓦片
        # 保留比它【分辨率更低】（level 值更大）的瓦片作为缓冲背景，避免闪烁和马赛克
        for key, item in self.tile_cache._cache.items():
            cached_level = key[0]
            if cached_level < best_level:
                item.setVisible(False)
            else:
                item.setVisible(True)

        # 递增版本号，表示发起了一次新的渲染批次
        self.render_version += 1

        # 计算视口覆盖的瓦片网格范围（增加边缘缓冲）
        start_col = int((intersected_rect.left() / level_downsample) // TILE_SIZE) - 1
        end_col = int((intersected_rect.right() / level_downsample) // TILE_SIZE) + 1
        start_row = int((intersected_rect.top() / level_downsample) // TILE_SIZE) - 1
        end_row = int((intersected_rect.bottom() / level_downsample) // TILE_SIZE) + 1

        # 限制在实际层级的有效范围内
        max_col = (level_dim[0] - 1) // TILE_SIZE
        max_row = (level_dim[1] - 1) // TILE_SIZE

        start_col = max(0, min(start_col, max_col))
        end_col = max(0, min(end_col, max_col))
        start_row = max(0, min(start_row, max_row))
        end_row = max(0, min(end_row, max_row))

        for row in range(start_row, end_row + 1):
            for col in range(start_col, end_col + 1):
                key = (best_level, col, row)

                # 检查缓存是否命中
                cached_item = self.tile_cache.get(key)
                if cached_item:
                    # 缓存命中，确保图块可见
                    if not cached_item.scene():
                        self.scene_canvas.addItem(cached_item)
                    cached_item.setVisible(True)
                else:
                    # 缓存未命中，需要派发任务给后台读取
                    tile_w = TILE_SIZE
                    tile_h = TILE_SIZE

                    # 处理边缘瓦片
                    if col == max_col:
                        tile_w = level_dim[0] - col * TILE_SIZE
                    if row == max_row:
                        tile_h = level_dim[1] - row * TILE_SIZE

                    # 计算在 Level 0 (Scene 绝对坐标系) 中的真实位置
                    abs_x = col * TILE_SIZE * level_downsample
                    abs_y = row * TILE_SIZE * level_downsample

                    self.render_worker.request_render(
                        self.slide_engine,
                        best_level,
                        col,
                        row,
                        int(abs_x),
                        int(abs_y),
                        int(tile_w),
                        int(tile_h),
                        level_downsample,
                        self.render_version,
                    )

        # 我们只需结束交互。
        finish_interaction_early()

    def _on_image_ready(self, version, level, col, row, qimg, x, y, scale):
        """
        接收后台线程返回的瓦片数据。
        """
        # 检查任务版本，丢弃过期任务
        if version < self.render_version:
            return

        key = (level, col, row)

        # 检查缓存是否存在重复图块
        if self.tile_cache.contains(key):
            return

        # 创建 QGraphicsPixmapItem 载体
        pixmap = QPixmap.fromImage(qimg)
        item = QGraphicsPixmapItem(pixmap)
        item.setPos(x, y)
        item.setScale(scale)

        # 严格按金字塔层级分布 Z-index，高分辨率永远覆盖低分辨率
        max_levels = len(self.slide_engine.slide.level_dimensions)
        z_value = max_levels - level
        item.setZValue(z_value)

        # 添加到 Scene
        self.scene_canvas.addItem(item)

        # 存入 LRU 缓存，并获取可能被淘汰的最老瓦片
        evicted_item = self.tile_cache.put(key, item)
        if evicted_item and evicted_item.scene():
            self.scene_canvas.removeItem(evicted_item)

        # 检查交互状态并展示瓦片
        if self._is_interaction:
            self._is_interaction = False
            self.interaction_finished.emit()

    def closeEvent(self, event):
        """关闭窗口时退出线程"""
        if hasattr(self, "render_worker"):
            self.render_worker.stop()
        super().closeEvent(event)

    def load_wsi(self, file_path):
        """加载 SVS 文件并初始化绝对坐标系"""
        try:
            self.slide_engine = WSIDataEngine(file_path)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法打开文件:\n{e}")
            return

        # 获取 Level 0 的绝对物理尺寸
        w, h = self.slide_engine.level_0_dim
        self.scene_canvas.setSceneRect(0, 0, w, h)
        self.resetTransform()

        # 清空旧的瓦片缓存
        old_items = self.tile_cache.clear()
        for item in old_items:
            if item.scene():
                self.scene_canvas.removeItem(item)

        try:
            thumb_img, downsample_factor = self.slide_engine.get_thumbnail(
                level_from_last=2
            )
            self.bg_layer_item.setPixmap(QPixmap.fromImage(ImageQt(thumb_img)))
            self.bg_layer_item.setScale(downsample_factor)
        except Exception as e:
            logger.error(f"宏观底图加载失败: {e}")

        # 计算初始缩放比例
        view_rect = self.viewport().rect()
        scale_w = view_rect.width() / w
        scale_h = view_rect.height() / h
        initial_scale = min(scale_w, scale_h) * 0.95  # 预留边距

        self.scale(initial_scale, initial_scale)

        # 请求首次渲染
        self._render_high_res_viewport()

    # ==================== 模块 B: 交互事件重写 ====================
    def wheelEvent(self, event):
        """重写滚轮事件：实现基于鼠标锚点的平滑缩放"""
        if not self.slide_engine:
            return

        # 触发交互开始信号
        self._mark_interaction()

        # 每次滚动的缩放步长
        zoom_factor = 1.15
        if event.angleDelta().y() < 0:
            zoom_factor = 1.0 / zoom_factor

        # 计算未来的缩放比例
        current_scale = self.transform().m11()
        new_scale = current_scale * zoom_factor

        # 限制缩放范围
        if new_scale > 1.0:
            zoom_factor = 1.0 / current_scale

        # 执行缩放
        self.scale(zoom_factor, zoom_factor)

        # 重置防抖定时器
        self.render_timer.start()
        self.view_rect_changed.emit(self.get_visible_rect())

    def mousePressEvent(self, event):
        """重写鼠标按下：开启平移"""
        if event.button() == Qt.LeftButton and self.slide_engine:
            # 记录鼠标按下的交互状态
            self._mark_interaction()
            self._is_panning = True
            self._last_mouse_pos = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """重写鼠标移动：计算偏移量并调整滚动条实现平移"""
        if self._is_panning:
            self._mark_interaction()

            current_pos = event.position().toPoint()
            delta = current_pos - self._last_mouse_pos
            self._last_mouse_pos = current_pos

            # 通过滚动条实现画布平移
            h_bar = self.horizontalScrollBar()
            v_bar = self.verticalScrollBar()
            h_bar.setValue(h_bar.value() - delta.x())
            v_bar.setValue(v_bar.value() - delta.y())

            # 平移时重置防抖定时器
            self.render_timer.start()
            self.view_rect_changed.emit(self.get_visible_rect())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """重写鼠标释放：结束平移"""
        if event.button() == Qt.LeftButton:
            self._is_panning = False
            self.setCursor(Qt.ArrowCursor)
            self.idle_timer.start()
            self.render_timer.start()
        super().mouseReleaseEvent(event)

    def _on_absolute_idle(self):
        if self._is_interaction:
            self._is_interaction = False
            self.interaction_finished.emit()

    # ==================== 模块 C: 视口按需渲染核心逻辑 ====================
    def _render_high_res_viewport(self):
        """
        坐标映射与层级计算
        """

        # 提取重置方法
        def finish_interaction():
            if self._is_interaction:
                self._is_interaction = False
                self.interaction_finished.emit()

        if not self.slide_engine:
            finish_interaction()
            return

        # 1. 视图 -> Scene 坐标映射
        # 获取当前 Viewport 在屏幕上的矩形
        viewport_rect = self.viewport().rect()
        # 将屏幕矩形映射到 Scene 坐标系，获取可见区域
        visible_scene_rect = self.mapToScene(viewport_rect).boundingRect()

        # 与 Scene 边界取交集，限制有效读取范围
        intersected_rect = visible_scene_rect.intersected(self.scene_canvas.sceneRect())
        if intersected_rect.isEmpty():
            finish_interaction()
            return

        # 2. 动态层级 (Level) 计算
        # 获取当前视图缩放比例
        current_scale = self.transform().m11()
        # 计算目标降采样率
        target_downsample = 1.0 / current_scale

        # 复用渲染请求逻辑
        self._request_high_res_render()

    # ==================== 模块 D: 鹰眼图 ====================
    def get_visible_rect(self):
        """获取当前主视图处于 Level 0 坐标系下的可见矩形区域"""
        return self.mapToScene(self.viewport().rect()).boundingRect()

    def _trigger_view_update(self):
        """在缩放和滚动后调用此方法发射信号"""
        self.view_rect_changed.emit(self.get_visible_rect())
