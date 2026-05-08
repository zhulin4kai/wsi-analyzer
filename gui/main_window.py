import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolBar,
)

from core import ImageServer
from gui.controllers import (
    AnalysisController,
    AnalysisResultController,
    HeatmapController,
    HudController,
    MinimapController,
    SlideController,
)
from gui.layers.layer_manager import LayerManager
from gui.main_menu import MainMenuBuilder
from gui.widgets import (
    ImageListPanel,
    LesionGallery,
    MagnificationWidget,
    ReportExporter,
    WSIView,
)
from wsi_analyzer.shared.wsi_file_utils import extract_wsi_paths_from_mime


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
        self.heatmap_layer_item = self.layers.heatmap_layer_item
        self.ai_layer_group = self.layers.ai_layer_group
        self.imported_layer_group = self.layers.imported_layer_group

        # ── 2. Widgets ─────────────────────────────────────────────
        self._init_toolbar()
        self._init_dock_widgets()

        # ── 3. Controllers ─────────────────────────────────────────
        self.minimap_controller = MinimapController(self.viewer, self)
        self.minimap_controller.setup()
        self.minimap = self.minimap_controller.minimap

        self.hud = HudController(self.viewer, self.mag_widget)
        self.hud.bind()

        self.slide_controller = SlideController(
            self, self.viewer, self.minimap, self.image_list_panel
        )

        self.analysis_controller = AnalysisController(
            self, self.viewer, self.slide_controller
        )

        self.result_controller = AnalysisResultController(
            self, self.viewer, self.layers,
            self.gallery, self.btn_export, self.chk_show_ai,
        )

        self.heatmap_controller = HeatmapController(
            self, self.viewer, self.layers, self.minimap,
            self._ai_toolbar, self.export_separator,
        )
        self.heatmap_controller.setup_ui()

        # ── 4. Menu ────────────────────────────────────────────────
        MainMenuBuilder(self).build()

        # ── 5. Signals ─────────────────────────────────────────────
        self.viewer.interaction_started.connect(
            self.result_controller.on_interaction_start
        )
        self.viewer.interaction_finished.connect(
            self.result_controller.on_interaction_finish
        )
        self.viewer.roi_drawn.connect(self.analysis_controller.start_roi_analysis)
        self.viewer.wsi_loaded.connect(self._on_wsi_loaded)

        # cross-controller delegation methods (kept as thin adapters)
        self._close_progress_dialog = self.analysis_controller._close_progress_dialog
        self._commit_results = self.result_controller._commit_results
        self._update_heatmap_layer = self.heatmap_controller._update_heatmap_layer
        self._clear_heatmap = self.heatmap_controller._clear_heatmap
        self._clear_imported_layer = self.result_controller._clear_imported_layer
        self.render_ai_results = self.result_controller.render_ai_results

    # ── Toolbar (inline UI builder) ────────────────────────────────

    def _init_toolbar(self):
        toolbar = QToolBar("AI 辅助分析")
        self.addToolBar(Qt.TopToolBarArea, toolbar)

        # magnification
        self.mag_widget = MagnificationWidget()
        toolbar.addWidget(self.mag_widget)
        toolbar.addSeparator()

        # model selector
        self.btn_sel_model = QAction("选择模型: 未选择", self)
        self.btn_sel_model.triggered.connect(self.select_model)
        toolbar.addAction(self.btn_sel_model)
        toolbar.addSeparator()

        # core actions
        self.btn_analyze = QAction("▶ 全片检测", self)
        self.btn_analyze.triggered.connect(self.analysis_controller.start_ai_analysis)
        toolbar.addAction(self.btn_analyze)

        self.btn_roi_analyze = QAction("ROI 分析", self)
        self.btn_roi_analyze.setCheckable(True)
        self.btn_roi_analyze.toggled.connect(self.analysis_controller.toggle_roi_mode)
        toolbar.addAction(self.btn_roi_analyze)

        toolbar.addSeparator()

        # view toggles
        self.chk_show_ai = QAction("预测框", self)
        self.chk_show_ai.setCheckable(True)
        self.chk_show_ai.setChecked(True)
        self.chk_show_ai.toggled.connect(self.result_controller.toggle_ai_visibility)
        toolbar.addAction(self.chk_show_ai)

        self.export_separator = toolbar.addSeparator()

        # export button
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

    # ── Model selection ────────────────────────────────────────────

    def select_model(self):
        from wsi_analyzer.infrastructure.persistence.database import DatabaseManager

        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择 AI 模型", "", "Model Files (*.pt *.pth)"
        )
        if not file_path:
            return

        self.current_model_path = file_path
        self.btn_sel_model.setText(f"模型: {os.path.basename(file_path)}")

        db = DatabaseManager()
        if db.get_auto_tune_enabled() and file_path.endswith(".pt"):
            self._auto_tune_from_yolo(file_path, db)
        if self.current_wsi_path:
            self._update_profile_for_model(file_path, db)

    def _auto_tune_from_yolo(self, file_path: str, db):
        try:
            from ultralytics import YOLO
            model = YOLO(file_path)
            imgsz = model.model.args.get("imgsz")
            if isinstance(imgsz, int):
                db.set_setting("ai_patch_size", imgsz)
                self.statusBar().showMessage(
                    f"智能调优: 已根据 YOLO 模型设置 Patch Size = {imgsz}"
                )
        except ImportError:
            self.statusBar().showMessage(
                "提示: 当前环境未安装 ultralytics，无法从 .pt 文件读取模型参数。"
            )
        except Exception:
            pass

    def _update_profile_for_model(self, file_path: str, db):
        from wsi_analyzer.infrastructure.hardware.profiler import HardwareProfiler

        drive_prefix = HardwareProfiler.get_storage_key(self.current_wsi_path)
        profile = db.get_system_profile(drive_prefix)
        if not (profile and "io_speed" in profile):
            return

        model_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        device = profile.get("device", HardwareProfiler.get_compute_device())
        _, free_vram = HardwareProfiler.get_vram_info(device)
        new_params = HardwareProfiler.calculate_optimal_params(
            profile["io_speed"], free_vram, model_size_mb
        )
        profile["batch_size"] = new_params["batch_size"]
        profile["tile_cache_limit"] = new_params["tile_cache_limit"]
        db.save_system_profile(drive_prefix, profile)

        self.statusBar().showMessage(
            f"模型已切换: {os.path.basename(file_path)} | "
            f"模型大小: {model_size_mb:.1f}MB | "
            f"自动调整 Batch Size 至: {new_params['batch_size']}"
        )

    # ── Dock widgets ───────────────────────────────────────────────

    def _init_dock_widgets(self):
        self.image_list_panel = ImageListPanel(self)
        self.image_list_panel.image_load_requested.connect(
            self.slide_controller._load_wsi_at_path
        )
        self.image_list_panel.add_requested.connect(
            self.slide_controller.add_images_to_list
        )
        self.addDockWidget(Qt.LeftDockWidgetArea, self.image_list_panel)

        self.gallery = LesionGallery(parent=self)
        self.gallery.navigate_requested.connect(self._navigate_to_lesion)
        self.gallery.hide()
        self.addDockWidget(Qt.RightDockWidgetArea, self.gallery)

    # ── Event handlers ─────────────────────────────────────────────

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
            self.slide_controller._load_wsi_at_path(paths[0])
