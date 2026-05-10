from PIL.ImageQt import ImageQt
from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QMessageBox,
)

from wsi_analyzer.config.config import IDLE_THRESHOLD_MS, RENDER_DEBOUNCE_MS
from wsi_analyzer.app.dependency_container import container
from wsi_analyzer.domain.slide import SlideMetadata
from wsi_analyzer.ui.rendering import TileLRUCache, TileRenderController
from wsi_analyzer.infrastructure.logging import logger
from wsi_analyzer.workers import RenderWorker

from .interaction_controller import InteractionController


class WSIView(QGraphicsView):
    """
    视口组件：处理鼠标交互（平移、缩放）并调度瓦片渲染。

    不直接持有 OpenSlideEngine。通过 ImageServer 获取元数据、像素数据
    及缩略图；引擎生命周期由 ImageServer.SlidePool 统一管理。
    """

    view_rect_changed = Signal(QRectF)
    interaction_started = Signal()
    interaction_finished = Signal()
    roi_drawn = Signal(tuple)

    zoom_changed = Signal(float)
    mouse_scene_pos_changed = Signal(float, float)
    wsi_loaded = Signal(object)  # SlideMetadata

    def __init__(self, parent=None):
        super().__init__(parent)

        self.scene_canvas = QGraphicsScene(self)
        self.setScene(self.scene_canvas)

        self.bg_layer_item = QGraphicsPixmapItem()
        self.bg_layer_item.setZValue(-1)
        self.scene_canvas.addItem(self.bg_layer_item)

        # 无切片时的占位提示文字（使用系统默认字体，跨平台兼容）
        font = QFont()
        font.setPointSize(13)
        self._placeholder = QGraphicsSimpleTextItem(
            "拖拽 .svs / .tif / .ndpi 切片到此处，或通过 文件 → 打开 加载"
        )
        self._placeholder.setFont(font)
        self._placeholder.setBrush(QBrush(QColor(140, 140, 140)))
        self._placeholder.setZValue(10000)
        self.scene_canvas.addItem(self._placeholder)

        # 拖拽悬停时的半透明灰色遮罩
        self._drop_overlay = QGraphicsRectItem()
        self._drop_overlay.setBrush(QBrush(QColor(80, 80, 80, 60)))
        self._drop_overlay.setPen(QPen(Qt.PenStyle.NoPen))
        self._drop_overlay.setZValue(9999)
        self._drop_overlay.setVisible(False)
        self.scene_canvas.addItem(self._drop_overlay)

        self.setAcceptDrops(True)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

        # Current slide state — replaces direct slide_engine ownership
        self._current_path: str | None = None
        self._metadata: SlideMetadata | None = None
        self._current_qimg = None  # Retain QImage ref to prevent GC during render

        # Interaction controller — handles pan/zoom/ROI/drag-drop
        self._interaction = InteractionController(
            view=self, scene=self.scene_canvas, idle_threshold_ms=IDLE_THRESHOLD_MS
        )
        self._interaction.interaction_started.connect(self.interaction_started)
        self._interaction.interaction_finished.connect(self.interaction_finished)
        self._interaction.roi_drawn.connect(self.roi_drawn)
        self._interaction.viewport_changed.connect(self._on_viewport_changed)

        # Tile render controller — owns version, cache, worker, dispatch logic
        self.tile_controller = TileRenderController(
            render_worker=RenderWorker(self),
            tile_cache=TileLRUCache(max_capacity=1024),
            scene_canvas=self.scene_canvas,
        )
        self.tile_controller.render_worker.image_ready.connect(
            self._on_image_ready
        )
        self.tile_controller.render_worker.start()

        # Debounce high-res render after interaction ends
        self.render_timer = QTimer()
        self.render_timer.setSingleShot(True)
        self.render_timer.setInterval(RENDER_DEBOUNCE_MS)
        self.render_timer.timeout.connect(self._request_high_res_render)

    # ── 公开只读属性 ──────────────────────────────────────────────────

    @property
    def current_metadata(self):
        return self._metadata

    @property
    def current_path(self):
        return self._current_path

    def set_tile_cache_capacity(self, capacity: int):
        self.tile_controller.set_cache_capacity(capacity)

    # ── 渲染入口 ──────────────────────────────────────────────────────

    def _request_high_res_render(self):
        if not self._current_path or not self._metadata:
            self._interaction.mark_idle()
            return

        viewport_rect = self.viewport().rect()
        visible_scene_rect = self.mapToScene(viewport_rect).boundingRect()

        self.tile_controller.request_tiles(
            visible_scene_rect=visible_scene_rect,
            scene_rect=self.scene_canvas.sceneRect(),
            current_scale=self.transform().m11(),
        )

        self._interaction.mark_idle()

    def _on_image_ready(self, path, version, level, col, row, qimg, x, y, scale):
        if self.tile_controller.on_image_ready(
            path, version, level, col, row, qimg, x, y, scale
        ):
            self._interaction.mark_idle()

    def closeEvent(self, event):
        if hasattr(self, "tile_controller"):
            self.tile_controller.render_worker.shutdown()
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_placeholder_visibility()

    def load_wsi(self, file_path):
        self._prepare_for_slide_switch()

        metadata = self._load_slide_metadata(file_path)
        if metadata is None:
            return

        self._setup_scene_for_metadata(metadata)
        self._clear_tile_items()
        self._load_background_thumbnail(file_path)
        self._fit_slide_to_view(metadata)
        self._activate_slide(file_path, metadata)

    def _prepare_for_slide_switch(self):
        self.render_timer.stop()
        self.tile_controller.invalidate()
        self._current_path = None
        self._metadata = None
        self._update_placeholder_visibility()

    def _load_slide_metadata(self, file_path):
        try:
            return container.image_server.get_metadata(file_path)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法打开文件:\n{e}")
            return None

    def _setup_scene_for_metadata(self, metadata):
        assert metadata is not None
        w, h = metadata.level_0_dim
        self.scene_canvas.setSceneRect(0, 0, w, h)
        self.resetTransform()

    def _clear_tile_items(self):
        self.tile_controller.clear_tile_items()

    def _load_background_thumbnail(self, file_path):
        try:
            thumb_img, downsample_factor = container.image_server.get_thumbnail(
                file_path, level_from_last=2
            )
            self.bg_layer_item.setPixmap(QPixmap.fromImage(ImageQt(thumb_img)))
            self.bg_layer_item.setScale(downsample_factor)
        except Exception as e:
            logger.error(f"宏观底图加载失败: {e}")

    def _fit_slide_to_view(self, metadata):
        assert metadata is not None
        w, h = metadata.level_0_dim
        view_rect = self.viewport().rect()
        scale_w = view_rect.width() / w
        scale_h = view_rect.height() / h
        initial_scale = min(scale_w, scale_h) * 0.95
        self.scale(initial_scale, initial_scale)

    def _activate_slide(self, file_path, metadata):
        self._current_path = file_path
        self._metadata = metadata
        self.tile_controller.activate(file_path, metadata)
        self._update_placeholder_visibility()

        self.zoom_changed.emit(self.transform().m11())
        self.request_render_now()
        self.wsi_loaded.emit(metadata)

    def _on_viewport_changed(self):
        """桥接 InteractionController.viewport_changed → render_timer + view_rect_changed"""
        self.render_timer.start()
        self.view_rect_changed.emit(self.get_visible_rect())

    def wheelEvent(self, event):
        factor = self._interaction.handle_wheel(event, bool(self._current_path))
        if factor is not None:
            self.scale(factor, factor)
            self.zoom_changed.emit(self.transform().m11())

    def toggle_roi_mode(self, enabled: bool):
        self._interaction.toggle_roi_mode(enabled)

    def clear_roi_box(self):
        self._interaction.clear_roi_box()

    def mousePressEvent(self, event):
        if self._interaction.handle_mouse_press(event, bool(self._current_path)):
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        self._interaction.handle_mouse_move(event)

        if self._current_path:
            scene_pos = self.mapToScene(event.position().toPoint())
            self.mouse_scene_pos_changed.emit(scene_pos.x(), scene_pos.y())

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._interaction.handle_mouse_release(event)
        super().mouseReleaseEvent(event)

    def _render_high_res_viewport(self):
        def finish_interaction():
            self._interaction.mark_idle()

        if not self._current_path or not self._metadata:
            finish_interaction()
            return

        viewport_rect = self.viewport().rect()
        visible_scene_rect = self.mapToScene(viewport_rect).boundingRect()
        intersected_rect = visible_scene_rect.intersected(self.scene_canvas.sceneRect())
        if intersected_rect.isEmpty():
            finish_interaction()
            return

        self._request_high_res_render()

    def set_scale(self, target_scale: float):
        """Set absolute zoom scale (m11 value), anchored to viewport centre."""
        if not self._current_path:
            return
        current = self.transform().m11()
        if current <= 0:
            return
        clamped = max(1e-4, min(float(target_scale), 1.0))
        factor = clamped / current
        if abs(factor - 1.0) < 1e-9:
            return
        old_anchor = self.transformationAnchor()
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.scale(factor, factor)
        self.setTransformationAnchor(old_anchor)
        self.zoom_changed.emit(self.transform().m11())
        self.render_timer.start()
        self.view_rect_changed.emit(self.get_visible_rect())

    def get_visible_rect(self):
        return self.mapToScene(self.viewport().rect()).boundingRect()

    def _trigger_view_update(self):
        self.view_rect_changed.emit(self.get_visible_rect())

    # ── 公开导航 API ──────────────────────────────────────────────────

    def request_render_now(self):
        self._render_high_res_viewport()

    def emit_view_rect_changed(self):
        self.view_rect_changed.emit(self.get_visible_rect())

    def navigate_to(self, cx: float, cy: float, render: bool = True):
        if not self._current_path:
            return
        self.centerOn(cx, cy)
        if render:
            self.request_render_now()
        self.emit_view_rect_changed()

    def focus_on(self, cx: float, cy: float, target_scale: float = 1.0):
        if not self._current_path:
            return
        self.centerOn(cx, cy)
        self.set_scale(target_scale)
        self.request_render_now()
        self.emit_view_rect_changed()

    # ── zoom/public ────────────────────────────────────────────────────

    def zoom_in(self):
        if not self._current_path:
            return
        self.set_scale(min(self.transform().m11() * 1.25, 1.0))

    def zoom_out(self):
        if not self._current_path:
            return
        self.set_scale(max(self.transform().m11() * 0.8, 1e-4))

    def reset_to_fit(self):
        if not self._current_path or not self._metadata:
            return
        w, h = self._metadata.level_0_dim
        self.resetTransform()
        view_rect = self.viewport().rect()
        scale_w = view_rect.width() / w
        scale_h = view_rect.height() / h
        initial_scale = min(scale_w, scale_h) * 0.95
        self.scale(initial_scale, initial_scale)
        self.zoom_changed.emit(self.transform().m11())
        self.render_timer.start()
        self.view_rect_changed.emit(self.get_visible_rect())

    # ── Drag and Drop ──────────────────────────────────────────────────────
    #
    # QGraphicsView 内部会在 event() 层拦截 DragEnter/DragMove/Drop 事件
    # 并分发给 QGraphicsScene，不论 acceptDrops 是否为 True，导致事件无法冒泡到
    # 父窗口 MainWindow。因此必须在 WSIView 层显式覆盖四个拖拽事件，转发给 parent
    # 以触发 MainWindow 的遮罩渲染与文件打开逻辑。

    def dragEnterEvent(self, event: QDragEnterEvent):
        self._interaction.handle_drag_enter(event)

    def dragMoveEvent(self, event: QDragMoveEvent):
        self._interaction.handle_drag_move(event)

    def dragLeaveEvent(self, event):
        self._interaction.handle_drag_leave(event)

    def dropEvent(self, event: QDropEvent):
        self._interaction.handle_drop(event)

    def set_drag_overlay(self, visible: bool):
        """显示/隐藏拖拽悬停遮罩并调整占位文字样式。"""
        self._drop_overlay.setVisible(visible)
        if visible:
            self._placeholder.setBrush(QBrush(QColor(180, 180, 180)))
            # 遮罩覆盖整个 viewport
            vr = self.viewport().rect()
            tl = self.mapToScene(vr.topLeft())
            br = self.mapToScene(vr.bottomRight())
            self._drop_overlay.setRect(QRectF(tl, br))
        else:
            self._placeholder.setBrush(QBrush(QColor(140, 140, 140)))

    def _update_placeholder_visibility(self):
        """根据当前切片状态控制占位文字显示。"""
        self._placeholder.setVisible(self._current_path is None)
        if not self._current_path:
            vr = self.viewport().rect()
            tr = self.mapToScene(vr).boundingRect()
            self._placeholder.setPos(
                tr.center().x() - self._placeholder.boundingRect().width() / 2,
                tr.center().y(),
            )
