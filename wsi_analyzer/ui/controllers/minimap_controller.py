from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QVBoxLayout

from wsi_analyzer.ui.widgets import MinimapView


class MinimapController:
    SIZE_PRESETS = [
        (0.50, "小 50%"),
        (0.75, "中 75%"),
        (1.00, "大 100%"),
        (1.50, "特大 150%"),
    ]

    def __init__(self, viewer, parent=None):
        self.viewer = viewer
        self.parent = parent or viewer
        self.minimap = MinimapView(viewer)
        self._size_actions = []

    def setup(self):
        shadow = QGraphicsDropShadowEffect(self.parent)
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 100))
        shadow.setOffset(2, 2)
        self.minimap.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self.viewer)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.minimap, alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

        self.viewer.view_rect_changed.connect(self.minimap.update_indicator)
        self.minimap.navigate_requested.connect(self._navigate_main_view)
        self.minimap.navigate_drag_requested.connect(self._navigate_main_view_light)
        self.minimap.size_scale_changed.connect(self._sync_size_actions)

    def _navigate_main_view(self, cx, cy):
        self.viewer.navigate_to(cx, cy, render=True)

    def _navigate_main_view_light(self, cx, cy):
        self.viewer.navigate_to(cx, cy, render=False)

    def set_visible(self, visible: bool):
        self.minimap.setVisible(visible)

    def is_visible(self) -> bool:
        return self.minimap.isVisible()

    def set_size_scale(self, scale: float):
        self.minimap.set_size_scale(scale)

    def register_size_actions(self, actions):
        self._size_actions = list(actions)

    def _sync_size_actions(self, scale: float):
        for action in self._size_actions:
            value = action.data()
            if value is not None:
                action.setChecked(abs(float(value) - scale) < 1e-6)
