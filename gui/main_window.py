from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QGraphicsItemGroup,
    QGraphicsPixmapItem,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
)

from config import AI_LAYER_Z_VALUE, HEATMAP_Z_VALUE, HUD_MARGIN
from core.image_server import ImageServer
from gui.mixins.analysis_mixin import AnalysisMixin
from gui.mixins.file_mixin import FileHandlingMixin
from gui.widgets import (
    ImageListPanel,
    LesionGallery,
    MinimapView,
    ReportExporter,
    WSIView,
)
from gui.widgets.info_bar_overlay import InfoBarOverlay
from gui.widgets.scale_bar_overlay import ScaleBarOverlay


class MainWindow(AnalysisMixin, FileHandlingMixin, QMainWindow):
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

        # 2. 初始化图层（Z-index 由低到高：底图[-1] → 瓦片[1~N] → 热力图[500] → 预测框[600] → ROI[1000]）
        self.heatmap_layer_item = QGraphicsPixmapItem()
        self.heatmap_layer_item.setZValue(HEATMAP_Z_VALUE)
        self.heatmap_layer_item.setTransformationMode(Qt.SmoothTransformation)
        self.viewer.scene_canvas.addItem(self.heatmap_layer_item)

        self.ai_layer_group = QGraphicsItemGroup()
        self.ai_layer_group.setZValue(AI_LAYER_Z_VALUE)
        self.viewer.scene_canvas.addItem(self.ai_layer_group)

        # 3. 初始化所有 UI 面板（_init_menu 必须最后调用，依赖其他面板已创建）
        self._init_ai_ui()
        self._init_heatmap_ui()
        self._init_minimap_overlay()
        self._init_gallery_ui()
        self._init_image_list()
        self._init_overlay_hud()
        self._init_menu()

        # 4. 绑定信号
        self.viewer.interaction_started.connect(self._on_interaction_start)
        self.viewer.interaction_finished.connect(self._on_interaction_finish)
        self.viewer.roi_drawn.connect(self.start_roi_analysis)
        self.viewer.wsi_loaded.connect(self._on_wsi_loaded)

    def _init_menu(self):
        menubar = self.menuBar()

        # ── 文件 ──────────────────────────────────────────────────────────────
        file_menu = menubar.addMenu("文件")

        open_action = file_menu.addAction("打开 WSI 文件...")
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_file)

        add_action = file_menu.addAction("添加图像到列表...")
        add_action.triggered.connect(self.add_images_to_list)

        file_menu.addSeparator()

        export_menu = file_menu.addMenu("导出诊断报告")
        export_menu.addAction("导出为 CSV").triggered.connect(
            lambda: self.export_report("csv")
        )
        export_menu.addAction("导出为 JSON").triggered.connect(
            lambda: self.export_report("json")
        )
        export_menu.addAction("导出为 GeoJSON (QuPath)").triggered.connect(
            lambda: self.export_report("geojson")
        )

        file_menu.addSeparator()

        self.settings_action = file_menu.addAction("系统设置...")
        self.settings_action.triggered.connect(self.open_settings)

        file_menu.addSeparator()

        exit_action = file_menu.addAction("退出")
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)

        # ── 视图 ──────────────────────────────────────────────────────────────
        view_menu = menubar.addMenu("视图")

        zoom_in_action = view_menu.addAction("放大")
        zoom_in_action.setShortcut("Ctrl+=")
        zoom_in_action.triggered.connect(self.viewer.zoom_in)

        zoom_out_action = view_menu.addAction("缩小")
        zoom_out_action.setShortcut("Ctrl+-")
        zoom_out_action.triggered.connect(self.viewer.zoom_out)

        reset_action = view_menu.addAction("重置视图")
        reset_action.setShortcut("Ctrl+R")
        # 修复：原 resetTransform() 重置为 1:1 导致只能看到切片左上角一小块
        # 正确行为是复用 load_wsi() 的 fit-to-window 逻辑
        reset_action.triggered.connect(self.viewer.reset_to_fit)

        view_menu.addSeparator()

        # 面板子菜单：使用 QDockWidget.toggleViewAction() 内建 Action，
        # 自动维护 check 状态与面板可见性的双向同步
        panel_menu = view_menu.addMenu("面板")
        panel_menu.addAction(self.image_list_panel.toggleViewAction())
        panel_menu.addAction(self.gallery.toggleViewAction())

        # 鹰眼图不是 QDockWidget，手动创建 checkable action
        minimap_action = panel_menu.addAction("鹰眼图")
        minimap_action.setCheckable(True)
        minimap_action.setChecked(self.minimap.isVisible())
        minimap_action.toggled.connect(self.minimap.setVisible)

        view_menu.addSeparator()

        # HUD 显示开关子菜单
        hud_menu = view_menu.addMenu("信息显示")

        scalebar_action = hud_menu.addAction("显示比例尺")
        scalebar_action.setCheckable(True)
        scalebar_action.setChecked(True)
        scalebar_action.toggled.connect(self.scale_bar.setVisible)

        infobar_action = hud_menu.addAction("显示坐标信息")
        infobar_action.setCheckable(True)
        infobar_action.setChecked(True)
        infobar_action.toggled.connect(self.info_bar.setVisible)

        mag_action = hud_menu.addAction("显示放大倍率")
        mag_action.setCheckable(True)
        mag_action.setChecked(True)
        mag_action.toggled.connect(self.mag_widget.setVisible)

        # ── 分析 ──────────────────────────────────────────────────────────────
        analyze_menu = menubar.addMenu("分析")

        analyze_action = analyze_menu.addAction("开始全片检测")
        analyze_action.triggered.connect(self.start_ai_analysis)

        # ROI 模式：菜单 action 与工具栏按钮双向同步（setChecked 不重发 triggered，无循环风险）
        roi_action = analyze_menu.addAction("框选 ROI 分析")
        roi_action.setCheckable(True)
        roi_action.triggered.connect(self.btn_roi_analyze.setChecked)
        self.btn_roi_analyze.toggled.connect(roi_action.setChecked)

        analyze_menu.addSeparator()

        cancel_action = analyze_menu.addAction("取消分析")
        cancel_action.triggered.connect(self.cancel_ai_analysis)

        clear_action = analyze_menu.addAction("清除分析结果")
        clear_action.triggered.connect(self.clear_ai_results)

        analyze_menu.addSeparator()

        model_action = analyze_menu.addAction("选择模型权重...")
        model_action.triggered.connect(self.select_model)

        analyze_menu.addSeparator()

        # 显示预测框：菜单 action 与工具栏复选框双向同步
        show_ai_action = analyze_menu.addAction("显示预测框")
        show_ai_action.setCheckable(True)
        show_ai_action.setChecked(True)
        show_ai_action.toggled.connect(self.chk_show_ai.setChecked)
        self.chk_show_ai.toggled.connect(show_ai_action.setChecked)

        # 显示热力图：菜单 action 与工具栏复选框双向同步
        show_heatmap_action = analyze_menu.addAction("显示热力图")
        show_heatmap_action.setCheckable(True)
        show_heatmap_action.setChecked(False)
        show_heatmap_action.toggled.connect(
            lambda checked: self.chk_show_heatmap.setChecked(checked)
        )
        self.chk_show_heatmap.toggled.connect(
            lambda checked: (
                show_heatmap_action.blockSignals(True),
                show_heatmap_action.setChecked(checked),
                show_heatmap_action.blockSignals(False),
            )
        )

        # ── 帮助 ──────────────────────────────────────────────────────────────
        help_menu = menubar.addMenu("帮助")

        shortcuts_action = help_menu.addAction("快捷键参考")
        shortcuts_action.triggered.connect(self._show_shortcuts)

        help_menu.addSeparator()

        about_action = help_menu.addAction("关于系统")
        about_action.triggered.connect(self._show_about)

    def _show_shortcuts(self):
        """显示快捷键参考对话框"""
        QMessageBox.information(
            self,
            "快捷键参考",
            "Ctrl+O        打开 WSI 文件\n"
            "Ctrl+Q        退出系统\n"
            "Ctrl+R        重置视图\n"
            "Ctrl+=        放大\n"
            "Ctrl+-        缩小",
        )

    def _show_about(self):
        """显示关于对话框"""
        QMessageBox.about(
            self,
            "关于 WSIAnalyzer",
            "<b>智能 WSI 病理切片辅助诊断系统</b> &nbsp; v1.0<br><br>"
            "基于深度学习的全切片图像（WSI）病理辅助诊断平台，<br>"
            "专用于微乳头状癌病灶自动检测与分析。<br><br>"
            "<b>技术栈</b><br>"
            "Python &nbsp;·&nbsp; PySide6 &nbsp;·&nbsp; OpenSlide "
            "&nbsp;·&nbsp; PyTorch &nbsp;·&nbsp; Ultralytics YOLO<br><br>"
            "© 2024 &nbsp; WSIAnalyzer",
        )

    def open_settings(self):
        """打开系统设置面板"""
        from PySide6.QtWidgets import QDialog

        from gui.dialogs.settings_dialog import SettingsDialog

        dlg = SettingsDialog(self, current_wsi_path=self.current_wsi_path)
        if dlg.exec() == QDialog.Accepted:
            dlg.apply_settings()
            QMessageBox.information(self, "设置成功", "设置已保存。")

    def closeEvent(self, event):
        ImageServer.instance().shutdown()
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "scale_bar"):
            self._reposition_hud()

    def _init_overlay_hud(self):
        """初始化 HUD 叠加层：左下角比例尺 + 右下角坐标信息栏。"""
        self.scale_bar = ScaleBarOverlay(self.viewer)
        self.info_bar = InfoBarOverlay(self.viewer)

        # 绑定 WSIView 信号
        self.viewer.zoom_changed.connect(self.scale_bar.on_zoom_changed)
        self.viewer.mouse_scene_pos_changed.connect(self.info_bar.on_mouse_moved)

        # 绑定工具栏放大倍率控件信号（mag_widget 由 AIToolbarMixin._init_ai_ui 创建）
        self.viewer.zoom_changed.connect(self.mag_widget.on_zoom_changed)
        self.mag_widget.zoom_to_scale.connect(self.viewer.set_scale)

    def _on_wsi_loaded(self, metadata):
        """切片加载完成后，向 HUD 控件注入元数据并完成初始定位。"""
        mpp = metadata.mpp
        mpp_x = mpp[0] if mpp else None
        mpp_y = mpp[1] if mpp else None

        self.scale_bar.load(mpp_x, mpp_y)
        self.info_bar.load(metadata)

        self.mag_widget.load(metadata.objective_power)

        current_scale = self.viewer.transform().m11()
        self.scale_bar.on_zoom_changed(current_scale)
        self.mag_widget.on_zoom_changed(current_scale)

        self._reposition_hud()

        # 预热相邻切片（利用加载完成后的 I/O 空闲期）
        if hasattr(self, "image_list_panel"):
            self.image_list_panel.preload_adjacent(metadata.path)

    def _reposition_hud(self):
        """将 HUD 控件定位到视图的左下角和右下角。"""
        vw = self.viewer.width()
        vh = self.viewer.height()
        margin = HUD_MARGIN

        sb = self.scale_bar
        ib = self.info_bar
        sb.move(margin, vh - sb.height() - margin)
        ib.move(vw - ib.width() - margin, vh - ib.height() - margin)

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
        self.minimap.navigate_drag_requested.connect(self._on_minimap_drag)

    def navigate_main_view(self, cx, cy):
        """鹰眼图向主视图发送跳转请求时的槽函数"""
        self.viewer.centerOn(cx, cy)
        self.viewer._render_high_res_viewport()
        self.viewer._trigger_view_update()

    def _on_minimap_drag(self, cx, cy):
        """鹰眼图拖拽时的轻量导航，仅移动视图不触发高清渲染"""
        self.viewer.centerOn(cx, cy)
        self.viewer._trigger_view_update()

    def export_report(self, fmt="csv"):
        """生成并导出结构化报告"""
        ReportExporter.export(
            self, self.current_wsi_path, self.current_ai_results, export_format=fmt
        )

    def _init_image_list(self):
        """初始化左侧图像列表停靠面板"""
        self.image_list_panel = ImageListPanel(self)
        self.image_list_panel.image_load_requested.connect(self._load_wsi_at_path)
        self.image_list_panel.add_requested.connect(self.add_images_to_list)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.image_list_panel)

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
