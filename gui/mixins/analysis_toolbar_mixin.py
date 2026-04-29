import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFileDialog,
    QMenu,
    QPushButton,
    QToolBar,
)

from gui.widgets import MagnificationWidget
from utils import DatabaseManager


class AnalysisToolbarMixin:
    """AI 工具栏构建与模型选择/自动调优逻辑。"""

    def _init_ai_ui(self):
        """初始化顶部工具栏"""
        toolbar = QToolBar("AI 辅助分析")
        self.addToolBar(Qt.TopToolBarArea, toolbar)

        # 0. 放大倍率显示/输入控件（视图导航区）
        self.mag_widget = MagnificationWidget()
        toolbar.addWidget(self.mag_widget)
        toolbar.addSeparator()

        # 1. 模型配置
        self.btn_sel_model = QAction("选择模型: 未选择", self)
        self.btn_sel_model.triggered.connect(self.select_model)
        toolbar.addAction(self.btn_sel_model)
        toolbar.addSeparator()

        # 2. 核心操作
        self.btn_analyze = QAction("▶ 全片检测", self)
        self.btn_analyze.triggered.connect(self.start_ai_analysis)
        toolbar.addAction(self.btn_analyze)

        self.btn_roi_analyze = QAction("ROI 分析", self)
        self.btn_roi_analyze.setCheckable(True)
        self.btn_roi_analyze.toggled.connect(self.toggle_roi_mode)
        toolbar.addAction(self.btn_roi_analyze)

        toolbar.addSeparator()

        # 3. 可视化控制
        self.chk_show_ai = QAction("预测框", self)
        self.chk_show_ai.setCheckable(True)
        self.chk_show_ai.setChecked(True)
        self.chk_show_ai.toggled.connect(self.toggle_ai_visibility)
        toolbar.addAction(self.chk_show_ai)

        # 4. 导出按钮
        self.export_separator = toolbar.addSeparator()
        self.btn_export = QPushButton("导出报告 ▾")
        self.btn_export.setEnabled(False)

        # 创建导出格式下拉菜单
        self.export_menu = QMenu(self.btn_export)
        action_csv = self.export_menu.addAction("导出为 CSV")
        action_csv.triggered.connect(lambda: self.export_report("csv"))
        action_json = self.export_menu.addAction("导出为 JSON")
        action_json.triggered.connect(lambda: self.export_report("json"))
        action_geojson = self.export_menu.addAction("导出为 GeoJSON (QuPath)")
        action_geojson.triggered.connect(lambda: self.export_report("geojson"))

        self.btn_export.clicked.connect(
            lambda: self.export_menu.exec(
                self.btn_export.mapToGlobal(self.btn_export.rect().bottomLeft())
            )
        )

        self.export_action = toolbar.addWidget(self.btn_export)

        # 保存工具栏引用，供 HeatmapMixin._init_heatmap_ui() 追加控件使用
        self._ai_toolbar = toolbar

        # 用于存储当前切片的最新分析结果
        self.current_ai_results = []
        self.ai_thread = None

    def select_model(self):
        """打开文件对话框选择模型权重，并根据模型信息执行智能调优。"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择 AI 模型", "", "Model Files (*.pt *.pth)"
        )
        if not file_path:
            return

        self.current_model_path = file_path
        self.btn_sel_model.setText(f"模型: {os.path.basename(file_path)}")

        db = DatabaseManager()

        # 从模型元数据中读取推荐 patch size
        if db.get_auto_tune_enabled() and file_path.endswith(".pt"):
            self._auto_tune_from_yolo(file_path, db)

        # 模型体积动态变化时重新计算最优 batch size
        if self.current_wsi_path:
            self._update_profile_for_model(file_path, db)

    def _auto_tune_from_yolo(self, file_path: str, db: DatabaseManager):
        """从 YOLO 模型元数据读取推荐 imgsz 并写入设置。"""
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

    def _update_profile_for_model(self, file_path: str, db: DatabaseManager):
        """根据模型体积重新计算最优 batch size 并持久化到硬件画像。"""
        from utils import HardwareProfiler

        drive_prefix = os.path.splitdrive(os.path.abspath(self.current_wsi_path))[0]
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
