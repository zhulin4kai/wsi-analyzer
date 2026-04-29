from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QWidget,
)

from workers import GalleryWorker


class GalleryItemWidget(QWidget):
    """画廊列表项"""

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)

        # 1. 序号标签
        self.lbl_index = QLabel(str(index))
        font = self.lbl_index.font()
        font.setBold(True)
        font.setPointSize(12)
        self.lbl_index.setFont(font)
        self.lbl_index.setFixedWidth(25)
        self.lbl_index.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        # 2. 图片标签 (初始状态)
        self.lbl_image = QLabel("Loading...")
        self.lbl_image.setFixedSize(128, 128)
        self.lbl_image.setAlignment(Qt.AlignCenter)
        self.lbl_image.setStyleSheet(
            "background-color: #f0f0f0; color: #888; border: 1px solid #ddd;"
        )

        # 3. 置信度文本标签
        self.lbl_conf = QLabel("")
        self.lbl_conf.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        layout.addWidget(self.lbl_index)
        layout.addWidget(self.lbl_image)
        layout.addSpacing(15)
        layout.addWidget(self.lbl_conf)
        layout.addStretch()

    def set_data(self, pixmap: QPixmap, confidence: float):
        self.lbl_image.setPixmap(pixmap)
        self.lbl_conf.setText(f"置信度: {confidence:.2%}")


class LesionGallery(QDockWidget):
    """
    病灶画廊停靠组件。
    负责展示高置信度的疑似病灶区域。
    """

    # 跳转信号
    navigate_requested = Signal(float, float)

    def __init__(self, title="病灶画廊 (Top 50)", parent=None):
        super().__init__(title, parent)
        # 设置允许停靠区域
        self.setAllowedAreas(
            Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea
        )

        # 设置最小宽度以防止内容遮挡
        self.setMinimumWidth(320)

        # 停靠时不显示关闭按钮，浮动时显示
        self.setFeatures(
            QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetMovable
        )
        self.topLevelChanged.connect(self._on_top_level_changed)

        # 初始化垂直列表视图（一行一个，左图右文）
        self.list_widget = QListWidget()
        self.list_widget.setViewMode(QListWidget.ListMode)
        self.list_widget.setIconSize(QSize(128, 128))
        self.list_widget.setSpacing(10)
        self.list_widget.itemClicked.connect(self._on_item_clicked)

        self.setWidget(self.list_widget)

        self.gallery_worker = None
        self.current_wsi_path = None

    def _on_top_level_changed(self, floating: bool):
        """悬浮时显示关闭按钮，停靠时隐藏关闭按钮"""
        if floating:
            self.setFeatures(
                QDockWidget.DockWidgetFloatable
                | QDockWidget.DockWidgetMovable
                | QDockWidget.DockWidgetClosable
            )
        else:
            self.setFeatures(
                QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetMovable
            )

    def closeEvent(self, event):
        """点击悬浮窗关闭按钮时归位至停靠区域，而非隐藏"""
        self.setFloating(False)
        event.ignore()

    def load_results(self, wsi_path: str, results: list):
        """加载分析结果并启动后台异步切图。"""
        self.clear_gallery()

        if not results or not wsi_path:
            self.hide()
            return

        self.show()
        self.current_wsi_path = wsi_path

        # 按照置信度倒序排序，取前 50 个病灶
        top_results = sorted(results, key=lambda x: x["confidence"], reverse=True)[:50]

        # 创建占位项
        for i, item in enumerate(top_results):
            list_item = QListWidgetItem()
            # 设置尺寸
            list_item.setSizeHint(QSize(300, 140))
            # 存储边界框及属性数据
            list_item.setData(Qt.UserRole, item)
            self.list_widget.addItem(list_item)

            # 嵌入自定义排版组件
            custom_widget = GalleryItemWidget(i + 1)
            self.list_widget.setItemWidget(list_item, custom_widget)

        # 启动后台异步切图
        self.gallery_worker = GalleryWorker(self.current_wsi_path, top_results)
        self.gallery_worker.thumb_ready.connect(self._on_thumb_ready)
        self.gallery_worker.start()

    def _on_thumb_ready(self, idx: int, qimg, item_data: dict):
        """
        接收后台缩略图并更新列表项
        """
        # 校验列表项索引
        if idx < self.list_widget.count():
            list_item = self.list_widget.item(idx)
            data = list_item.data(Qt.UserRole)

            # 校验数据一致性
            if data and data.get("bbox") == item_data.get("bbox"):
                pixmap = QPixmap.fromImage(qimg)
                # 更新对应组件的图像与文本
                custom_widget = self.list_widget.itemWidget(list_item)
                if isinstance(custom_widget, GalleryItemWidget):
                    custom_widget.set_data(pixmap, item_data["confidence"])

    def _on_item_clicked(self, item: QListWidgetItem):
        """
        处理点击事件，发送聚焦信号
        """
        data = item.data(Qt.UserRole)
        if not data:
            return

        b = data["bbox"]
        # 计算中心坐标
        cx = (b[0] + b[2]) / 2.0
        cy = (b[1] + b[3]) / 2.0

        # 发送跳转请求
        self.navigate_requested.emit(cx, cy)

    def clear_gallery(self):
        """清理画廊及相关线程资源。"""
        if self.gallery_worker:
            self.gallery_worker.thumb_ready.disconnect(self._on_thumb_ready)
            self.gallery_worker.cancel()
            self.gallery_worker = None

        self.list_widget.clear()
        self.current_wsi_path = None
        self.hide()
