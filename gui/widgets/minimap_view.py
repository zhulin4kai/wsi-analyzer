from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsPixmapItem
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QPen, QColor, QPixmap, QPainter
from PIL.ImageQt import ImageQt

class MinimapView(QGraphicsView):
    # 信号：当用户点击鹰眼图时，向外抛出 Level 0 的绝对中心坐标
    navigate_requested = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene_canvas = QGraphicsScene(self)
        self.setScene(self.scene_canvas)

        # 优化渲染与隐藏滚动条
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # 1. 底图层 (静态缩略图)
        self.bg_item = QGraphicsPixmapItem()
        self.scene_canvas.addItem(self.bg_item)

        # 2. 视口指示器层 (红色边框)
        self.indicator = QGraphicsRectItem()
        pen = QPen(QColor(255, 0, 0, 220))
        pen.setWidth(2)
        pen.setCosmetic(True)  # 保持线宽不受缩放影响
        self.indicator.setPen(pen)
        self.scene_canvas.addItem(self.indicator)

        self.downsample_factor = 1.0  # Level 0 到缩略图的缩放系数

    def load_minimap(self, slide_engine):
        """加载缩略图并计算映射系数"""
        thumb_img, self.downsample_factor = slide_engine.get_thumbnail(level_from_last=1)

        self.bg_item.setPixmap(QPixmap.fromImage(ImageQt(thumb_img)))

        # 约束 Scene 大小并自动适配 View 视口
        self.scene_canvas.setSceneRect(0, 0, thumb_img.width, thumb_img.height)
        self.fitInView(self.scene_canvas.sceneRect(), Qt.KeepAspectRatio)

    def update_indicator(self, level0_rect: QRectF):
        """【单向同步】：主视图 -> 鹰眼图"""
        if self.downsample_factor <= 0: return
        # 核心算式：Level0 坐标 / 缩放系数 = 鹰眼图局部坐标
        x = level0_rect.x() / self.downsample_factor
        y = level0_rect.y() / self.downsample_factor
        w = level0_rect.width() / self.downsample_factor
        h = level0_rect.height() / self.downsample_factor

        self.indicator.setRect(x, y, w, h)
        self.viewport().update()

    def mousePressEvent(self, event):
        """【双向同步】：鹰眼图 -> 主视图"""
        if event.button() == Qt.LeftButton:
            # 将鼠标点击在控件上的位置转为鹰眼图 Scene 坐标
            scene_pos = self.mapToScene(event.position().toPoint())

            # 核心算式：鹰眼图坐标 * 缩放系数 = 主视图(Level 0)绝对坐标
            level0_cx = scene_pos.x() * self.downsample_factor
            level0_cy = scene_pos.y() * self.downsample_factor

            # 发射跳转请求信号
            self.navigate_requested.emit(level0_cx, level0_cy)

        super().mousePressEvent(event)