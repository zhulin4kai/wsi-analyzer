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

from workers.gallery_worker import GalleryWorker


class GalleryItemWidget(QWidget):
    """自定义的画廊列表项，用于精细控制序号、图片和文本的排版"""

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)  # 控制序号和图片之间的较近距离

        # 1. 序号标签
        self.lbl_index = QLabel(str(index))
        font = self.lbl_index.font()
        font.setBold(True)
        font.setPointSize(12)
        self.lbl_index.setFont(font)
        self.lbl_index.setFixedWidth(25)
        self.lbl_index.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        # 2. 图片标签 (默认 Loading)
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
        layout.addSpacing(15)  # 控制图片和置信度之间的较远距离
        layout.addWidget(self.lbl_conf)
        layout.addStretch()

    def set_data(self, pixmap: QPixmap, confidence: float):
        self.lbl_image.setPixmap(pixmap)
        self.lbl_conf.setText(f"置信度: {confidence:.2%}")


class LesionGallery(QDockWidget):
    """
    高危病灶画廊停靠组件。
    负责异步截取并展示 Top 50 的疑似病灶区域。
    """

    # 定义跳转信号：抛出需要聚焦的中心点 (cx, cy)
    navigate_requested = Signal(float, float)

    def __init__(self, title="高危病灶画廊 (Top 50)", parent=None):
        super().__init__(title, parent)
        # 允许停靠在左侧、右侧或底部
        self.setAllowedAreas(
            Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea
        )

        # 设置最小宽度，加宽画廊，防止置信度文字被遮挡
        self.setMinimumWidth(320)

        # 初始化垂直列表视图（一行一个，左图右文）
        self.list_widget = QListWidget()
        self.list_widget.setViewMode(QListWidget.ListMode)
        self.list_widget.setIconSize(QSize(128, 128))
        self.list_widget.setSpacing(10)
        self.list_widget.itemClicked.connect(self._on_item_clicked)

        self.setWidget(self.list_widget)

        self.gallery_worker = None
        self.current_wsi_path = None

    def load_results(self, wsi_path: str, results: list):
        """
        核心输入接口：加载新的分析结果并启动后台异步切图
        """
        self.clear_gallery()

        if not results or not wsi_path:
            return

        self.current_wsi_path = wsi_path

        # 按照置信度倒序排序，最多取前 50 个病灶
        top_results = sorted(results, key=lambda x: x["confidence"], reverse=True)[:50]

        # 瞬间创建灰色的占位符 Item
        for i, item in enumerate(top_results):
            list_item = QListWidgetItem()
            # 设置固定高宽，以便容纳 128x128 的图片和外边距 (加宽以防止文字被遮挡)
            list_item.setSizeHint(QSize(300, 140))
            # 将原始的 bbox 坐标和属性埋入底层，用于后续的跳转与校验
            list_item.setData(Qt.UserRole, item)
            self.list_widget.addItem(list_item)

            # 嵌入自定义的精细排版 Widget
            custom_widget = GalleryItemWidget(i + 1)
            self.list_widget.setItemWidget(list_item, custom_widget)

        # 启动后台独立异步截图工具，防止阻塞主界面
        self.gallery_worker = GalleryWorker(self.current_wsi_path, top_results)
        self.gallery_worker.thumb_ready.connect(self._on_thumb_ready)
        self.gallery_worker.start()

    def _on_thumb_ready(self, idx: int, qimg, item_data: dict):
        """
        内部槽函数：接收后台切好的小图并更新到对应的 Item
        """
        # 健壮性检查 1：确保当前列表没有被清空，且索引没有越界
        if idx < self.list_widget.count():
            list_item = self.list_widget.item(idx)
            data = list_item.data(Qt.UserRole)

            # 健壮性检查 2：数据指纹比对防串图
            # 必须验证传回来的结果与 UI 格子底层的原始指纹一致，才允许渲染
            if data and data.get("bbox") == item_data.get("bbox"):
                pixmap = QPixmap.fromImage(qimg)
                # 找到该 Item 绑定的自定义 Widget 并更新图像和文字
                custom_widget = self.list_widget.itemWidget(list_item)
                if isinstance(custom_widget, GalleryItemWidget):
                    custom_widget.set_data(pixmap, item_data["confidence"])

    def _on_item_clicked(self, item: QListWidgetItem):
        """
        内部槽函数：点击画廊小图，向外发射靶向平移聚焦信号
        """
        data = item.data(Qt.UserRole)
        if not data:
            return

        b = data["bbox"]
        # 计算病灶绝对物理中心点
        cx = (b[0] + b[2]) / 2.0
        cy = (b[1] + b[3]) / 2.0

        # 向主窗口抛出平移请求
        self.navigate_requested.emit(cx, cy)

    def clear_gallery(self):
        """
        生命周期安全管理：清理画廊和后台线程
        """
        if self.gallery_worker:
            # 仅仅发出中断信号，并解绑槽函数，不使用 wait() 阻塞主线程
            self.gallery_worker.thumb_ready.disconnect(self._on_thumb_ready)
            self.gallery_worker.cancel()
            self.gallery_worker = None

        self.list_widget.clear()
        self.current_wsi_path = None
