import os

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QDockWidget,
    QFileDialog,
    QGraphicsDropShadowEffect,
    QGraphicsItemGroup,
    QGraphicsRectItem,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QToolBar,
    QVBoxLayout,
)

from config import AI_PEN_COLOR, AI_PEN_WIDTH
from gui.widgets import LesionGallery, MinimapView, ReportExporter, WSIView
from utils import DatabaseManager
from workers import AIAnalysisWorker


class MainWindow(QMainWindow):
    """主窗口容器"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("智能 WSI 病理切片辅助诊断系统 - WSIAnalyzer")
        self.resize(1440, 900)

        # 状态记录
        self.current_wsi_path = None
        self.current_model_path = None
        self._was_ai_visible = True
        self.current_ai_results = []

        # 1. 初始化中心视图 WSIView
        self.viewer = WSIView(self)
        self.setCentralWidget(self.viewer)

        # 2. 初始化图层
        self.ai_layer_group = QGraphicsItemGroup()
        self.viewer.scene_canvas.addItem(self.ai_layer_group)

        # 3. 初始化所有 UI 面板
        self._init_menu()
        self._init_ai_ui()
        self._init_minimap_overlay()
        self._init_gallery_ui()

        # 4. 绑定信号
        self.viewer.interaction_started.connect(self._on_interaction_start)
        self.viewer.interaction_finished.connect(self._on_interaction_finish)

    def _init_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("文件")
        open_action = file_menu.addAction("打开 WSI 文件")
        open_action.setShortcut("Ctrl + O")
        open_action.triggered.connect(self.open_file)

        file_menu.addSeparator()
        recent_menu = file_menu.addMenu("最近打开的文件")
        recent_menu.setEnabled(False)
        file_menu.addSeparator()
        self.settings_action = file_menu.addAction("系统设置")
        self.settings_action.triggered.connect(self.open_settings)
        exit_action = file_menu.addAction("退出系统")
        exit_action.setShortcut("Ctrl + Q")
        exit_action.triggered.connect(self.close)

        view_menu = menubar.addMenu("视图")
        reset_view = view_menu.addAction("重置视图")
        reset_view.setShortcut("Ctrl + R")
        reset_view.triggered.connect(lambda: self.viewer.resetTransform())

        help_menu = menubar.addMenu("帮助")
        about_action = help_menu.addAction("关于系统")
        about_action.triggered.connect(
            lambda: QMessageBox.about(
                self, "关于", "基于 YOLOv8 的智能 WSI 病理切片辅助诊断系统"
            )
        )

    def open_settings(self):
        """打开系统设置面板，调整数据库容量限制及硬件加速配置"""
        from PySide6.QtWidgets import (
            QDialog,
            QDoubleSpinBox,
            QFormLayout,
            QLabel,
            QPushButton,
            QSpinBox,
            QTabWidget,
            QVBoxLayout,
            QWidget,
        )

        db = DatabaseManager()
        current_capacity = db.get_max_capacity()

        dialog = QDialog(self)
        dialog.setWindowTitle("系统设置")
        dialog.resize(400, 300)

        layout = QVBoxLayout(dialog)
        tabs = QTabWidget()

        # 基本设置 Tab
        tab_basic = QWidget()
        layout_basic = QFormLayout(tab_basic)
        import config

        spin_capacity = QSpinBox()
        spin_capacity.setRange(getattr(config, "DB_MIN_CAPACITY_MB", 50), 10000)
        spin_capacity.setSingleStep(50)
        spin_capacity.setValue(current_capacity)
        layout_basic.addRow("数据库最大容量 (MB):", spin_capacity)
        tabs.addTab(tab_basic, "基本设置")

        # 性能与硬件加速 Tab
        tab_perf = QWidget()
        layout_perf = QFormLayout(tab_perf)

        drive_prefix = ""
        if self.current_wsi_path:
            drive_prefix = os.path.splitdrive(os.path.abspath(self.current_wsi_path))[0]

        profile = db.get_system_profile(drive_prefix) if drive_prefix else None

        lbl_device = QLabel(profile.get("device", "未知") if profile else "未知")
        lbl_io_speed = QLabel(
            f"{profile.get('io_speed', 0):.2f} MB/s ({profile.get('io_rating', '未知')})"
            if profile
            else "未知"
        )

        spin_batch = QSpinBox()
        spin_batch.setRange(1, getattr(config, "BATCH_SIZE_CAP_NVME_SSD", 256))
        spin_batch.setValue(profile.get("batch_size", 16) if profile else 16)

        layout_perf.addRow("计算设备:", lbl_device)
        layout_perf.addRow(
            "当前盘符:", QLabel(drive_prefix if drive_prefix else "未加载文件")
        )
        layout_perf.addRow("当前 I/O 速度:", lbl_io_speed)
        layout_perf.addRow("Batch Size (可手动覆盖):", spin_batch)

        tabs.addTab(tab_perf, "性能与硬件加速")

        # AI 参数设置 Tab
        tab_ai = QWidget()
        layout_ai = QFormLayout(tab_ai)

        spin_patch_size = QSpinBox()
        spin_patch_size.setRange(128, 4096)
        spin_patch_size.setSingleStep(128)
        spin_patch_size.setValue(
            db.get_setting("ai_patch_size", getattr(config, "AI_PATCH_SIZE", 512))
        )

        spin_stride = QSpinBox()
        spin_stride.setRange(64, 4096)
        spin_stride.setSingleStep(64)
        spin_stride.setValue(
            db.get_setting("ai_stride", getattr(config, "AI_STRIDE", 400))
        )

        spin_iou = QDoubleSpinBox()
        spin_iou.setRange(0.01, 1.0)
        spin_iou.setSingleStep(0.05)
        spin_iou.setValue(
            db.get_setting(
                "ai_nms_iou_thresh", getattr(config, "AI_NMS_IOU_THRESH", 0.25)
            )
        )

        spin_conf = QDoubleSpinBox()
        spin_conf.setRange(0.01, 1.0)
        spin_conf.setSingleStep(0.05)
        spin_conf.setValue(
            db.get_setting("ai_conf_thresh", getattr(config, "AI_CONF_THRESH", 0.5))
        )

        layout_ai.addRow("切片尺寸 (Patch Size):", spin_patch_size)
        layout_ai.addRow("滑动步长 (Stride):", spin_stride)
        layout_ai.addRow("NMS IOU 阈值:", spin_iou)
        layout_ai.addRow("置信度阈值 (Conf):", spin_conf)

        tabs.addTab(tab_ai, "AI 参数设置")

        layout.addWidget(tabs)

        def on_save_clicked():
            patch_size = spin_patch_size.value()
            stride = spin_stride.value()
            if stride > patch_size:
                from PySide6.QtWidgets import QMessageBox

                QMessageBox.warning(
                    dialog,
                    "参数警告",
                    f"滑动步长 ({stride}) 大于切片尺寸 ({patch_size})，这会导致在推断时漏掉部分区域！\n请重新设置（建议步长略小于切片尺寸以保证重叠覆盖率）。",
                )
                return
            dialog.accept()

        btn_save = QPushButton("保存")
        btn_save.clicked.connect(on_save_clicked)
        layout.addWidget(btn_save)

        if dialog.exec_() == QDialog.Accepted:
            new_capacity = spin_capacity.value()
            if new_capacity != current_capacity:
                db.set_max_capacity(new_capacity)

            if profile and drive_prefix:
                profile["batch_size"] = spin_batch.value()
                db.save_system_profile(drive_prefix, profile)

            # 获取并钳制安全边界，防止用户手动输入超限或奇怪的数值
            patch_size = max(
                getattr(config, "AI_PATCH_SIZE_MIN", 128),
                min(
                    spin_patch_size.value(), getattr(config, "AI_PATCH_SIZE_MAX", 4096)
                ),
            )
            stride = max(
                getattr(config, "AI_STRIDE_MIN", 64),
                min(spin_stride.value(), getattr(config, "AI_STRIDE_MAX", 4096)),
            )
            iou = max(
                getattr(config, "AI_NMS_IOU_THRESH_MIN", 0.01),
                min(spin_iou.value(), getattr(config, "AI_NMS_IOU_THRESH_MAX", 1.0)),
            )
            conf = max(
                getattr(config, "AI_CONF_THRESH_MIN", 0.01),
                min(spin_conf.value(), getattr(config, "AI_CONF_THRESH_MAX", 1.0)),
            )

            db.set_setting("ai_patch_size", patch_size)
            db.set_setting("ai_stride", stride)
            db.set_setting("ai_nms_iou_thresh", iou)
            db.set_setting("ai_conf_thresh", conf)

            QMessageBox.information(self, "设置成功", "设置已保存。")

    def resizeEvent(self, event):
        super().resizeEvent(event)

    def open_file(self):
        """重写父类的打开文件逻辑，以便拦截并记录当前的 SVS 绝对路径"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择病理切片", "", "WSI Files (*.svs *.tif *.ndpi)"
        )

        if file_path:
            # 状态安全重置
            # 切换切片前，务必清空上一张切片留下的 AI 预测框，防止空间坐标错位
            for item in self.ai_layer_group.childItems():
                self.ai_layer_group.removeFromGroup(item)
                self.viewer.scene_canvas.removeItem(item)
            self.current_ai_results = []
            if hasattr(self, "btn_export"):
                self.btn_export.setEnabled(False)  # 禁用导出按钮

            if hasattr(self, "gallery"):
                self.gallery.clear_gallery()

            self.current_wsi_path = file_path
            self.viewer.load_wsi(file_path)
            self.statusBar().showMessage(f"已加载: {os.path.basename(file_path)}")

            drive_prefix = os.path.splitdrive(os.path.abspath(file_path))[0]
            db = DatabaseManager()
            existing_profile = db.get_system_profile(drive_prefix)

            if existing_profile and "batch_size" in existing_profile:
                optimal_params = existing_profile
                io_speed = optimal_params.get("io_speed", 0.0)
            else:
                # 第一阶段：隐形 I/O 测速 (Invisible Benchmark)
                from core.slide_engine import WSIDataEngine
                from utils.hardware_profiler import HardwareProfiler

                def init_and_thumb(fp):
                    engine = WSIDataEngine(fp)
                    img, _ = engine.get_thumbnail()
                    # 估算像素体积 (bytes)
                    bytes_size = img.width * img.height * 3
                    engine.close()
                    return bytes_size

                io_speed = HardwareProfiler.measure_io_speed(file_path, init_and_thumb)

                device = HardwareProfiler.get_compute_device()
                _, free_vram = HardwareProfiler.get_vram_info(device)
                # 假设默认模型大小100MB，实际在切换模型时会重新计算
                optimal_params = HardwareProfiler.calculate_optimal_params(
                    io_speed, free_vram, 100.0
                )
                optimal_params["io_speed"] = io_speed

                db.save_system_profile(drive_prefix, optimal_params)

            if (
                hasattr(self.viewer, "tile_cache")
                and "tile_cache_limit" in optimal_params
            ):
                self.viewer.tile_cache.max_capacity = optimal_params["tile_cache_limit"]

            self.statusBar().showMessage(
                f"已加载: {os.path.basename(file_path)} | I/O: {io_speed:.2f} MB/s | Batch: {optimal_params['batch_size']}"
            )

            if hasattr(self.viewer, "slide_engine") and self.viewer.slide_engine:
                self.minimap.load_minimap(self.viewer.slide_engine)

            # 本地数据库静默读取
            cache_data = db.get_analysis(file_path)
            if cache_data and cache_data.get("status") == "completed":
                results = cache_data.get("results", [])
                reply = QMessageBox.question(
                    self,
                    "发现分析缓存",
                    "检测到该病理切片已有历史检测记录。\n是否直接加载本地缓存结果？",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if reply == QMessageBox.Yes:
                    self.render_ai_results({"results": results, "status": "completed"})
                    self.statusBar().showMessage(
                        f"已从本地数据库加载 {len(results)} 个病灶。"
                    )

    def render_ai_results(self, results_dict):
        """渲染预测结果"""
        if hasattr(self, "progress_dialog"):
            try:
                self.progress_dialog.canceled.disconnect(self.cancel_ai_analysis)
            except Exception:
                pass
            self.progress_dialog.close()

        results = results_dict.get("results", [])
        status = results_dict.get("status", "completed")
        valid_coords = results_dict.get("valid_coords", [])
        processed_patches = results_dict.get("processed_patches", 0)
        total_patches = results_dict.get("total_patches", 0)

        # 清空旧数据
        for item in self.ai_layer_group.childItems():
            self.ai_layer_group.removeFromGroup(item)
            self.viewer.scene_canvas.removeItem(item)

        # 遍历生成 QGraphicsRectItem
        for data in results:
            x_min, y_min, x_max, y_max = data["bbox"]
            rect_item = QGraphicsRectItem(
                QRectF(x_min, y_min, x_max - x_min, y_max - y_min)
            )

            # 化妆笔模式保证在全景缩小（Level 0 大尺寸）下依然可见
            pen = QPen(QColor(*AI_PEN_COLOR))
            pen.setWidth(AI_PEN_WIDTH)
            pen.setCosmetic(True)
            rect_item.setPen(pen)
            rect_item.setToolTip(f"微乳头状癌病灶\n置信度: {data['confidence']:.2%}")
            self.ai_layer_group.addToGroup(rect_item)

        # 保存结果并启用导出按钮
        self.ai_layer_group.setVisible(self.chk_show_ai.isChecked())
        self.current_ai_results = results
        self.btn_export.setEnabled(len(results) > 0)

        if self.current_wsi_path:
            db = DatabaseManager()
            db.save_analysis(
                file_path=self.current_wsi_path,
                model_path=self.current_model_path or "",
                status=status,
                total_patches=total_patches,
                processed_patches=processed_patches,
                results=results,
                valid_coords=valid_coords,
            )

        if status == "completed":
            QMessageBox.information(
                self, "分析完成", f"共标记 {len(results)} 处疑似病灶。"
            )
        else:
            QMessageBox.information(
                self, "分析已中止", f"进度已保存。当前标记 {len(results)} 处疑似病灶。"
            )

        # 开始生成画廊缩略图
        self.gallery.load_results(self.current_wsi_path, results)

    # LOD 动态视觉降级控制
    def _on_interaction_start(self):
        """
        槽函数：交互开始 (鼠标按下或滚轮初次滚动)
        动作：静默隐藏重度图层，释放 Qt C++ 底层的重绘压力。
        """
        # 记录隐藏前的真实意图（因为用户可能本来就把框关掉了）
        self._was_ai_visible = self.chk_show_ai.isChecked()

        # 强制隐藏包含成千上万个矩形的 AI 图层组
        self.ai_layer_group.setVisible(False)

    def _on_interaction_finish(self):
        """
        槽函数：交互结束 (防抖定时器结束，且高清切图渲染完毕)
        动作：根据记忆的状态，恢复图层显示。
        """
        # 只有在用户原本期望显示的情况下，才恢复画框
        if self._was_ai_visible:
            self.ai_layer_group.setVisible(True)

    def _init_ai_ui(self):
        """初始化顶部工具栏"""
        toolbar = QToolBar("AI 辅助分析")
        self.addToolBar(Qt.TopToolBarArea, toolbar)

        # 1. 开始分析按钮
        self.btn_analyze = QPushButton("开始全片检测")
        self.btn_analyze.setMinimumHeight(35)
        self.btn_analyze.clicked.connect(self.start_ai_analysis)
        toolbar.addWidget(self.btn_analyze)

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

        # 用于存储当前切片的最新分析结果
        self.current_ai_results = []

        self.ai_thread = None

    def select_model(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择 AI 模型", "", "Model Files (*.pt *.pth)"
        )
        if file_path:
            self.current_model_path = file_path
            self.lbl_model.setText(f" 当前模型: {os.path.basename(file_path)} ")

            # 风险 3：模型体积动态变化 (Model Switching Overhead)
            if self.current_wsi_path:
                from utils.hardware_profiler import HardwareProfiler

                db = DatabaseManager()
                drive_prefix = os.path.splitdrive(
                    os.path.abspath(self.current_wsi_path)
                )[0]
                profile = db.get_system_profile(drive_prefix)

                if profile and "io_speed" in profile:
                    model_size_mb = os.path.getsize(file_path) / (1024 * 1024)
                    device = profile.get(
                        "device", HardwareProfiler.get_compute_device()
                    )
                    _, free_vram = HardwareProfiler.get_vram_info(device)

                    new_params = HardwareProfiler.calculate_optimal_params(
                        profile["io_speed"], free_vram, model_size_mb
                    )

                    # 更新配置并持久化
                    profile["batch_size"] = new_params["batch_size"]
                    profile["tile_cache_limit"] = new_params["tile_cache_limit"]
                    db.save_system_profile(drive_prefix, profile)

                    self.statusBar().showMessage(
                        f"模型已切换: {os.path.basename(file_path)} | 模型大小: {model_size_mb:.1f}MB | 自动调整 Batch Size 至: {new_params['batch_size']}"
                    )

    def start_ai_analysis(self):
        """启动真实后台推断"""
        if not self.current_wsi_path:
            QMessageBox.warning(self, "警告", "请先通过'文件'菜单打开一个 WSI 切片！")
            return
        if not self.current_model_path or not os.path.exists(self.current_model_path):
            QMessageBox.warning(self, "警告", "请先选择有效的模型权重 (.pt) 文件！")
            return

        db = DatabaseManager()
        cache_data = db.get_analysis(self.current_wsi_path)
        resume_data = None

        if cache_data and cache_data.get("status") == "interrupted":
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("发现中断的分析")
            msg_box.setText(
                "检测到该病理切片有未完成的分析记录。\n是否继续上次的分析进度？\n选择'否'将重新开始。"
            )
            msg_box.setIcon(QMessageBox.Question)
            btn_yes = msg_box.addButton("是", QMessageBox.ActionRole)
            btn_no = msg_box.addButton("否", QMessageBox.ActionRole)
            msg_box.exec()

            if msg_box.clickedButton() == btn_yes:
                resume_data = cache_data
            else:
                db.delete_analysis(self.current_wsi_path)

        self.btn_analyze.setEnabled(False)
        self.settings_action.setEnabled(False)
        self.btn_export.setEnabled(False)

        self.progress_dialog = QProgressDialog(
            "正在进行全片 AI 检测...", "取消", 0, 100, self
        )
        self.progress_dialog.setWindowTitle("分析进度")
        self.progress_dialog.setWindowModality(Qt.NonModal)
        self.progress_dialog.setAutoClose(False)
        self.progress_dialog.setAutoReset(False)
        self.progress_dialog.setValue(0)
        self.progress_dialog.canceled.connect(self.cancel_ai_analysis)

        # 传入当前切片路径和模型路径，以及可能的断点数据
        self.ai_thread = AIAnalysisWorker(
            svs_path=self.current_wsi_path,
            model_path=self.current_model_path,
            resume_data=resume_data,
        )

        # 连接信号与槽
        self.ai_thread.progress_updated.connect(self.progress_dialog.setValue)
        self.ai_thread.status_updated.connect(self.statusBar().showMessage)
        self.ai_thread.analysis_finished.connect(self.render_ai_results)
        self.ai_thread.error_occurred.connect(self.handle_ai_error)
        self.ai_thread.finished.connect(lambda: self.btn_analyze.setEnabled(True))
        self.ai_thread.finished.connect(lambda: self.settings_action.setEnabled(True))

        self.progress_dialog.show()
        self.ai_thread.start()

    def cancel_ai_analysis(self):
        if getattr(self, "_is_canceling", False):
            return
        if (
            not hasattr(self, "ai_thread")
            or not self.ai_thread
            or not self.ai_thread.isRunning()
        ):
            return

        self._is_canceling = True

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("取消确认")
        msg_box.setText("确定要中断当前的 AI 分析吗？进度将被保存。")
        msg_box.setIcon(QMessageBox.Question)
        btn_yes = msg_box.addButton("是", QMessageBox.ActionRole)
        btn_no = msg_box.addButton("否", QMessageBox.ActionRole)
        msg_box.exec()

        if msg_box.clickedButton() == btn_yes:
            if self.ai_thread and self.ai_thread.isRunning():
                self.ai_thread.cancel()
        else:
            if hasattr(self, "progress_dialog"):
                # 重置进度条以清除内部的 wasCanceled 锁定状态
                current_val = self.progress_dialog.value()
                self.progress_dialog.reset()
                self.progress_dialog.setValue(current_val)
                # 延迟执行 show()，避开 QProgressDialog 在触发 close 事件后的自动隐藏机制
                from PySide6.QtCore import QTimer

                QTimer.singleShot(0, self.progress_dialog.show)

        self._is_canceling = False

    def handle_ai_error(self, err_msg):
        if hasattr(self, "progress_dialog"):
            try:
                self.progress_dialog.canceled.disconnect(self.cancel_ai_analysis)
            except Exception:
                pass
            self.progress_dialog.close()
        self.statusBar().showMessage("分析失败或被中断。")
        QMessageBox.critical(self, "AI 引擎错误", err_msg)

    def toggle_ai_visibility(self, state):
        self.ai_layer_group.setVisible(state == Qt.Checked)

    def _init_minimap_overlay(self):
        """初始化鹰眼图悬浮层"""
        self.minimap = MinimapView(self.viewer)
        # 尺寸现已由 MinimapView 根据切片比例动态接管计算

        # 阴影
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 100))
        shadow.setOffset(2, 2)
        self.minimap.setGraphicsEffect(shadow)

        # 右上角
        layout = QVBoxLayout(self.viewer)
        layout.setContentsMargins(0, 0, 0, 0)  # 上边距和右边距各留出 20px
        layout.addWidget(self.minimap, alignment=Qt.AlignTop | Qt.AlignRight)

        # 绑定双向联动信号
        self.viewer.view_rect_changed.connect(self.minimap.update_indicator)
        self.minimap.navigate_requested.connect(self.navigate_main_view)

    def navigate_main_view(self, cx, cy):
        """鹰眼图向主视图发送跳转请求时的槽函数"""
        self.viewer.centerOn(cx, cy)
        # 手动触发一次高分辨率渲染
        self.viewer._render_high_res_viewport()
        self.viewer._trigger_view_update()

    def export_report(self, fmt="csv"):
        """生成并导出结构化报告"""
        ReportExporter.export(
            self, self.current_wsi_path, self.current_ai_results, export_format=fmt
        )

    def _init_gallery_ui(self):
        """初始化右侧高危病灶画廊"""
        self.gallery = LesionGallery(parent=self)
        self.gallery.navigate_requested.connect(self._navigate_to_lesion)
        self.addDockWidget(Qt.RightDockWidgetArea, self.gallery)

    def _navigate_to_lesion(self, cx, cy):
        """接收画廊靶向信号，瞬间移动主视图到病灶中心并放大"""
        # 平移视图到病灶中心
        self.viewer.centerOn(cx, cy)

        # 尝试自动放大到一个较高的倍率以便看清细胞
        current_scale = self.viewer.transform().m11()
        target_scale = 1.0  # 修改为一个合理的切片聚焦倍率，避免放大过度出现马赛克
        if current_scale < target_scale:
            factor = target_scale / current_scale
            self.viewer.scale(factor, factor)
        elif current_scale > target_scale:  # 如果当前放得太大，也缩小回该视角
            factor = target_scale / current_scale
            self.viewer.scale(factor, factor)

        # 手动触发局部高清渲染
        if hasattr(self.viewer, "_render_high_res_viewport"):
            self.viewer._render_high_res_viewport()
        if hasattr(self.viewer, "_trigger_view_update"):
            self.viewer._trigger_view_update()
