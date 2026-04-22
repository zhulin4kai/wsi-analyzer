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


class WSIView(QGraphicsView):
    """
    核心视口组件：负责处理鼠标交互（平移、缩放）并按需调度 OpenSlide 渲染
    """

    view_rect_changed = Signal(QRectF)
    interaction_started = Signal()
    interaction_finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # 1. 初始化场景 (Scene)
        self.scene_canvas = QGraphicsScene(self)
        self.setScene(self.scene_canvas)

        # 宏观底图铺垫层
        self.bg_layer_item = QGraphicsPixmapItem()
        self.bg_layer_item.setZValue(-1)
        self.scene_canvas.addItem(self.bg_layer_item)

        # 2. 核心渲染载体：整个 Scene 中只保留一个 PixmapItem 用于显示当前视口图像
        # 这样可以绝对避免频繁创建删除 Item 导致的内存泄漏
        self.viewport_item = QGraphicsPixmapItem()
        self.viewport_item.setZValue(0)
        self.scene_canvas.addItem(self.viewport_item)

        # 3. 视图优化设置
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(
            QPainter.SmoothPixmapTransform
        )  # 开启平滑插值，防止缩放时出现马赛克
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )  # 隐藏滚动条，实现类似谷歌地图的纯净画布
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # 缩放锚点：以鼠标指针当前位置为中心进行缩放
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

        # 4. 后端引擎与状态变量
        self.slide_engine = None
        self._current_qimg = (
            None  # 保持对当前 QImage 的引用，防止被 Python GC 提前回收引发崩溃
        )

        # 交互状态
        self._is_panning = False
        self._last_mouse_pos = None

        # 用于放置在连续滚动滚轮或拖拽时，高频重复发射 interaction_started 信号
        self._is_interaction = False

        # 异步渲染核心
        # 5. 防抖定时器
        # 记录当前请求的版本号
        self.render_version = 0

        # 启动后台渲染线程
        self.render_worker = RenderWorker(self)
        self.render_worker.image_ready.connect(self._on_image_ready)
        self.render_worker.start()

        # 1. 渲染触发定时器 (极速响应)
        # 负责不断去后台取最新高清图，哪怕在拖拽中也可以极速触发
        self.render_timer = QTimer()
        self.render_timer.setSingleShot(True)
        self.render_timer.setInterval(RENDER_DEBOUNCE_MS)  # 降到极低的 50ms
        self.render_timer.timeout.connect(self._request_high_res_render)

        # 2. 绝对静止定时器 (掌控 UI 繁重图层)
        # 只有在完全没有任何交互后，才允许绘制沉重的 AI 画框
        self.idle_timer = QTimer()
        self.idle_timer.setSingleShot(True)
        self.idle_timer.setInterval(
            IDLE_THRESHOLD_MS
        )  # 300ms 不操作，才认为交互真正结束
        self.idle_timer.timeout.connect(self._on_absolute_idle)

    def _mark_interaction(self):
        """统一管理交互状态的入口"""
        # 1. 重置静止定时器
        self.idle_timer.start()

        # 2. 如果当前不在交互状态，进入交互并通知主界面隐藏画框
        if not self._is_interaction:
            self._is_interaction = True
            self.interaction_started.emit()

    def _request_high_res_render(self):
        """
        主线程只负责算坐标
        由定时器触发，计算好所需坐标后给后台线程。
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

        loc_x, loc_y, best_level, size_w, size_h, level_downsample = (
            self.slide_engine.calculate_render_params(
                intersected_rect.left(),
                intersected_rect.top(),
                intersected_rect.width(),
                intersected_rect.height(),
                target_downsample,
            )
        )

        if size_w <= 0 or size_h <= 0:
            finish_interaction_early()
            return

        # 递增版本号，并将沉重的任务丢给后台线程
        # 主线程瞬间执行完毕，继续响应鼠标拖拽。
        self.render_version += 1
        self.render_worker.request_render(
            self.slide_engine,
            loc_x,
            loc_y,
            best_level,
            size_w,
            size_h,
            level_downsample,
            self.render_version,
        )

    def _on_image_ready(self, version, qimg, x, y, scale):
        """
        当后台线程把图处理好送回来时，主线程进行审查。
        """
        # 结果丢弃
        # 如果送回来的版本号低于当前版本号，说明用户在渲染期间又动了鼠标。
        # 这张图已经过期，不进行任何 UI 更新
        if version != self.render_version:
            return

        if self._is_panning:
            return

        # 验证通过，更新 UI 显示
        pixmap = QPixmap.fromImage(qimg)
        self.viewport_item.setPixmap(pixmap)
        self.viewport_item.setPos(x, y)
        self.viewport_item.setScale(scale)

        # 真正的图贴好之后，再结束交互状态，把隐藏的 AI 框重新显示出来
        if self._is_interaction:
            self._is_interaction = False
            self.interaction_finished.emit()

    def closeEvent(self, event):
        """关闭窗口时安全退出线程"""
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

        try:
            thumb_img, downsample_factor = self.slide_engine.get_thumbnail(
                level_from_last=2
            )
            self.bg_layer_item.setPixmap(QPixmap.fromImage(ImageQt(thumb_img)))
            self.bg_layer_item.setScale(downsample_factor)
        except Exception as e:
            logger.error(f"宏观底图加载失败: {e}")

        # 计算初始缩放比例（让整个切片刚好适应当前窗口大小）
        view_rect = self.viewport().rect()
        scale_w = view_rect.width() / w
        scale_h = view_rect.height() / h
        initial_scale = min(scale_w, scale_h) * 0.95  # 留 5% 边距

        self.scale(initial_scale, initial_scale)

        # 触发首次渲染
        self._render_high_res_viewport()

    # ==================== 模块 B: 交互事件重写 ====================
    def wheelEvent(self, event):
        """重写滚轮事件：实现基于鼠标锚点的平滑缩放"""
        if not self.slide_engine:
            return

        # 如果是连续滚动动作的第一下，触发交互开始信号
        self._mark_interaction()

        # 每次滚动的缩放步长
        zoom_factor = 1.15
        if event.angleDelta().y() < 0:
            zoom_factor = 1.0 / zoom_factor

        # 计算未来的缩放比例
        current_scale = self.transform().m11()
        new_scale = current_scale * zoom_factor

        # 限制缩放范围：最大放大到 Level 0 (1.0)，最小缩小到刚好塞满屏幕
        if new_scale > 1.0:
            zoom_factor = 1.0 / current_scale

        # 执行缩放 (由于设置了 AnchorUnderMouse，Qt 会自动处理偏移数学计算)
        self.scale(zoom_factor, zoom_factor)

        # 重置防抖定时器
        self.render_timer.start()
        self.view_rect_changed.emit(self.get_visible_rect())

    def mousePressEvent(self, event):
        """重写鼠标按下：开启平移"""
        if event.button() == Qt.LeftButton and self.slide_engine:
            # 鼠标按下的瞬间，进入交互状态
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

            # 通过操作隐藏的滚动条来实现画布平移
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
        核心渲染逻辑：坐标映射 -> 计算层级 -> 截取图像 -> 对齐显示
        """

        # 防止函数提前return， 提取一个重置方法
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
        # 将屏幕矩形映射到 Scene 坐标系（即 Level 0 绝对坐标系）中，获取可见的物理区域
        visible_scene_rect = self.mapToScene(viewport_rect).boundingRect()

        # 与 Scene 的物理边界取交集，防止读取超出 WSI 范围的无效数据
        intersected_rect = visible_scene_rect.intersected(self.scene_canvas.sceneRect())
        if intersected_rect.isEmpty():
            finish_interaction()
            return

        # 2. 动态层级 (Level) 计算
        # 当前视图的缩放比例（例如 0.1 表示缩小了 10 倍显示）
        current_scale = self.transform().m11()
        # 目标降采样率 (Downsample) = 1 / 缩放比例。缩小 10 倍，意味着我们需要 downsample 约为 10 的层级
        target_downsample = 1.0 / current_scale

        loc_x, loc_y, best_level, size_w, size_h, level_downsample = (
            self.slide_engine.calculate_render_params(
                intersected_rect.left(),
                intersected_rect.top(),
                intersected_rect.width(),
                intersected_rect.height(),
                target_downsample,
            )
        )

        if size_w <= 0 or size_h <= 0:
            finish_interaction()
            return

        self.render_version += 1
        self.render_worker.request_render(
            self.slide_engine,
            loc_x,
            loc_y,
            best_level,
            size_w,
            size_h,
            level_downsample,
            self.render_version,
        )

    # ==================== 模块 D: 鹰眼图 ====================
    def get_visible_rect(self):
        """获取当前主视图处于 Level 0 坐标系下的可见矩形区域"""
        return self.mapToScene(self.viewport().rect()).boundingRect()

    def _trigger_view_update(self):
        """在缩放和滚动后调用此方法发射信号"""
        self.view_rect_changed.emit(self.get_visible_rect())
