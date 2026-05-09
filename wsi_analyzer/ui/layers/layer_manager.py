from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGraphicsItemGroup, QGraphicsPixmapItem

from wsi_analyzer.config.config import AI_LAYER_Z_VALUE, HEATMAP_Z_VALUE
from wsi_analyzer.ui.layers.annotation_layer import AnnotationLayer
from wsi_analyzer.ui.layers.detection_layer import DetectionLayer
from wsi_analyzer.ui.layers.heatmap_layer import HeatmapLayer


class LayerManager:
    def __init__(self, scene):
        self.scene = scene

        self.heatmap_layer_item = QGraphicsPixmapItem()
        self.heatmap_layer_item.setZValue(HEATMAP_Z_VALUE)
        self.heatmap_layer_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.scene.addItem(self.heatmap_layer_item)
        self.heatmap = HeatmapLayer(self.heatmap_layer_item)

        ai_group = QGraphicsItemGroup()
        ai_group.setZValue(AI_LAYER_Z_VALUE)
        self.scene.addItem(ai_group)
        self.detection = DetectionLayer(ai_group, scene)

        imported_group = QGraphicsItemGroup()
        imported_group.setZValue(AI_LAYER_Z_VALUE + 10)
        self.scene.addItem(imported_group)
        self.annotation = AnnotationLayer(imported_group, scene)

        # backward compat aliases
        self.ai_layer_group = ai_group
        self.imported_layer_group = imported_group

    def set_ai_visible(self, visible: bool):
        self.detection.set_visible(visible)
        self.annotation.set_visible(visible)

    def set_heatmap_visible(self, visible: bool):
        self.heatmap.set_visible(visible)

    def clear_ai_items(self):
        self.detection.clear()
        self.annotation.clear()

    def clear_imported_items(self):
        self.annotation.clear()

    def clear_heatmap(self):
        self.heatmap.clear()
