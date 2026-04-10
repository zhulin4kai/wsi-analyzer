import sys
import os

def resource_path(relative_path):
    """生成资源绝对路径，兼顾开发环境与 PyInstaller 打包环境"""
    if hasattr(sys, '_MEIPASS'):
        # 单文件模式 (--onefile) 会用到 _MEIPASS
        base_path = sys._MEIPASS
    else:
        # 目录模式 (--onedir) 下
        base_path = os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.join(base_path, relative_path)

# 只需要在 import openslide 之前，先 import openslide_bin，它会自动挂载 DLL
import openslide_bin
import openslide
import json
import csv
from PySide6.QtWidgets import (QApplication, QGraphicsRectItem, QGraphicsItemGroup,
                               QToolBar, QPushButton, QProgressBar, QCheckBox,
                               QMessageBox, QFileDialog, QLabel, QDockWidget)
from PySide6.QtCore import Qt, QThread, Signal, QRectF
from PySide6.QtGui import QPen, QColor

from BaseViewer import MainWindow
from Analyzer import WSIAnalyzer
from Minimap import MinimapView


# ==================== 模块 A: 真实异步工作线程 ====================
class AIAnalysisThread(QThread):
    """驱动真实 YOLO 引擎的后台线程"""
    progress_updated = Signal(int)
    status_updated = Signal(str)  # 用于向状态栏汇报文字状态
    analysis_finished = Signal(list)
    error_occurred = Signal(str)

    def __init__(self, svs_path, model_path, parent=None):
        super().__init__(parent)
        self.svs_path = svs_path
        self.model_path = model_path

    def run(self):
        try:
            self.status_updated.emit("正在初始化 AI 模型与计算设备 (耗时较长，请稍候)...")

            # 1. 实例化真实的分析器
            # (在此处实例化，意味着模型加载在后台线程发生，完全不会卡死主界面)
            analyzer = WSIAnalyzer(
                svs_path=self.svs_path,
                model_path=self.model_path,
                patch_size=512,
                stride=400,
                batch_size=16,  # 如果你的 GPU 显存 >= 8G，建议可以改成 32 或 64
                nms_iou_thresh=0.25
            )

            # 2. 触发核心管线，并注入 Lambda 回调函数进行 UI 信号中转
            results = analyzer.process(
                output_json="current_wsi_analysis.json",
                progress_callback=lambda p: self.progress_updated.emit(p),
                status_callback=lambda s: self.status_updated.emit(s)
            )

            if results is None:
                self.error_occurred.emit("未提取到有效组织区域，分析终止。")
            else:
                self.analysis_finished.emit(results)

        except RuntimeError as re:
            if "CUDA out of memory" in str(re):
                self.error_occurred.emit("显存不足 (CUDA OOM)！请在代码中调小 batch_size。")
            else:
                self.error_occurred.emit(f"运行时错误: {str(re)}")
        except Exception as e:
            self.error_occurred.emit(f"AI 引擎异常: {str(e)}")
        finally:
            if analyzer is not None:
                analyzer.close()


# ==================== 模块 B & C: UI 交互与结果渲染 ====================
class AIMainWindow(MainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("基于YOLOv8的智能 WSI 病理切片辅助诊断系统")
        self.resize(1440, 900)

        # 状态记录
        self.current_wsi_path = None
        self.current_model_path = "best.pt"  # 默认模型路径

        # AI 图层组
        self.ai_layer_group = QGraphicsItemGroup()
        self.viewer.scene_canvas.addItem(self.ai_layer_group)

        self._init_ai_ui()
        self._init_minimap_dock()

    def open_file(self):
        """重写父类的打开文件逻辑，以便拦截并记录当前的 SVS 绝对路径"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择全尺寸病理切片", "", "WSI Files (*.svs *.tif *.ndpi)"
        )
        if file_path:
            self.current_wsi_path = file_path
            self.viewer.load_wsi(file_path)
            self.statusBar().showMessage(f"已加载: {os.path.basename(file_path)}")

            if self.viewer.slide:
                self.minimap.load_minimap(self.viewer.slide)

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
        self.ai_thread = AIAnalysisThread(
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

    def render_ai_results(self, results):
        """渲染预测结果"""
        # 清空旧数据
        for item in self.ai_layer_group.childItems():
            self.ai_layer_group.removeFromGroup(item)
            self.viewer.scene_canvas.removeItem(item)

        # 遍历生成 QGraphicsRectItem
        for data in results:
            x_min, y_min, x_max, y_max = data["bbox"]
            conf = data["confidence"]
            cls_id = data["class_id"]

            rect_item = QGraphicsRectItem(QRectF(x_min, y_min, x_max - x_min, y_max - y_min))

            # 【化妆笔模式】保证在全景缩小（Level 0 大尺寸）下依然可见
            pen = QPen(QColor(255, 0, 0))
            pen.setWidth(2)
            pen.setCosmetic(True)
            rect_item.setPen(pen)

            rect_item.setToolTip(f"微乳头状癌病灶\n置信度: {conf:.2%}")
            self.ai_layer_group.addToGroup(rect_item)

        # 保存结果并启用导出按钮
        self.current_ai_results = results
        if len(results) > 0:
            self.btn_export.setEnabled(True)

        self.ai_layer_group.setVisible(self.chk_show_ai.isChecked())
        QMessageBox.information(self, "分析完成", f"全片微乳头细胞检测完毕，共标记 {len(results)} 处疑似病灶。")



    def toggle_ai_visibility(self, state):
        self.ai_layer_group.setVisible(state == Qt.Checked)

    def _init_minimap_dock(self):
        """初始化鹰眼图停靠面板"""
        # 实例化鹰眼图视图
        self.minimap = MinimapView()
        self.minimap.setMinimumSize(250, 200)  # 设置最小尺寸

        # 创建 QDockWidget 作为容器
        self.dock_minimap = QDockWidget("全景导航 (Minimap)", self)
        self.dock_minimap.setWidget(self.minimap)
        # 允许停靠在左侧或右侧
        self.dock_minimap.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        # 允许浮动和移动
        self.dock_minimap.setFeatures(QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetMovable)

        # 默认将鹰眼图停靠在窗口右侧
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock_minimap)

        # 绑定双向联动信号（前提是 WSIView 中已写好了 view_rect_changed 信号发射逻辑）
        self.viewer.view_rect_changed.connect(self.minimap.update_indicator)
        self.minimap.navigate_requested.connect(self.navigate_main_view)

    def navigate_main_view(self, cx, cy):
        """鹰眼图向主视图发送跳转请求时的槽函数"""
        self.viewer.centerOn(cx, cy)
        # 手动触发一次高分辨率渲染
        self.viewer._render_high_res_viewport()

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
                        writer.writerow([idx, item["class_id"], f"{item['confidence']:.4f}", b[0], b[1], b[2], b[3]])

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



if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AIMainWindow()
    window.show()
    sys.exit(app.exec())