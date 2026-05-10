from PIL.ImageQt import ImageQt
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QMenu,
)

# Z 值层级常量（minimap 内部）
_Z_BG = 0.0  # 缩略图底图
_Z_HEATMAP = 0.5  # 热力图叠层（介于底图与视口指示器之间）
_Z_INDICATOR = 1.0  # 红色视口指示框（最顶层）

_SIZE_PRESETS = [
    (0.50, "小 50%"),
    (0.75, "中 75%"),
    (1.00, "大 100%"),
    (1.50, "特大 150%"),
]
_BASE_SIZE = 250.0
_DEFAULT_SCALE = 1.0


class MinimapView(QGraphicsView):
    # 点击缩略图时发送 Level 0 坐标（鼠标释放时触发，附带高清渲染）
    navigate_requested = Signal(float, float)
    # 拖拽时实时发送 Level 0 坐标（仅移动视图，不触发高清渲染）
    navigate_drag_requested = Signal(float, float)
    # 尺寸档位变更时发射，携带 scale 值，供 MainWindow 同步菜单勾选状态
    size_scale_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene_canvas = QGraphicsScene(self)
        self.setScene(self.scene_canvas)

        # 初始隐藏，加载 WSI 切片后显示
        self.setVisible(False)

        # 拖拽导航状态
        self._is_dragging = False

        # 优化渲染与隐藏滚动条
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # 1. 底图层 (静态缩略图)
        self.bg_item = QGraphicsPixmapItem()
        self.bg_item.setZValue(_Z_BG)
        self.scene_canvas.addItem(self.bg_item)

        # 2. 热力图叠层（方向三：介于底图与视口指示器之间）
        self.heatmap_mini_item = QGraphicsPixmapItem()
        self.heatmap_mini_item.setZValue(_Z_HEATMAP)
        self.scene_canvas.addItem(self.heatmap_mini_item)

        # 3. 视口指示器层 (红色边框，显式置顶确保不被热力图遮挡)
        self.indicator = QGraphicsRectItem()
        self.indicator.setZValue(_Z_INDICATOR)
        pen = QPen(QColor(255, 0, 0, 220))
        pen.setWidth(2)
        pen.setCosmetic(True)  # 保持线宽不受缩放影响
        self.indicator.setPen(pen)
        self.scene_canvas.addItem(self.indicator)

        self.downsample_factor = 1.0  # Level 0 到缩略图的缩放系数

        # 尺寸档位
        self._size_scale = _DEFAULT_SCALE
        self._thumb_img = None

    def load_minimap(self, thumb_img, downsample_factor: float):
        """将缩略图加载到鹰眼图。thumb_img 为 PIL.Image，downsample_factor 为 Level-0 到缩略图的降采样系数。"""
        self.downsample_factor = downsample_factor
        self._thumb_img = thumb_img
        self.bg_item.setPixmap(QPixmap.fromImage(ImageQt(thumb_img)))

        self.heatmap_mini_item.setPixmap(QPixmap())

        max_size = _BASE_SIZE * self._size_scale
        img_w, img_h = thumb_img.width, thumb_img.height

        if img_w > img_h:
            target_w = int(max_size)
            target_h = int(max_size * (img_h / img_w))
        else:
            target_h = int(max_size)
            target_w = int(max_size * (img_w / img_h))

        self.setFixedSize(target_w, target_h)

        self.scene_canvas.setSceneRect(0, 0, img_w, img_h)
        self.fitInView(self.scene_canvas.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

        self.setVisible(True)

    def set_size_scale(self, scale: float):
        """切换鹰眼图尺寸档位（0.5 / 0.75 / 1.0 / 1.5）。"""
        if abs(self._size_scale - scale) < 1e-6:
            return
        self._size_scale = scale
        if self._thumb_img is not None:
            max_size = _BASE_SIZE * scale
            img_w, img_h = self._thumb_img.width, self._thumb_img.height

            if img_w > img_h:
                target_w = int(max_size)
                target_h = int(max_size * (img_h / img_w))
            else:
                target_h = int(max_size)
                target_w = int(max_size * (img_w / img_h))

            self.setFixedSize(target_w, target_h)
            self.fitInView(self.scene_canvas.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self.size_scale_changed.emit(scale)

    def contextMenuEvent(self, event):
        """右键弹出尺寸档位选择菜单。"""
        menu = QMenu(self)
        menu.setTitle("鹰眼图大小")
        group = QActionGroup(menu)
        group.setExclusive(True)
        for scale, label in _SIZE_PRESETS:
            action = QAction(label, group)
            action.setCheckable(True)
            action.setChecked(abs(self._size_scale - scale) < 1e-6)
            action.triggered.connect(lambda checked, s=scale: self.set_size_scale(s))
            menu.addAction(action)
        menu.exec(event.globalPos())

    def resizeEvent(self, event):
        """视图尺寸改变时调整内容显示"""
        super().resizeEvent(event)
        if self.scene() and not self.scene().sceneRect().isEmpty():
            self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

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
        if event.button() == Qt.MouseButton.LeftButton:
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
        if self._is_dragging and (event.buttons() & Qt.MouseButton.LeftButton):
            if self.downsample_factor <= 0:
                return

            scene_pos = self.mapToScene(event.position().toPoint())

            level0_cx = scene_pos.x() * self.downsample_factor
            level0_cy = scene_pos.y() * self.downsample_factor

            self.navigate_drag_requested.emit(level0_cx, level0_cy)
        # 不调用 super，防止 QGraphicsView 触发自身的拖动滚动行为

    def mouseReleaseEvent(self, event):
        """鹰眼图释放：结束拖拽，发射完整导航信号以触发高清渲染"""
        if event.button() == Qt.MouseButton.LeftButton and self._is_dragging:
            self._is_dragging = False

            scene_pos = self.mapToScene(event.position().toPoint())

            level0_cx = scene_pos.x() * self.downsample_factor
            level0_cy = scene_pos.y() * self.downsample_factor

            # 释放时发射完整信号，触发高清渲染
            self.navigate_requested.emit(level0_cx, level0_cy)

        super().mouseReleaseEvent(event)
