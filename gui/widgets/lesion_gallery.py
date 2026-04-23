from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QDockWidget, QListWidget, QListWidgetItem

from workers.gallery_worker import GalleryWorker


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
            list_item = QListWidgetItem(f"   Top {i + 1}  -  Loading...")
            # 左对齐，让文字靠在图片右边显示
            list_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            # 将原始的 bbox 坐标和属性埋入底层，用于后续的跳转与校验
            list_item.setData(Qt.UserRole, item)
            self.list_widget.addItem(list_item)

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
                list_item.setIcon(QIcon(pixmap))
                # 重新排版文本，使其在一行内水平显示
                list_item.setText(
                    f"   Top {idx + 1}  |  置信度: {item_data['confidence']:.2%}"
                )

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
