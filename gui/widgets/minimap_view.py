from PIL.ImageQt import ImageQt
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
)


class MinimapView(QGraphicsView):
    # 点击缩略图时发送 Level 0 坐标（鼠标释放时触发，附带高清渲染）
    navigate_requested = Signal(float, float)
    # 拖拽时实时发送 Level 0 坐标（仅移动视图，不触发高清渲染）
    navigate_drag_requested = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene_canvas = QGraphicsScene(self)
        self.setScene(self.scene_canvas)

        # 初始隐藏，加载 WSI 切片后显示
        self.setVisible(False)

        # 拖拽导航状态
        self._is_dragging = False

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
        thumb_img, self.downsample_factor = slide_engine.get_thumbnail(
            level_from_last=1
        )

        self.bg_item.setPixmap(QPixmap.fromImage(ImageQt(thumb_img)))

        # 根据切片比例计算缩略图尺寸
        max_size = 250.0  # 以250像素为最大边长基准
        img_w, img_h = thumb_img.width, thumb_img.height

        if img_w > img_h:
            target_w = int(max_size)
            target_h = int(max_size * (img_h / img_w))
        else:
            target_h = int(max_size)
            target_w = int(max_size * (img_w / img_h))

        self.setFixedSize(target_w, target_h)

        # 约束 Scene 大小并自动适配 View 视口
        self.scene_canvas.setSceneRect(0, 0, img_w, img_h)
        self.fitInView(self.scene_canvas.sceneRect(), Qt.KeepAspectRatio)

        # 显示鹰眼图
        self.setVisible(True)

    def resizeEvent(self, event):
        """视图尺寸改变时调整内容显示"""
        super().resizeEvent(event)
        if self.scene() and not self.scene().sceneRect().isEmpty():
            self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)

    def update_indicator(self, level0_rect: QRectF):
        """主视图同步至鹰眼图"""
        if self.downsample_factor <= 0:
            return
        # 坐标换算：Level 0 -> 鹰眼图局部坐标
        x = level0_rect.x() / self.downsample_factor
        y = level0_rect.y() / self.downsample_factor
        w = level0_rect.width() / self.downsample_factor
        h = level0_rect.height() / self.downsample_factor

        self.indicator.setRect(x, y, w, h)
        self.viewport().update()

    def mousePressEvent(self, event):
        """鹰眼图鼠标按下：记录拖拽起点并发射轻量导航信号"""
        if event.button() == Qt.LeftButton:
            self._is_dragging = True

            # 控件坐标转换为 Scene 坐标
            scene_pos = self.mapToScene(event.position().toPoint())

            # 坐标换算：鹰眼图 -> Level 0 绝对坐标
            level0_cx = scene_pos.x() * self.downsample_factor
            level0_cy = scene_pos.y() * self.downsample_factor

            # 按下时仅发射轻量信号，移动视图但不触发高清渲染
            self.navigate_drag_requested.emit(level0_cx, level0_cy)

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """鹰眼图拖拽：持续发射轻量导航信号，不触发高清渲染"""
        if self._is_dragging and (event.buttons() & Qt.LeftButton):
            if self.downsample_factor <= 0:
                return

            scene_pos = self.mapToScene(event.position().toPoint())

            level0_cx = scene_pos.x() * self.downsample_factor
            level0_cy = scene_pos.y() * self.downsample_factor

            self.navigate_drag_requested.emit(level0_cx, level0_cy)
        # 不调用 super，防止 QGraphicsView 触发自身的拖动滚动行为

    def mouseReleaseEvent(self, event):
        """鹰眼图释放：结束拖拽，发射完整导航信号以触发高清渲染"""
        if event.button() == Qt.LeftButton and self._is_dragging:
            self._is_dragging = False

            scene_pos = self.mapToScene(event.position().toPoint())

            level0_cx = scene_pos.x() * self.downsample_factor
            level0_cy = scene_pos.y() * self.downsample_factor

            # 释放时发射完整信号，触发高清渲染
            self.navigate_requested.emit(level0_cx, level0_cy)

        super().mouseReleaseEvent(event)
