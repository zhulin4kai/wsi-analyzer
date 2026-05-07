from PySide6.QtCore import Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QMainWindow,
    QMessageBox,
)

from core import ImageServer
from gui.controllers import HudController, MinimapController
from gui.layers.layer_manager import LayerManager
from gui.main_menu import MainMenuBuilder
from gui.mixins import AnalysisMixin, FileHandlingMixin
from gui.widgets import (
    ImageListPanel,
    LesionGallery,
    ReportExporter,
    WSIView,
)
from utils.wsi_file_utils import extract_wsi_paths_from_mime


class MainWindow(AnalysisMixin, FileHandlingMixin, QMainWindow):
    """主窗口容器"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("智能 WSI 病理切片辅助诊断系统 - WSIAnalyzer")
        self.resize(1440, 900)
        self.setAcceptDrops(True)

        # 状态记录
        self.current_wsi_path = None
        self.current_model_path = None
        self._was_ai_visible = True
        self.current_ai_results = []
        self.current_imported_annotations = []

        # 1. 初始化中心视图 WSIView
        self.viewer = WSIView(self)
        self.setCentralWidget(self.viewer)

        # 2. 初始化图层（Z-index 由低到高：底图[-1] → 瓦片[1~N] → 热力图[500] → 预测框[600] → ROI[1000]）
        self.layers = LayerManager(self.viewer.scene_canvas)
        self.heatmap_layer_item = self.layers.heatmap_layer_item
        self.ai_layer_group = self.layers.ai_layer_group
        self.imported_layer_group = self.layers.imported_layer_group

        # 3. 初始化所有 UI 面板
        self._init_ai_ui()
        self._init_heatmap_ui()
        self._init_minimap()
        self._init_hud()
        self._init_gallery_ui()
        self._init_image_list()
        MainMenuBuilder(self).build()

        # 4. 绑定信号
        self.viewer.interaction_started.connect(self._on_interaction_start)
        self.viewer.interaction_finished.connect(self._on_interaction_finish)
        self.viewer.roi_drawn.connect(self.start_roi_analysis)
        self.viewer.wsi_loaded.connect(self._on_wsi_loaded)

    def _init_minimap(self):
        self.minimap_controller = MinimapController(self.viewer, self)
        self.minimap_controller.setup()
        self.minimap = self.minimap_controller.minimap

    def _init_hud(self):
        self.hud = HudController(self.viewer, self.mag_widget)
        self.hud.bind()

    def open_settings(self):
        from PySide6.QtWidgets import QDialog

        from gui.dialogs import SettingsDialog

        dlg = SettingsDialog(self, current_wsi_path=self.current_wsi_path)
        if dlg.exec() == QDialog.Accepted:
            dlg.apply_settings()
            QMessageBox.information(self, "设置成功", "设置已保存。")

    def closeEvent(self, event):
        ImageServer.instance().shutdown()
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "hud"):
            self.hud.reposition()

    def _on_wsi_loaded(self, metadata):
        self.hud.on_wsi_loaded(metadata)

        # 预热相邻切片（利用加载完成后的 I/O 空闲期）
        if hasattr(self, "image_list_panel"):
            self.image_list_panel.preload_adjacent(metadata.path)

    def export_report(self, fmt="csv"):
        ReportExporter.export(
            self, self.current_wsi_path, self.current_ai_results, export_format=fmt
        )

    def _init_image_list(self):
        self.image_list_panel = ImageListPanel(self)
        self.image_list_panel.image_load_requested.connect(self._load_wsi_at_path)
        self.image_list_panel.add_requested.connect(self.add_images_to_list)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.image_list_panel)

    def _init_gallery_ui(self):
        self.gallery = LesionGallery(parent=self)
        self.gallery.navigate_requested.connect(self._navigate_to_lesion)
        self.gallery.hide()
        self.addDockWidget(Qt.RightDockWidgetArea, self.gallery)

    def _navigate_to_lesion(self, cx, cy):
        self.viewer.focus_on(cx, cy, target_scale=1.0)

    # ==================== Drag and Drop ====================

    def dragEnterEvent(self, event: QDragEnterEvent):
        paths = extract_wsi_paths_from_mime(event.mimeData())
        if paths:
            event.acceptProposedAction()
            self.viewer.set_drag_overlay(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.viewer.set_drag_overlay(False)

    def dropEvent(self, event: QDropEvent):
        self.viewer.set_drag_overlay(False)
        paths = extract_wsi_paths_from_mime(event.mimeData())
        if not paths:
            return

        event.acceptProposedAction()
        if hasattr(self, "image_list_panel"):
            self.image_list_panel.add_images(paths)
        if paths:
            self._load_wsi_at_path(paths[0])
