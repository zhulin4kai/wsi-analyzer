from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QGraphicsItemGroup,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
)

from gui.mixins.ai_analysis_mixin import AIAnalysisMixin
from gui.mixins.file_mixin import FileHandlingMixin
from gui.widgets import LesionGallery, MinimapView, ReportExporter, WSIView


class MainWindow(AIAnalysisMixin, FileHandlingMixin, QMainWindow):
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
        self.viewer.roi_drawn.connect(self.start_roi_analysis)

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
            lambda: QMessageBox.about(self, "关于", "智能 WSI 病理切片辅助诊断系统")
        )

    def open_settings(self):
        """打开系统设置面板"""
        from PySide6.QtWidgets import QDialog

        from gui.dialogs.settings_dialog import SettingsDialog

        dlg = SettingsDialog(self, current_wsi_path=self.current_wsi_path)
        if dlg.exec() == QDialog.Accepted:
            dlg.apply_settings()
            QMessageBox.information(self, "设置成功", "设置已保存。")

    def resizeEvent(self, event):
        super().resizeEvent(event)

    def _init_minimap_overlay(self):
        """初始化鹰眼图悬浮层"""
        self.minimap = MinimapView(self.viewer)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 100))
        shadow.setOffset(2, 2)
        self.minimap.setGraphicsEffect(shadow)

        # 右上角
        layout = QVBoxLayout(self.viewer)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.minimap, alignment=Qt.AlignTop | Qt.AlignRight)

        # 绑定双向联动信号
        self.viewer.view_rect_changed.connect(self.minimap.update_indicator)
        self.minimap.navigate_requested.connect(self.navigate_main_view)

    def navigate_main_view(self, cx, cy):
        """鹰眼图向主视图发送跳转请求时的槽函数"""
        self.viewer.centerOn(cx, cy)
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
