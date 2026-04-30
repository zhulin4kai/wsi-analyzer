import math

from PIL.ImageQt import ImageQt
from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QDragEnterEvent, QDragMoveEvent, QDropEvent, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QMessageBox,
)

from config import IDLE_THRESHOLD_MS, RENDER_DEBOUNCE_MS
from core import ImageServer, SlideMetadata
from core import TileLRUCache
from utils import logger
from workers import RenderWorker

from .roi_box_item import ROIBoxItem

TILE_SIZE = 512


class WSIView(QGraphicsView):
    """
    视口组件：处理鼠标交互（平移、缩放）并调度瓦片渲染。

    不直接持有 WSIDataEngine。通过 ImageServer 获取元数据、像素数据
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

        # 无切片时的占位提示文字
        self._placeholder = QGraphicsSimpleTextItem(
            "拖拽 .svs / .tif / .ndpi 切片到此处，或通过左侧 添加图像 加载"
        )
        self._placeholder.setFont(QFont("Microsoft YaHei", 13))
        self._placeholder.setBrush(QBrush(QColor(140, 140, 140)))
        self._placeholder.setZValue(10000)
        self.scene_canvas.addItem(self._placeholder)

        # 拖拽悬停时的半透明灰色遮罩
        self._drop_overlay = QGraphicsRectItem()
        self._drop_overlay.setBrush(QBrush(QColor(80, 80, 80, 60)))
        self._drop_overlay.setPen(QPen(Qt.NoPen))
        self._drop_overlay.setZValue(9999)
        self._drop_overlay.setVisible(False)
        self.scene_canvas.addItem(self._drop_overlay)

        # 场景项 LRU 缓存；每次切换切片时清空
        self.tile_cache = TileLRUCache(max_capacity=1024)

        self.setAcceptDrops(True)
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

        # Current slide state — replaces direct slide_engine ownership
        self._current_path: str | None = None
        self._metadata: SlideMetadata | None = None
        self._current_qimg = None  # Retain QImage ref to prevent GC during render

        # Interaction state
        self._is_panning = False
        self._last_mouse_pos = None
        self._is_interaction = False

        # ROI state
        self._is_roi_mode = False
        self._roi_start_pos = None
        self._current_roi_item = None

        self.render_version = 0

        self.render_worker = RenderWorker(self)
        self.render_worker.image_ready.connect(self._on_image_ready)
        self.render_worker.start()

        # Debounce high-res render after interaction ends
        self.render_timer = QTimer()
        self.render_timer.setSingleShot(True)
        self.render_timer.setInterval(RENDER_DEBOUNCE_MS)
        self.render_timer.timeout.connect(self._request_high_res_render)

        # Detect absolute idle to finalize interaction state
        self.idle_timer = QTimer()
        self.idle_timer.setSingleShot(True)
        self.idle_timer.setInterval(IDLE_THRESHOLD_MS)
        self.idle_timer.timeout.connect(self._on_absolute_idle)

    def _mark_interaction(self):
        self.idle_timer.start()
        if not self._is_interaction:
            self._is_interaction = True
            self.interaction_started.emit()

    def _request_high_res_render(self):
        """Compute visible tile grid and route each tile through three cache levels."""

        def finish_interaction_early():
            if self._is_interaction:
                self._is_interaction = False
                self.interaction_finished.emit()

        if not self._current_path or not self._metadata:
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

        best_level = self._metadata.get_best_level_for_downsample(target_downsample)
        level_downsample = self._metadata.level_downsamples[best_level]
        level_dim = self._metadata.level_dimensions[best_level]

        # 隐藏高分辨率已缓存瓦片，避免切换层级时的 z-fighting 渲染冲突
        for key, item in self.tile_cache._cache.items():
            cached_level = key[0]
            item.setVisible(cached_level >= best_level)

        self.render_version += 1

        start_col = int((intersected_rect.left() / level_downsample) // TILE_SIZE) - 1
        end_col = int((intersected_rect.right() / level_downsample) // TILE_SIZE) + 1
        start_row = int((intersected_rect.top() / level_downsample) // TILE_SIZE) - 1
        end_row = int((intersected_rect.bottom() / level_downsample) // TILE_SIZE) + 1

        max_col = (level_dim[0] - 1) // TILE_SIZE
        max_row = (level_dim[1] - 1) // TILE_SIZE

        start_col = max(0, min(start_col, max_col))
        end_col = max(0, min(end_col, max_col))
        start_row = max(0, min(start_row, max_row))
        end_row = max(0, min(end_row, max_row))

        for row in range(start_row, end_row + 1):
            for col in range(start_col, end_col + 1):
                key = (best_level, col, row)

                # Level 1：场景项 LRU 缓存（无 I/O）
                cached_item = self.tile_cache.get(key)
                if cached_item:
                    if not cached_item.scene():
                        self.scene_canvas.addItem(cached_item)
                    cached_item.setVisible(True)
                    continue

                abs_x = col * TILE_SIZE * level_downsample
                abs_y = row * TILE_SIZE * level_downsample
                tile_w = level_dim[0] - col * TILE_SIZE if col == max_col else TILE_SIZE
                tile_h = level_dim[1] - row * TILE_SIZE if row == max_row else TILE_SIZE

                # Level 2：跨切片像素数据缓存（无 I/O，重访时命中可跳过磁盘读取）
                cached_qimg = ImageServer.instance().get_tile(
                    self._current_path, best_level, col, row
                )
                if cached_qimg is not None:
                    self._add_tile_to_scene(
                        cached_qimg,
                        best_level,
                        col,
                        row,
                        int(abs_x),
                        int(abs_y),
                        level_downsample,
                    )
                    continue

                # Level 3：派发后台 I/O 任务
                # 优先级：中心瓦片优先渲染（数值越小优先级越高）
                viewport_center = visible_scene_rect.center()
                tile_center_x = abs_x + tile_w * level_downsample * 0.5
                tile_center_y = abs_y + tile_h * level_downsample * 0.5
                dist = math.hypot(
                    tile_center_x - viewport_center.x(),
                    tile_center_y - viewport_center.y(),
                )
                priority_score = dist / max(level_downsample, 1e-6)

                self.render_worker.request_render(
                    self._current_path,
                    best_level,
                    col,
                    row,
                    int(abs_x),
                    int(abs_y),
                    int(tile_w),
                    int(tile_h),
                    level_downsample,
                    self.render_version,
                    priority=priority_score,
                )

        finish_interaction_early()

    def _add_tile_to_scene(self, qimg, level, col, row, x, y, scale):
        """Convert QImage → QGraphicsPixmapItem and insert into scene + scene-item cache."""
        key = (level, col, row)
        if self.tile_cache.contains(key):
            return
        pixmap = QPixmap.fromImage(qimg)
        item = QGraphicsPixmapItem(pixmap)
        item.setPos(x, y)
        item.setScale(scale)
        # Higher resolution (lower level index) renders on top
        item.setZValue(self._metadata.level_count - level)
        self.scene_canvas.addItem(item)
        evicted = self.tile_cache.put(key, item)
        if evicted and evicted.scene():
            self.scene_canvas.removeItem(evicted)

    def _on_image_ready(self, path, version, level, col, row, qimg, x, y, scale):
        # Discard results from a previous slide or a superseded render batch
        if path != self._current_path:
            return
        if version < self.render_version:
            return
        key = (level, col, row)
        if self.tile_cache.contains(key):
            return
        self._add_tile_to_scene(qimg, level, col, row, x, y, scale)
        if self._is_interaction:
            self._is_interaction = False
            self.interaction_finished.emit()

    def closeEvent(self, event):
        if hasattr(self, "render_worker"):
            self.render_worker.shutdown()
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_placeholder_visibility()

    def load_wsi(self, file_path):
        """Switch to a new slide. Engine lifecycle is fully delegated to ImageServer.SlidePool."""
        # Stop pending tasks; a large version jump marks in-flight tasks as stale
        self.render_timer.stop()
        self.render_version += 1000
        self.render_worker.set_version(self.render_version)  # sync scheduler version
        self.render_worker.stop()  # clear queued tasks

        # Nullify state so any late _on_image_ready calls are silently discarded
        self._current_path = None
        self._metadata = None
        self._update_placeholder_visibility()

        try:
            metadata = ImageServer.instance().get_metadata(file_path)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法打开文件:\n{e}")
            return

        w, h = metadata.level_0_dim
        self.scene_canvas.setSceneRect(0, 0, w, h)
        self.resetTransform()

        # 清空场景项；跨切片的 TileDataCache 刻意保留，重访时可跳过磁盘 I/O
        old_items = self.tile_cache.clear()
        for item in old_items:
            if item.scene():
                self.scene_canvas.removeItem(item)

        try:
            thumb_img, downsample_factor = ImageServer.instance().get_thumbnail(
                file_path, level_from_last=2
            )
            self.bg_layer_item.setPixmap(QPixmap.fromImage(ImageQt(thumb_img)))
            self.bg_layer_item.setScale(downsample_factor)
        except Exception as e:
            logger.error(f"宏观底图加载失败: {e}")

        view_rect = self.viewport().rect()
        scale_w = view_rect.width() / w
        scale_h = view_rect.height() / h
        initial_scale = min(scale_w, scale_h) * 0.95
        self.scale(initial_scale, initial_scale)

        # 所有准备工作完成后才激活新的切片状态
        self._current_path = file_path
        self._metadata = metadata
        self._update_placeholder_visibility()

        self.zoom_changed.emit(self.transform().m11())
        self._render_high_res_viewport()
        self.wsi_loaded.emit(metadata)

    def wheelEvent(self, event):
        if not self._current_path:
            return
        self._mark_interaction()

        zoom_factor = 1.15
        if event.angleDelta().y() < 0:
            zoom_factor = 1.0 / zoom_factor

        current_scale = self.transform().m11()
        new_scale = current_scale * zoom_factor
        if new_scale > 1.0:
            zoom_factor = 1.0 / current_scale

        self.scale(zoom_factor, zoom_factor)
        self.zoom_changed.emit(self.transform().m11())
        self.render_timer.start()
        self.view_rect_changed.emit(self.get_visible_rect())

    def toggle_roi_mode(self, enabled: bool):
        self._is_roi_mode = enabled
        self.setCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor)

    def clear_roi_box(self):
        if self._current_roi_item and self._current_roi_item.scene():
            self.scene_canvas.removeItem(self._current_roi_item)
            self._current_roi_item = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._current_path:
            if self._is_roi_mode:
                self._roi_start_pos = self.mapToScene(event.position().toPoint())
                if self._current_roi_item and self._current_roi_item.scene():
                    self.scene_canvas.removeItem(self._current_roi_item)
                self._current_roi_item = ROIBoxItem()
                self.scene_canvas.addItem(self._current_roi_item)
                self._current_roi_item.update_rect(
                    self._roi_start_pos, self._roi_start_pos
                )
            else:
                self._mark_interaction()
                self._is_panning = True
                self._last_mouse_pos = event.position().toPoint()
                self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._is_roi_mode and self._roi_start_pos is not None:
            current_scene_pos = self.mapToScene(event.position().toPoint())
            if self._current_roi_item:
                self._current_roi_item.update_rect(
                    self._roi_start_pos, current_scene_pos
                )
        elif self._is_panning:
            self._mark_interaction()
            current_pos = event.position().toPoint()
            delta = current_pos - self._last_mouse_pos
            self._last_mouse_pos = current_pos
            h_bar = self.horizontalScrollBar()
            v_bar = self.verticalScrollBar()
            h_bar.setValue(h_bar.value() - delta.x())
            v_bar.setValue(v_bar.value() - delta.y())
            self.render_timer.start()
            self.view_rect_changed.emit(self.get_visible_rect())

        if self._current_path:
            scene_pos = self.mapToScene(event.position().toPoint())
            self.mouse_scene_pos_changed.emit(scene_pos.x(), scene_pos.y())

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self._is_roi_mode and self._roi_start_pos is not None:
                if self._current_roi_item:
                    roi_coords = self._current_roi_item.get_roi_coordinates()
                    self.roi_drawn.emit(roi_coords)
                self._roi_start_pos = None
            else:
                self._is_panning = False
                self.setCursor(Qt.ArrowCursor)
                self.idle_timer.start()
                self.render_timer.start()
        super().mouseReleaseEvent(event)

    def _on_absolute_idle(self):
        if self._is_interaction:
            self._is_interaction = False
            self.interaction_finished.emit()

    def _render_high_res_viewport(self):
        def finish_interaction():
            if self._is_interaction:
                self._is_interaction = False
                self.interaction_finished.emit()

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
        self.setTransformationAnchor(QGraphicsView.AnchorViewCenter)
        self.scale(factor, factor)
        self.setTransformationAnchor(old_anchor)
        self.zoom_changed.emit(self.transform().m11())
        self.render_timer.start()
        self.view_rect_changed.emit(self.get_visible_rect())

    def get_visible_rect(self):
        return self.mapToScene(self.viewport().rect()).boundingRect()

    def _trigger_view_update(self):
        self.view_rect_changed.emit(self.get_visible_rect())

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
        if self.parent():
            self.parent().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent):
        if self.parent():
            self.parent().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        if self.parent():
            self.parent().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent):
        if self.parent():
            self.parent().dropEvent(event)

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
