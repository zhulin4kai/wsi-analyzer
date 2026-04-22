import os
import csv
import json
from PySide6.QtWidgets import (QMainWindow, QGraphicsRectItem, QGraphicsItemGroup,
                               QToolBar, QPushButton, QProgressBar, QCheckBox,
                               QMessageBox, QFileDialog, QLabel, QDockWidget, QVBoxLayout, QGraphicsDropShadowEffect)
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPen, QColor

from config import DEFAULT_MODEL_PATH, AI_PEN_COLOR, AI_PEN_WIDTH
from utils import CacheManager
from gui.widgets import WSIView
from gui.widgets import MinimapView
from workers import AIAnalysisWorker

class MainWindow(QMainWindow):
    """主窗口容器"""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("基于 YOLOv8 的智能 WSI 病理切片辅助诊断系统")
        self.resize(1440, 900)

        # 状态记录
        self.current_wsi_path = None
        self.current_model_path = DEFAULT_MODEL_PATH
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
            if hasattr(self, 'btn_export'):
                self.btn_export.setEnabled(False)  # 禁用导出按钮

            self.current_wsi_path = file_path
            self.viewer.load_wsi(file_path)
            self.statusBar().showMessage(f"已加载: {os.path.basename(file_path)}")

            if hasattr(self.viewer, 'slide_engine') and self.viewer.slide_engine:
                self.minimap.load_minimap(self.viewer.slide_engine)

            # 本地缓存静默读取
            cache_data = CacheManager.load_analysis(file_path)
            if cache_data:
                reply = QMessageBox.question(
                    self, "发现分析缓存",
                    "检测到该病理切片已有历史检测记录。\n是否直接加载本地缓存结果？",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    self.render_ai_results(cache_data)
                    self.statusBar().showMessage(f"已从本地缓存加载 {len(cache_data)} 个病灶。")

    def render_ai_results(self, results):
        """渲染预测结果"""
        # 清空旧数据
        for item in self.ai_layer_group.childItems():
            self.ai_layer_group.removeFromGroup(item)
            self.viewer.scene_canvas.removeItem(item)

        # 遍历生成 QGraphicsRectItem
        for data in results:
            x_min, y_min, x_max, y_max = data["bbox"]
            rect_item = QGraphicsRectItem(QRectF(x_min, y_min, x_max - x_min, y_max - y_min))

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
            CacheManager.save_analysis(self.current_wsi_path, results)

        QMessageBox.information(self, "分析完成", f"共标记 {len(results)} 处疑似病灶。")

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

        # 1. 选择模型按钮
        self.btn_sel_model = QPushButton("选择模型权重(choice)")
        self.btn_sel_model.clicked.connect(self.select_model)
        toolbar.addWidget(self.btn_sel_model)

        self.lbl_model = QLabel(f" 当前模型: {self.current_model_path} ")
        toolbar.addWidget(self.lbl_model)
        toolbar.addSeparator()

        # 2. 开始分析按钮
        self.btn_analyze = QPushButton("开始全片检测(start)")
        self.btn_analyze.clicked.connect(self.start_ai_analysis)
        toolbar.addWidget(self.btn_analyze)

        # 3. 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedWidth(200)
        toolbar.addWidget(self.progress_bar)

        # 4. 显隐控制
        self.chk_show_ai = QCheckBox("显示预测框")
        self.chk_show_ai.setChecked(True)
        self.chk_show_ai.stateChanged.connect(self.toggle_ai_visibility)
        toolbar.addWidget(self.chk_show_ai)

        # 5. 导出按钮
        toolbar.addSeparator()
        self.btn_export = QPushButton("导出诊断报告")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self.export_report)
        toolbar.addWidget(self.btn_export)

        # 用于存储当前切片的最新分析结果
        self.current_ai_results = []

        self.ai_thread = None

    def select_model(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择 YOLO 权重文件", "", "PyTorch Models (*.pt)")
        if file_path:
            self.current_model_path = file_path
            self.lbl_model.setText(f" 当前模型: {os.path.basename(file_path)} ")

    def start_ai_analysis(self):
        """启动真实后台推断"""
        if not self.current_wsi_path:
            QMessageBox.warning(self, "警告", "请先通过'文件'菜单打开一个 WSI 切片！")
            return
        if not os.path.exists(self.current_model_path):
            QMessageBox.warning(self, "警告",
                                f"找不到模型文件: {self.current_model_path}\n请点击左侧按钮选择正确的 .pt 文件！")
            return

        self.btn_analyze.setEnabled(False)
        self.progress_bar.setValue(0)

        # 传入当前切片路径和模型路径
        self.ai_thread = AIAnalysisWorker(
            svs_path=self.current_wsi_path,
            model_path=self.current_model_path
        )

        # 连接信号与槽
        self.ai_thread.progress_updated.connect(self.progress_bar.setValue)
        self.ai_thread.status_updated.connect(self.statusBar().showMessage)
        self.ai_thread.analysis_finished.connect(self.render_ai_results)
        self.ai_thread.error_occurred.connect(self.handle_ai_error)
        self.ai_thread.finished.connect(lambda: self.btn_analyze.setEnabled(True))

        self.ai_thread.start()

    def handle_ai_error(self, err_msg):
        self.statusBar().showMessage("分析失败或被中断。")
        QMessageBox.critical(self, "AI 引擎错误", err_msg)

    def toggle_ai_visibility(self, state):
        self.ai_layer_group.setVisible(state == Qt.Checked)

    def _init_minimap_overlay(self):
        """ 初始化鹰眼图悬浮层 """
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
        """ 鹰眼图向主视图发送跳转请求时的槽函数 """
        self.viewer.centerOn(cx, cy)
        # 手动触发一次高分辨率渲染
        self.viewer._render_high_res_viewport()
        self.viewer._trigger_view_update()

    def export_report(self):
        """" 生成并导出CSV/JSON 格式的结构化报告 """
        if not self.current_ai_results:
            QMessageBox.warning(self, "提示", "暂无分析数据可导出！")
            return

        # 1. 基础统计学计算
        total_lesions = len(self.current_ai_results)
        confidences = [item["confidence"] for item in self.current_ai_results]
        avg_conf = sum(confidences) / total_lesions

        # 寻找置信度最高的病灶
        max_conf_item = max(self.current_ai_results, key=lambda x: x["confidence"])
        max_conf = max_conf_item["confidence"]
        max_conf_bbox = max_conf_item["bbox"]

        # 2. 弹出保存文件对话框
        default_name = "WSI_AI_Report.csv"
        if self.current_wsi_path:
            base_name = os.path.splitext(os.path.basename(self.current_wsi_path))[0]
            default_name = f"{base_name}_诊断报告.csv"

        save_path, filter_type = QFileDialog.getSaveFileName(
            self, "导出诊断报告", default_name, "CSV 文件 (*.csv);;JSON 文件 (*.json)"
        )

        if not save_path:
            return

        # 3. 写入文件 (包含 I/O 异常捕获)
        try:
            if save_path.endswith('.csv'):
                # 使用 utf-8-sig 编码，防止 Excel 打开中文乱码
                with open(save_path, mode='w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)

                    # 写入总览信息
                    writer.writerow(["=== 智能病理辅助诊断报告 ==="])
                    writer.writerow(["分析文件", self.current_wsi_path])
                    writer.writerow(["病灶总数", total_lesions])
                    writer.writerow(["平均置信度", f"{avg_conf:.2%}"])
                    writer.writerow(["最高置信度", f"{max_conf:.2%} (坐标: {max_conf_bbox})"])
                    writer.writerow([])

                    # 写入明细表头
                    writer.writerow(["序号", "类别ID", "置信度", "X_min", "Y_min", "X_max", "Y_max"])
                    for idx, item in enumerate(self.current_ai_results, 1):
                        b = item["bbox"]
                        writer.writerow(
                            [idx, item["class_id"], f"{item['confidence']:.4f}", b[0], b[1], b[2], b[3]])

            elif save_path.endswith('.json'):
                # JSON 格式导出
                export_data = {
                    "summary": {
                        "file": self.current_wsi_path,
                        "total_lesions": total_lesions,
                        "average_confidence": round(avg_conf, 4),
                        "max_confidence_bbox": max_conf_bbox
                    },
                    "details": self.current_ai_results
                }
                with open(save_path, mode='w', encoding='utf-8') as f:
                    json.dump(export_data, f, ensure_ascii=False, indent=4)

            QMessageBox.information(self, "导出成功", f"报告已成功保存至:\n{save_path}")

        except PermissionError:
            QMessageBox.critical(self, "导出失败",
                                 "文件被占用！\n请检查该文件是否正在被 Excel 或其他程序打开，关闭后再试。")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"写入文件时发生错误:\n{str(e)}")