from wsi_analyzer.config.config import AI_PEN_COLOR, AI_PEN_WIDTH
from wsi_analyzer.ui.layers._base import make_rect_item


class DetectionLayer:
    def __init__(self, group, scene):
        self._group = group
        self._scene = scene

    def render(self, results):
        self.clear()
        for data in results:
            rect = make_rect_item(
                data, AI_PEN_COLOR, AI_PEN_WIDTH,
                f"微乳头状癌病灶\n置信度: {data['confidence']:.2%}",
            )
            self._group.addToGroup(rect)

    def clear(self):
        for item in self._group.childItems():
            self._group.removeFromGroup(item)
            self._scene.removeItem(item)

    def set_visible(self, visible: bool):
        self._group.setVisible(visible)
