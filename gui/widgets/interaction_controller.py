from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent

from .roi_box_item import ROIBoxItem


class InteractionController(QObject):
    """WSIView 的鼠标/拖拽/ROI 交互逻辑独立模块。

    通过注入 view (QGraphicsView) 和 scene (QGraphicsScene) 操作视图，
    不继承 QGraphicsView。处理平移、缩放、ROI 绘制及拖拽事件转发。
    """

    interaction_started = Signal()
    interaction_finished = Signal()
    roi_drawn = Signal(tuple)
    viewport_changed = Signal()

    def __init__(self, view, scene, idle_threshold_ms, parent=None):
        """
        :param view:  QGraphicsView 实例（用于 mapToScene / scrollbar / cursor）
        :param scene: QGraphicsScene 实例（用于 ROIBoxItem 的生命周期管理）
        :param idle_threshold_ms: 交互绝对空闲判定的超时阈值（毫秒）
        """
        super().__init__(parent)
        self._view = view
        self._scene = scene

        # ── Pan 状态 ──
        self._is_panning = False
        self._last_mouse_pos = None

        # ── ROI 状态 ──
        self._is_roi_mode = False
        self._roi_start_pos = None
        self._current_roi_item = None

        # ── 交互空闲检测 ──
        self._is_interaction = False
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(idle_threshold_ms)
        self._idle_timer.timeout.connect(self._on_absolute_idle)

    # ── Public API ────────────────────────────────────────────────────

    def toggle_roi_mode(self, enabled: bool):
        self._is_roi_mode = enabled
        self._view.setCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor)

    def clear_roi_box(self):
        if self._current_roi_item and self._current_roi_item.scene():
            self._scene.removeItem(self._current_roi_item)
            self._current_roi_item = None

    def mark_idle(self):
        """强制结束交互状态（供渲染流水线在瓦片就绪/渲染完成时调用）。"""
        if self._is_interaction:
            self._is_interaction = False
            self.interaction_finished.emit()

    # ── Event Handlers ────────────────────────────────────────────────

    def handle_mouse_press(self, event, has_slide: bool):
        """返回 True 表示已消耗事件，调用方应跳过 super().mousePressEvent()"""
        if event.button() != Qt.LeftButton or not has_slide:
            return False

        if self._is_roi_mode:
            pos = self._view.mapToScene(event.position().toPoint())
            self._roi_start_pos = pos
            self.clear_roi_box()
            self._current_roi_item = ROIBoxItem()
            self._scene.addItem(self._current_roi_item)
            self._current_roi_item.update_rect(pos, pos)
        else:
            self._mark_interaction()
            self._is_panning = True
            self._last_mouse_pos = event.position().toPoint()
            self._view.setCursor(Qt.ClosedHandCursor)
        return True

    def handle_mouse_move(self, event):
        if self._is_roi_mode and self._roi_start_pos is not None:
            current_pos = self._view.mapToScene(event.position().toPoint())
            if self._current_roi_item:
                self._current_roi_item.update_rect(self._roi_start_pos, current_pos)
        elif self._is_panning:
            self._mark_interaction()
            current_pos = event.position().toPoint()
            delta = current_pos - self._last_mouse_pos
            self._last_mouse_pos = current_pos
            h_bar = self._view.horizontalScrollBar()
            v_bar = self._view.verticalScrollBar()
            h_bar.setValue(h_bar.value() - delta.x())
            v_bar.setValue(v_bar.value() - delta.y())
            self.viewport_changed.emit()

    def handle_mouse_release(self, event):
        if event.button() != Qt.LeftButton:
            return

        if self._is_roi_mode and self._roi_start_pos is not None:
            if self._current_roi_item:
                coords = self._current_roi_item.get_roi_coordinates()
                self.roi_drawn.emit(coords)
            self._roi_start_pos = None
        else:
            self._is_panning = False
            self._view.setCursor(Qt.ArrowCursor)
            self._idle_timer.start()
            self.viewport_changed.emit()

    def handle_wheel(self, event, has_slide: bool) -> float | None:
        """返回新的 zoom_factor 供调用方应用缩放；若不应缩放则返回 None"""
        if not has_slide:
            return None

        self._mark_interaction()
        zoom_in = event.angleDelta().y() > 0
        factor = 1.15 if zoom_in else 1.0 / 1.15

        current_scale = self._view.transform().m11()
        if current_scale * factor > 1.0:
            factor = 1.0 / current_scale

        self.viewport_changed.emit()
        return factor

    # ── Drag & Drop 转发 ──────────────────────────────────────────────

    def handle_drag_enter(self, event: QDragEnterEvent):
        if self._view.parent():
            self._view.parent().dragEnterEvent(event)

    def handle_drag_move(self, event: QDragMoveEvent):
        if self._view.parent():
            self._view.parent().dragMoveEvent(event)

    def handle_drag_leave(self, event):
        if self._view.parent():
            self._view.parent().dragLeaveEvent(event)

    def handle_drop(self, event: QDropEvent):
        if self._view.parent():
            self._view.parent().dropEvent(event)

    # ── Internal ──────────────────────────────────────────────────────

    def _mark_interaction(self):
        self._idle_timer.start()
        if not self._is_interaction:
            self._is_interaction = True
            self.interaction_started.emit()

    def _on_absolute_idle(self):
        if self._is_interaction:
            self._is_interaction = False
            self.interaction_finished.emit()
