import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QLabel,
    QMenu,
    QPushButton,
    QToolBar,
)

from gui.widgets.magnification_widget import MagnificationWidget
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

        # 1. 开始分析按钮
        self.btn_analyze = QPushButton("开始全片检测")
        self.btn_analyze.setMinimumHeight(35)
        self.btn_analyze.clicked.connect(self.start_ai_analysis)
        toolbar.addWidget(self.btn_analyze)

        # 1.5 框选 ROI 分析按钮
        self.btn_roi_analyze = QPushButton("框选 ROI 分析")
        self.btn_roi_analyze.setCheckable(True)
        self.btn_roi_analyze.setMinimumHeight(35)
        self.btn_roi_analyze.toggled.connect(self.toggle_roi_mode)
        toolbar.addWidget(self.btn_roi_analyze)

        toolbar.addSeparator()

        # 2. 选择模型按钮
        self.btn_sel_model = QPushButton("选择模型权重")
        self.btn_sel_model.setMinimumHeight(35)
        self.btn_sel_model.clicked.connect(self.select_model)
        toolbar.addWidget(self.btn_sel_model)

        self.lbl_model = QLabel(" 当前模型: 未选择 ")
        toolbar.addWidget(self.lbl_model)
        toolbar.addSeparator()

        # 3. 显隐控制
        self.chk_show_ai = QCheckBox("显示预测框")
        self.chk_show_ai.setChecked(True)
        self.chk_show_ai.stateChanged.connect(self.toggle_ai_visibility)
        toolbar.addWidget(self.chk_show_ai)

        # 4. 导出按钮
        toolbar.addSeparator()
        self.btn_export = QPushButton("导出诊断报告")
        self.btn_export.setMinimumHeight(35)
        self.btn_export.setEnabled(False)

        # 创建导出格式下拉菜单
        export_menu = QMenu(self.btn_export)
        action_csv = export_menu.addAction("导出为 CSV")
        action_csv.triggered.connect(lambda: self.export_report("csv"))
        action_json = export_menu.addAction("导出为 JSON")
        action_json.triggered.connect(lambda: self.export_report("json"))
        action_geojson = export_menu.addAction("导出为 GeoJSON (QuPath)")
        action_geojson.triggered.connect(lambda: self.export_report("geojson"))
        self.btn_export.setMenu(export_menu)

        toolbar.addWidget(self.btn_export)

        # 保存工具栏引用，供 HeatmapMixin._init_heatmap_ui() 追加控件使用
        self._ai_toolbar = toolbar

        # 用于存储当前切片的最新分析结果
        self.current_ai_results = []
        self.ai_thread = None

    def select_model(self):
        """打开文件对话框选择模型权重，并根据模型信息执行智能调优。"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择 AI 模型", "", "Model Files (*.pt *.onnx *.pth)"
        )
        if not file_path:
            return

        self.current_model_path = file_path
        self.lbl_model.setText(f" 当前模型: {os.path.basename(file_path)} ")

        db = DatabaseManager()

        # 智能调优：从模型元数据中读取推荐 patch size
        if db.get_auto_tune_enabled() and file_path.endswith(".pt"):
            self._auto_tune_from_yolo(file_path, db)
        elif db.get_auto_tune_enabled() and file_path.endswith(".onnx"):
            self._auto_tune_from_onnx(file_path, db)

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
        except Exception:
            pass

    def _auto_tune_from_onnx(self, file_path: str, db: DatabaseManager):
        """从 ONNX 模型输入形状读取推荐 patch size 并写入设置。"""
        try:
            import onnxruntime as ort

            session = ort.InferenceSession(
                file_path, providers=["CPUExecutionProvider"]
            )
            input_shape = session.get_inputs()[0].shape
            if len(input_shape) >= 4 and isinstance(input_shape[2], int):
                db.set_setting("ai_patch_size", input_shape[2])
                self.statusBar().showMessage(
                    f"智能调优: 已根据 ONNX 模型设置 Patch Size = {input_shape[2]}"
                )
        except Exception:
            pass

    def _update_profile_for_model(self, file_path: str, db: DatabaseManager):
        """根据模型体积重新计算最优 batch size 并持久化到硬件画像。"""
        from utils.hardware_profiler import HardwareProfiler

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
