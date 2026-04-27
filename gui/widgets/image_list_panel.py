import os

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDockWidget,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config import IMAGE_LIST_THUMB_H, IMAGE_LIST_THUMB_W
from workers.thumbnail_worker import ThumbnailWorker


class ImageListPanel(QDockWidget):
    """
    图像列表停靠面板，支持多 WSI 文件管理。
    双击列表项加载切片，底部搜索栏支持按文件名实时过滤。
    """

    # 双击图像项时发射，携带文件绝对路径
    image_load_requested = Signal(str)
    # 点击"添加图像"按钮时发射，由外部处理文件对话框
    add_requested = Signal()

    def __init__(self, parent=None):
        super().__init__("图像列表", parent)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setMinimumWidth(200)

        # 已添加的文件绝对路径列表（保持与列表项一一对应的顺序）
        self._entries = []
        # 已成功加载缩略图的项索引集合
        self._thumb_loaded = set()
        # 当前缩略图加载 Worker
        self._thumb_worker = None
        # 已取消但仍在运行的旧 Worker 引用，防止 QThread 被 GC 回收导致崩溃
        self._dead_workers = []

        # --- 布局 ---
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # 添加图像按钮
        self.btn_add = QPushButton("添加图像...")
        self.btn_add.clicked.connect(self.add_requested)
        layout.addWidget(self.btn_add)

        # 图像列表
        self.list_widget = QListWidget()
        self.list_widget.setIconSize(QSize(IMAGE_LIST_THUMB_W, IMAGE_LIST_THUMB_H))
        self.list_widget.setSpacing(2)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.list_widget)

        # 搜索栏
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("搜索图像...")
        self.search_bar.textChanged.connect(self._on_search_changed)
        layout.addWidget(self.search_bar)

        self.setWidget(container)

    def add_image(self, file_path: str):
        """将单个 WSI 文件路径加入列表（自动去重）。"""
        self.add_images([file_path])

    def add_images(self, paths: list):
        """批量添加多个 WSI 文件路径到列表（自动去重），统一触发一次缩略图加载。"""
        added = False
        for file_path in paths:
            abs_path = os.path.abspath(file_path)
            if abs_path in self._entries:
                continue

            self._entries.append(abs_path)

            item = QListWidgetItem(os.path.basename(abs_path))
            item.setData(Qt.UserRole, abs_path)
            if not os.path.exists(abs_path):
                item.setToolTip("文件不存在")
            self.list_widget.addItem(item)
            added = True

        if added:
            self._restart_thumb_worker()

    def highlight(self, file_path: str):
        """在列表中高亮显示指定路径对应的项。"""
        abs_path = os.path.abspath(file_path)
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.UserRole) == abs_path:
                self.list_widget.setCurrentItem(item)
                return

    def _restart_thumb_worker(self):
        """取消旧 Worker，以所有未加载项重新启动缩略图加载。"""
        pending = [
            (i, self._entries[i])
            for i in range(len(self._entries))
            if i not in self._thumb_loaded
        ]
        if not pending:
            return

        if self._thumb_worker:
            # 断开旧信号，使其残余输出不影响当前列表
            self._thumb_worker.thumb_ready.disconnect(self._on_thumb_ready)
            self._thumb_worker.cancel()
            # 保留引用直到线程自然退出，防止 QThread 在运行中被 GC 回收导致崩溃
            self._dead_workers.append(self._thumb_worker)

        # 清理已结束的旧 Worker，释放内存
        self._dead_workers = [w for w in self._dead_workers if w.isRunning()]

        self._thumb_worker = ThumbnailWorker(
            pending, IMAGE_LIST_THUMB_W, IMAGE_LIST_THUMB_H
        )
        self._thumb_worker.thumb_ready.connect(self._on_thumb_ready)
        self._thumb_worker.start()

    def _on_thumb_ready(self, index: int, qimg):
        """接收后台缩略图，更新对应列表项图标。"""
        self._thumb_loaded.add(index)
        if index < self.list_widget.count():
            item = self.list_widget.item(index)
            if item:
                item.setIcon(QIcon(QPixmap.fromImage(qimg)))

    def _on_item_double_clicked(self, item: QListWidgetItem):
        """双击时校验文件存在性后发射加载请求。"""
        path = item.data(Qt.UserRole)
        if path and os.path.exists(path):
            self.image_load_requested.emit(path)
        else:
            QMessageBox.warning(self, "文件不存在", f"无法找到文件：\n{path}")

    def _on_context_menu(self, pos):
        """右键菜单：从列表中移除选中项。"""
        item = self.list_widget.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        action_remove = menu.addAction("从列表移除")
        if menu.exec(self.list_widget.mapToGlobal(pos)) == action_remove:
            self._remove_item(item)

    def _remove_item(self, item: QListWidgetItem):
        """从列表和内部记录中删除指定项，同步修正缩略图加载索引。"""
        path = item.data(Qt.UserRole)
        row = self.list_widget.row(item)
        self.list_widget.takeItem(row)
        if path in self._entries:
            self._entries.remove(path)

        # 删除项后索引整体偏移，重建缩略图已加载索引集合
        self._thumb_loaded = {
            (i if i < row else i - 1) for i in self._thumb_loaded if i != row
        }

    def _on_search_changed(self, text: str):
        """按文件名实时过滤列表项的显示。"""
        lower = text.lower()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            name = os.path.basename(item.data(Qt.UserRole)).lower()
            item.setHidden(lower not in name)
