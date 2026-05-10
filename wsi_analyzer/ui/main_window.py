from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolBar,
)


from wsi_analyzer.ui.controllers import (
    AnalysisController,
    AnalysisResultController,
    HeatmapController,
    HudController,
    MinimapController,
    ModelController,
    SlideController,
)
from wsi_analyzer.ui.layers import LayerManager
from wsi_analyzer.ui.main_menu import MainMenuBuilder
from wsi_analyzer.ui.widgets import (
    ImageListPanel,
    LesionGallery,
    MagnificationWidget,
    ReportExporter,
    WSIView,
)
from wsi_analyzer.shared import extract_wsi_paths_from_mime


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("智能 WSI 病理切片辅助诊断系统 - WSIAnalyzer")
        self.resize(1440, 900)
        self.setAcceptDrops(True)

        # ── shared state ───────────────────────────────────────────
        self.current_wsi_path = None
        self.current_model_path = None
        self.current_ai_results = []
        self.current_imported_annotations = []

        # ── 1. View + Layers ───────────────────────────────────────
        self.viewer = WSIView(self)
        self.setCentralWidget(self.viewer)

        self.layers = LayerManager(self.viewer.scene_canvas)

        # ── 2. Dock widgets ───────────────────────────────────────
        self._init_dock_widgets()

        # ── 3. Toolbar widgets (no controller signals yet) ──────────
        self._init_toolbar_widgets()

        # ── 4. Controllers ─────────────────────────────────────────
        self.minimap_controller = MinimapController(self.viewer, self)
        self.minimap_controller.setup()
        self.minimap = self.minimap_controller.minimap

        self.slide_controller = SlideController(
            self, self.viewer, self.minimap, self.image_list_panel
        )

        self.result_controller = AnalysisResultController(
            self, self.viewer, self.layers,
            self.gallery, self.btn_export, self.chk_show_ai,
        )

        self.analysis_controller = AnalysisController(
            self, self.viewer, self.slide_controller, self.result_controller
        )

        self.model_controller = ModelController(self)

        # ── 5. Connect signals (controllers now exist) ──────────────
        self._connect_toolbar_signals()
        self._connect_dock_signals()

        # ── 6. HUD + Heatmap (need mag_widget from toolbar) ─────────
        self.hud = HudController(self.viewer, self.mag_widget)
        self.hud.bind()

        self.heatmap_controller = HeatmapController(
            self, self.viewer, self.layers, self.minimap,
            self._ai_toolbar, self.export_separator,
        )
        self.heatmap_controller.setup_ui()

        # ── 7. Menu ────────────────────────────────────────────────
        MainMenuBuilder(self).build()

        # ── 8. Signals ─────────────────────────────────────────────
        self.viewer.interaction_started.connect(
            self.result_controller.on_interaction_start
        )
        self.viewer.interaction_finished.connect(
            self.result_controller.on_interaction_finish
        )
        self.viewer.roi_drawn.connect(self.analysis_controller.start_roi_analysis)
        self.viewer.wsi_loaded.connect(self._on_wsi_loaded)

        # cross-controller delegation methods (kept as thin adapters)

    # ── Toolbar (inline UI builder) ────────────────────────────────

    def _init_dock_widgets(self):
        self.image_list_panel = ImageListPanel(self)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.image_list_panel)

        self.gallery = LesionGallery(self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.gallery)

    def _connect_dock_signals(self):
        self.image_list_panel.image_load_requested.connect(
            self.slide_controller.load_wsi_at_path
        )
        self.image_list_panel.add_requested.connect(
            self.slide_controller.add_images_to_list
        )
        self.gallery.navigate_requested.connect(self._navigate_to_lesion)

    def _init_toolbar_widgets(self):
        toolbar = QToolBar("AI 辅助分析")
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

        self.mag_widget = MagnificationWidget()
        toolbar.addWidget(self.mag_widget)
        toolbar.addSeparator()

        self.btn_sel_model = QAction("选择模型: 未选择", self)
        toolbar.addAction(self.btn_sel_model)
        toolbar.addSeparator()

        self.btn_analyze = QAction("▶ 全片检测", self)
        toolbar.addAction(self.btn_analyze)

        self.btn_roi_analyze = QAction("ROI 分析", self)
        self.btn_roi_analyze.setCheckable(True)
        toolbar.addAction(self.btn_roi_analyze)

        toolbar.addSeparator()

        self.chk_show_ai = QAction("预测框", self)
        self.chk_show_ai.setCheckable(True)
        self.chk_show_ai.setChecked(True)
        toolbar.addAction(self.chk_show_ai)

        self.export_separator = toolbar.addSeparator()

        self.btn_export = QPushButton("导出报告 ▾")
        self.btn_export.setEnabled(False)
        self.export_menu = QMenu(self.btn_export)
        self.export_menu.addAction("导出为 CSV").triggered.connect(
            lambda: self.export_report("csv")
        )
        self.export_menu.addAction("导出为 JSON").triggered.connect(
            lambda: self.export_report("json")
        )
        self.export_menu.addAction("导出为 GeoJSON (QuPath)").triggered.connect(
            lambda: self.export_report("geojson")
        )
        self.btn_export.clicked.connect(
            lambda: self.export_menu.exec(
                self.btn_export.mapToGlobal(self.btn_export.rect().bottomLeft())
            )
        )
        toolbar.addWidget(self.btn_export)

        self._ai_toolbar = toolbar

    def _connect_toolbar_signals(self):
        self.btn_sel_model.triggered.connect(self.model_controller.select_model)
        self.btn_analyze.triggered.connect(self.analysis_controller.start_ai_analysis)
        self.btn_roi_analyze.toggled.connect(self.analysis_controller.toggle_roi_mode)
        self.chk_show_ai.toggled.connect(self.result_controller.toggle_ai_visibility)

    # ── Event handlers ─────────────────────────────────────────────

    def open_settings(self):
        from PySide6.QtWidgets import QDialog
        from wsi_analyzer.ui.dialogs import SettingsDialog

        dlg = SettingsDialog(self, current_wsi_path=self.current_wsi_path)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            dlg.apply_settings()
            QMessageBox.information(self, "设置成功", "设置已保存。")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "hud"):
            self.hud.reposition()

    def _on_wsi_loaded(self, metadata):
        self.hud.on_wsi_loaded(metadata)
        if hasattr(self, "image_list_panel"):
            self.image_list_panel.preload_adjacent(metadata.path)

    def _navigate_to_lesion(self, cx, cy):
        self.viewer.focus_on(cx, cy, target_scale=1.0)

    def export_report(self, fmt="csv"):
        ReportExporter.export(
            self, self.current_wsi_path, self.current_ai_results, export_format=fmt
        )

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
            self.slide_controller.load_wsi_at_path(paths[0])
