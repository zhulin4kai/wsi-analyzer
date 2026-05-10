from wsi_analyzer.config.config import IMPORTED_ANNOTATION_COLOR, IMPORTED_ANNOTATION_WIDTH
from wsi_analyzer.ui.layers._base import make_rect_item


class AnnotationLayer:
    def __init__(self, group, scene):
        self._group = group
        self._scene = scene

    def render(self, results):
        self.clear()
        for data in results:
            rect = make_rect_item(
                data, IMPORTED_ANNOTATION_COLOR, IMPORTED_ANNOTATION_WIDTH,
                f"导入标注: {data.get('class_id', '-')}\n置信度: {data.get('confidence', 0):.2%}",
            )
            self._group.addToGroup(rect)

    def clear(self):
        for item in self._group.childItems():
            self._group.removeFromGroup(item)
            self._scene.removeItem(item)

    def set_visible(self, visible: bool):
        self._group.setVisible(visible)
