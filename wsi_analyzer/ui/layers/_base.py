from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import QGraphicsRectItem


def make_rect_item(data: dict, color: tuple, width: int, tooltip: str) -> QGraphicsRectItem:
    x_min, y_min, x_max, y_max = data["bbox"]
    rect = QGraphicsRectItem(QRectF(x_min, y_min, x_max - x_min, y_max - y_min))
    pen = QPen(QColor(*color))
    pen.setWidth(width)
    pen.setCosmetic(True)
    rect.setPen(pen)
    rect.setToolTip(tooltip)
    return rect
