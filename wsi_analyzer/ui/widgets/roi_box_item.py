from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtWidgets import QGraphicsRectItem


class ROIBoxItem(QGraphicsRectItem):
    """
    感兴趣区域 (ROI) 选择框的可视化表示。
    提供样式设置和坐标提取，用于靶向 AI 推理。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_style()

    def _setup_style(self):
        """初始化 ROI 边界框的视觉样式。"""
        # 高可见度虚线边框
        pen = QPen(QColor(0, 255, 0))
        pen.setWidth(3)
        pen.setStyle(Qt.PenStyle.DashLine)
        # 防止画笔宽度随视图缩放，以保持一致的可见度
        pen.setCosmetic(True)
        self.setPen(pen)

        # 用于区域高亮的半透明填充
        brush = QBrush(QColor(0, 255, 0, 40))
        self.setBrush(brush)

        # 分配高 Z 值以确保 ROI 框渲染在所有瓦片和模型结果之上
        self.setZValue(1000)

    def update_rect(self, start_pos: QPointF, current_pos: QPointF):
        """
        根据交互点更新矩形尺寸。

        :param start_pos: 拖拽动作的起始点 (QPointF)
        :param current_pos: 当前鼠标光标位置 (QPointF)
        """
        x_min = min(start_pos.x(), current_pos.x())
        y_min = min(start_pos.y(), current_pos.y())
        width = abs(start_pos.x() - current_pos.x())
        height = abs(start_pos.y() - current_pos.y())

        self.setRect(QRectF(x_min, y_min, width, height))

    def get_roi_coordinates(self):
        """
        获取 ROI 的绝对物理坐标。

        :return: 对应于 Level 0 分辨率的 (X_min, Y_min, X_max, Y_max) 元组
        """
        rect = self.rect()
        return (
            int(rect.left()),
            int(rect.top()),
            int(rect.right()),
            int(rect.bottom()),
        )
