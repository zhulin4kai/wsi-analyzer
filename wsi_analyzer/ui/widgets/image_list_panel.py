import os

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Signal
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

from wsi_analyzer.config.config import IMAGE_LIST_THUMB_H, IMAGE_LIST_THUMB_W
from wsi_analyzer.workers import ThumbnailWorker


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
        super().__init__("切片列表", parent)
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.setMinimumWidth(200)

        # 停靠时不显示关闭按钮，浮动时显示
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetFloatable | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )
        self.topLevelChanged.connect(self._on_top_level_changed)

        # 已添加的文件绝对路径列表（保持与列表项一一对应的顺序）
        self._entries = []
        # 已成功加载缩略图的项索引集合
        self._thumb_loaded = set()
        # 当前缩略图加载 Worker
        self._thumb_worker = None
        # 已取消但仍在运行的旧 Worker 引用，防止 QThread 被 GC 回收导致崩溃
        self._dead_workers = []

        # 快速切换保护：_loading 标志防止 load_wsi 并发，_pending_load_path 记录最后一次请求
        self._loading = False
        self._pending_load_path = None

        # --- 布局 ---
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # 添加图像按钮
        self.btn_add = QPushButton("添加图像")
        self.btn_add.clicked.connect(self.add_requested)
        layout.addWidget(self.btn_add)

        # 图像列表
        self.list_widget = QListWidget()
        self.list_widget.setIconSize(QSize(IMAGE_LIST_THUMB_W, IMAGE_LIST_THUMB_H))
        self.list_widget.setSpacing(2)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.list_widget.currentItemChanged.connect(self._on_selection_changed)
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.list_widget)

        # 搜索栏
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("搜索图像")
        self.search_bar.textChanged.connect(self._on_search_changed)
        layout.addWidget(self.search_bar)

        self.setWidget(container)

    def _on_top_level_changed(self, floating: bool):
        """悬浮时显示关闭按钮，停靠时隐藏关闭按钮"""
        if floating:
            self.setFeatures(
                QDockWidget.DockWidgetFeature.DockWidgetFloatable
                | QDockWidget.DockWidgetFeature.DockWidgetMovable
                | QDockWidget.DockWidgetFeature.DockWidgetClosable
            )
        else:
            self.setFeatures(
                QDockWidget.DockWidgetFeature.DockWidgetFloatable | QDockWidget.DockWidgetFeature.DockWidgetMovable
            )

    def closeEvent(self, event):
        """点击悬浮窗关闭按钮时归位至停靠区域，而非隐藏"""
        self.setFloating(False)
        event.ignore()

    def add_image(self, file_path: str):
        """将单个 WSI 文件路径加入列表（自动去重）。"""
        self.add_images([file_path])

    def add_images(self, paths: list):
        """批量添加多个 WSI 文件路径到列表（自动去重），统一触发一次缩略图加载。"""
        added = False
        first_new = None  # 记录第一个真正新增的路径，用于预取
        for file_path in paths:
            abs_path = os.path.abspath(file_path)
            if abs_path in self._entries:
                continue

            self._entries.append(abs_path)

            item = QListWidgetItem(os.path.basename(abs_path))
            item.setData(Qt.ItemDataRole.UserRole, str(abs_path))
            if not os.path.exists(str(abs_path)):
                item.setToolTip("文件不存在")
            self.list_widget.addItem(item)

            if first_new is None:
                first_new = abs_path
            added = True

        if added:
            self._restart_thumb_worker()
            # 预热第一个新增切片，减少首次加载的 I/O 等待
            if first_new and os.path.exists(first_new):
                from PySide6.QtCore import QThreadPool
                from wsi_analyzer.workers import PreloadTask

                QThreadPool.globalInstance().start(PreloadTask(first_new), -1)

    def highlight(self, file_path: str):
        """在列表中高亮显示指定路径对应的项。"""
        abs_path = os.path.abspath(file_path)
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == abs_path:
                self.list_widget.setCurrentItem(item)
                return

    def preload_adjacent(self, file_path: str) -> None:
        """预热列表中当前切片的前后相邻项（利用加载完成后的 I/O 空闲期）。"""
        abs_path = os.path.abspath(file_path)
        if abs_path not in self._entries:
            return
        idx = self._entries.index(abs_path)
        candidates = []
        if idx > 0:
            candidates.append(self._entries[idx - 1])
        if idx < len(self._entries) - 1:
            candidates.append(self._entries[idx + 1])

        from PySide6.QtCore import QThreadPool
        from wsi_analyzer.workers import PreloadTask

        for path in candidates:
            if os.path.exists(path):
                QThreadPool.globalInstance().start(PreloadTask(path), -1)

    @staticmethod
    def _on_selection_changed(current, _previous):
        """单击或键盘切换选中项时，后台预热引擎（消除首帧延迟）。"""
        if current is None:
            return
        item_path = str(current.data(Qt.ItemDataRole.UserRole))
        if item_path and os.path.exists(item_path):
            from PySide6.QtCore import QThreadPool
            from wsi_analyzer.workers import PreloadTask

            QThreadPool.globalInstance().start(PreloadTask(item_path), -1)

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
        """双击时校验文件存在性后立即发射加载请求。

        快速连续切换时，若当前正在加载则记录最后点击的路径，
        待当前加载完成后自动加载最新请求，避免 OpenSlide C 层并发崩溃。
        """
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and os.path.exists(path):
            self._pending_load_path = path
            if not self._loading:
                self._start_load()
        else:
            QMessageBox.warning(self, "文件不存在", f"无法找到文件：\n{path}")

    def _start_load(self):
        """发射加载信号；先调度 _loading 重置再 emit，防止异常导致标志位死锁。"""
        if not self._pending_load_path:
            return
        self._loading = True
        path = self._pending_load_path
        self._pending_load_path = None
        QTimer.singleShot(0, self._on_load_finished)
        self.image_load_requested.emit(path)

    def _on_load_finished(self):
        """当前加载在事件循环中完成后，检查是否有新的待处理请求。"""
        self._loading = False
        if self._pending_load_path:
            self._start_load()

    def _on_context_menu(self, pos: QPoint):
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
        path = item.data(Qt.ItemDataRole.UserRole)
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
            name = os.path.basename(item.data(Qt.ItemDataRole.UserRole)).lower()
            item.setHidden(lower not in name)
