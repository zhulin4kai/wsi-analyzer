from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import QGraphicsRectItem

from wsi_analyzer.config.config import AI_PEN_COLOR, AI_PEN_WIDTH


class DetectionLayer:
    def __init__(self, group, scene):
        self._group = group
        self._scene = scene

    def render(self, results):
        self.clear()
        for data in results:
            x_min, y_min, x_max, y_max = data["bbox"]
            rect = QGraphicsRectItem(QRectF(x_min, y_min, x_max - x_min, y_max - y_min))
            pen = QPen(QColor(*AI_PEN_COLOR))
            pen.setWidth(AI_PEN_WIDTH)
            pen.setCosmetic(True)
            rect.setPen(pen)
            rect.setToolTip(f"微乳头状癌病灶\n置信度: {data['confidence']:.2%}")
            self._group.addToGroup(rect)

    def clear(self):
        for item in self._group.childItems():
            self._group.removeFromGroup(item)
            self._scene.removeItem(item)

    def set_visible(self, visible: bool):
        self._group.setVisible(visible)
