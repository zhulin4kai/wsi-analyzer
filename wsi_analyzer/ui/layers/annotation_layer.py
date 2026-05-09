from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import QGraphicsRectItem

from wsi_analyzer.config.config import IMPORTED_ANNOTATION_COLOR, IMPORTED_ANNOTATION_WIDTH


class AnnotationLayer:
    def __init__(self, group, scene):
        self._group = group
        self._scene = scene

    def render(self, results):
        self.clear()
        for data in results:
            x_min, y_min, x_max, y_max = data["bbox"]
            rect = QGraphicsRectItem(QRectF(x_min, y_min, x_max - x_min, y_max - y_min))
            pen = QPen(QColor(*IMPORTED_ANNOTATION_COLOR))
            pen.setWidth(IMPORTED_ANNOTATION_WIDTH)
            pen.setCosmetic(True)
            rect.setPen(pen)
            rect.setToolTip(
                f"导入标注: {data.get('class_id', '-')}"
                f"\n置信度: {data.get('confidence', 0):.2%}"
            )
            self._group.addToGroup(rect)

    def clear(self):
        for item in self._group.childItems():
            self._group.removeFromGroup(item)
            self._scene.removeItem(item)

    def set_visible(self, visible: bool):
        self._group.setVisible(visible)
