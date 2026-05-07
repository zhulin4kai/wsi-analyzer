from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGraphicsItemGroup, QGraphicsPixmapItem

from config import AI_LAYER_Z_VALUE, HEATMAP_Z_VALUE


class LayerManager:
    def __init__(self, scene):
        self.scene = scene

        self.heatmap_layer_item = QGraphicsPixmapItem()
        self.heatmap_layer_item.setZValue(HEATMAP_Z_VALUE)
        self.heatmap_layer_item.setTransformationMode(Qt.SmoothTransformation)
        self.scene.addItem(self.heatmap_layer_item)

        self.ai_layer_group = QGraphicsItemGroup()
        self.ai_layer_group.setZValue(AI_LAYER_Z_VALUE)
        self.scene.addItem(self.ai_layer_group)

        self.imported_layer_group = QGraphicsItemGroup()
        self.imported_layer_group.setZValue(AI_LAYER_Z_VALUE + 10)
        self.scene.addItem(self.imported_layer_group)

    def set_ai_visible(self, visible: bool):
        self.ai_layer_group.setVisible(visible)
        self.imported_layer_group.setVisible(visible)

    def set_heatmap_visible(self, visible: bool):
        self.heatmap_layer_item.setVisible(visible)

    def clear_ai_items(self):
        for item in list(self.ai_layer_group.childItems()):
            self.ai_layer_group.removeFromGroup(item)
            self.scene.removeItem(item)

    def clear_imported_items(self):
        for item in list(self.imported_layer_group.childItems()):
            self.imported_layer_group.removeFromGroup(item)
            self.scene.removeItem(item)

    def clear_heatmap(self):
        self.heatmap_layer_item.setPixmap(None)
