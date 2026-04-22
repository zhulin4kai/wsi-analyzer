import os

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGraphicsDropShadowEffect,
    QGraphicsItemGroup,
    QGraphicsRectItem,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QToolBar,
    QVBoxLayout,
)

from config import AI_PEN_COLOR, AI_PEN_WIDTH
from gui.widgets import MinimapView, ReportExporter, WSIView
from utils import DatabaseManager
from workers import AIAnalysisWorker


class MainWindow(QMainWindow):
    """主窗口容器"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("基于 YOLOv8 的智能 WSI 病理切片辅助诊断系统")
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
        """打开系统设置面板，调整数据库容量限制"""
        db = DatabaseManager()
        current_capacity = db.get_max_capacity()

        new_capacity, ok = QInputDialog.getInt(
            self,
            "系统设置",
            "设置本地数据库最大存储容量 (MB):\n超出该容量时将自动清理最旧的分析记录\n最低50MB",
            value=current_capacity,
            minValue=50,
            maxValue=10000,
            step=50,
        )

        if ok and new_capacity != current_capacity:
            db.set_max_capacity(new_capacity)
            QMessageBox.information(
                self, "设置成功", f"数据库最大容量已更新为 {new_capacity} MB。"
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)

    def open_file(self):
        """重写父类的打开文件逻辑，以便拦截并记录当前的 SVS 绝对路径"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择全尺寸病理切片", "", "WSI Files (*.svs *.tif *.ndpi)"
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

            self.current_wsi_path = file_path
            self.viewer.load_wsi(file_path)
            self.statusBar().showMessage(f"已加载: {os.path.basename(file_path)}")

            if hasattr(self.viewer, "slide_engine") and self.viewer.slide_engine:
                self.minimap.load_minimap(self.viewer.slide_engine)

            # 本地数据库静默读取
            db = DatabaseManager()
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
        self.btn_export.clicked.connect(self.export_report)
        toolbar.addWidget(self.btn_export)

        # 用于存储当前切片的最新分析结果
        self.current_ai_results = []

        self.ai_thread = None

    def select_model(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择 YOLO 权重文件", "", "PyTorch Models (*.pt)"
        )
        if file_path:
            self.current_model_path = file_path
            self.lbl_model.setText(f" 当前模型: {os.path.basename(file_path)} ")

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

    def handle_ai_error(self, err_msg):
        if hasattr(self, "progress_dialog"):
            self.progress_dialog.close()
        self.statusBar().showMessage("分析失败或被中断。")
        QMessageBox.critical(self, "AI 引擎错误", err_msg)

    def toggle_ai_visibility(self, state):
        self.ai_layer_group.setVisible(state == Qt.Checked)

    def _init_minimap_overlay(self):
        """初始化鹰眼图悬浮层"""
        self.minimap = MinimapView(self.viewer)
        self.minimap.setFixedSize(250, 200)  # 悬浮窗通常使用固定大小

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

    def export_report(self):
        """生成并导出CSV/JSON 格式的结构化报告"""
        ReportExporter.export(self, self.current_wsi_path, self.current_ai_results)
