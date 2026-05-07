import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QGraphicsItemGroup,
    QGraphicsPixmapItem,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
)

from config import AI_LAYER_Z_VALUE, HEATMAP_Z_VALUE, HUD_MARGIN
from core import ImageServer
from gui.mixins import AnalysisMixin, FileHandlingMixin
from gui.main_menu import MainMenuBuilder
from gui.widgets import (
    ImageListPanel,
    InfoBarOverlay,
    LesionGallery,
    MinimapView,
    ReportExporter,
    ScaleBarOverlay,
    WSIView,
)


class MainWindow(AnalysisMixin, FileHandlingMixin, QMainWindow):
    """主窗口容器"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("智能 WSI 病理切片辅助诊断系统 - WSIAnalyzer")
        self.resize(1440, 900)
        self.setAcceptDrops(True)

        # 状态记录
        self.current_wsi_path = None
        self.current_model_path = None
        self._was_ai_visible = True
        self.current_ai_results = []
        self.current_imported_annotations = []

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

        # 导入标注图层：Z 值略高于 AI 预测框，位于热力图与 ROI 框之间
        self.imported_layer_group = QGraphicsItemGroup()
        self.imported_layer_group.setZValue(AI_LAYER_Z_VALUE + 10)
        self.viewer.scene_canvas.addItem(self.imported_layer_group)

        # 3. 初始化所有 UI 面板（_init_menu 必须最后调用，依赖其他面板已创建）
        self._init_ai_ui()
        self._init_heatmap_ui()
        self._init_minimap_overlay()
        self._init_gallery_ui()
        self._init_image_list()
        self._init_overlay_hud()
        MainMenuBuilder(self).build()

        # 4. 绑定信号
        self.viewer.interaction_started.connect(self._on_interaction_start)
        self.viewer.interaction_finished.connect(self._on_interaction_finish)
        self.viewer.roi_drawn.connect(self.start_roi_analysis)
        self.viewer.wsi_loaded.connect(self._on_wsi_loaded)

    def open_settings(self):
        """打开系统设置面板"""
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
        self.viewer.navigate_to(cx, cy, render=True)

    def _on_minimap_drag(self, cx, cy):
        """鹰眼图拖拽时的轻量导航，仅移动视图不触发高清渲染"""
        self.viewer.navigate_to(cx, cy, render=False)

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
        self.gallery.hide()  # 默认隐藏，有结果时再显示
        self.addDockWidget(Qt.RightDockWidgetArea, self.gallery)

    def _navigate_to_lesion(self, cx, cy):
        """接收画廊靶向信号，瞬间移动主视图到病灶中心并放大"""
        self.viewer.focus_on(cx, cy, target_scale=1.0)

    # ==================== Drag and Drop ====================

    _WSI_EXTENSIONS = {".svs", ".tif", ".ndpi", ".ome.tif"}

    def _extract_wsi_paths(self, event) -> list:
        """从拖拽事件中提取有效的 WSI 文件路径列表。"""
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        paths = []
        for url in urls:
            if url.isLocalFile():
                path = url.toLocalFile()
                full_lower = path.lower()
                if any(
                    full_lower.endswith(e) for e in self._WSI_EXTENSIONS
                ) and os.path.exists(path):
                    paths.append(path)
        return paths

    def dragEnterEvent(self, event: QDragEnterEvent):
        paths = self._extract_wsi_paths(event)
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
        paths = self._extract_wsi_paths(event)
        if not paths:
            return

        event.acceptProposedAction()
        # 批量添加并加载第一个
        if hasattr(self, "image_list_panel"):
            self.image_list_panel.add_images(paths)
        if paths:
            self._load_wsi_at_path(paths[0])
