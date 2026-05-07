from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMessageBox


def _show_shortcuts(window):
    QMessageBox.information(
        window,
        "快捷键参考",
        "Ctrl+O        打开 WSI 文件\n"
        "Ctrl+Q        退出系统\n"
        "Ctrl+R        重置视图\n"
        "Ctrl+=        放大\n"
        "Ctrl+-        缩小",
    )


def _show_about(window):
    QMessageBox.about(
        window,
        "关于 WSIAnalyzer",
        "<b>智能 WSI 病理切片辅助诊断系统</b> &nbsp; v1.0<br><br>"
        "基于深度学习的全切片图像（WSI）病理辅助诊断平台，<br>"
        "专用于微乳头状癌病灶自动检测与分析。<br><br>"
        "<b>技术栈</b><br>"
        "Python &nbsp;·&nbsp; PySide6 &nbsp;·&nbsp; OpenSlide "
        "&nbsp;·&nbsp; PyTorch &nbsp;·&nbsp; Ultralytics YOLO<br><br>"
        "© 2024 &nbsp; WSIAnalyzer",
    )


class MainMenuBuilder:
    def __init__(self, window):
        self.window = window

    def build(self):
        self._build_file_menu()
        self._build_view_menu()
        self._build_analyze_menu()
        self._build_help_menu()

    def _build_file_menu(self):
        window = self.window
        file_menu = window.menuBar().addMenu("文件")

        open_action = file_menu.addAction("打开 WSI 文件")
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(window.open_file)

        add_action = file_menu.addAction("添加图像到列表")
        add_action.triggered.connect(window.add_images_to_list)

        file_menu.addSeparator()

        export_menu = file_menu.addMenu("导出诊断报告")
        export_menu.addAction("导出为 CSV").triggered.connect(
            lambda: window.export_report("csv")
        )
        export_menu.addAction("导出为 JSON").triggered.connect(
            lambda: window.export_report("json")
        )
        export_menu.addAction("导出为 GeoJSON (QuPath)").triggered.connect(
            lambda: window.export_report("geojson")
        )

        file_menu.addSeparator()

        import_annotation_action = file_menu.addAction("导入标注 (GeoJSON)")
        import_annotation_action.triggered.connect(window.import_annotations)

        file_menu.addSeparator()

        window.settings_action = file_menu.addAction("系统设置")
        window.settings_action.triggered.connect(window.open_settings)

        file_menu.addSeparator()

        exit_action = file_menu.addAction("退出")
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(window.close)

    def _build_view_menu(self):
        window = self.window
        mc = window.minimap_controller
        view_menu = window.menuBar().addMenu("视图")

        zoom_in_action = view_menu.addAction("放大")
        zoom_in_action.setShortcut("Ctrl+=")
        zoom_in_action.triggered.connect(window.viewer.zoom_in)

        zoom_out_action = view_menu.addAction("缩小")
        zoom_out_action.setShortcut("Ctrl+-")
        zoom_out_action.triggered.connect(window.viewer.zoom_out)

        reset_action = view_menu.addAction("重置视图")
        reset_action.setShortcut("Ctrl+R")
        reset_action.triggered.connect(window.viewer.reset_to_fit)

        view_menu.addSeparator()

        panel_menu = view_menu.addMenu("面板")
        panel_menu.addAction(window.image_list_panel.toggleViewAction())
        panel_menu.addAction(window.gallery.toggleViewAction())

        minimap_menu = panel_menu.addMenu("鹰眼图")

        show_action = minimap_menu.addAction("显示鹰眼图")
        show_action.setCheckable(True)
        show_action.setChecked(mc.is_visible())
        show_action.toggled.connect(mc.set_visible)

        minimap_menu.addSeparator()

        size_menu = minimap_menu.addMenu("大小")
        size_group = QActionGroup(window)
        size_group.setExclusive(True)
        size_actions = []
        for scale, label in mc.SIZE_PRESETS:
            action = QAction(label, size_group)
            action.setCheckable(True)
            action.setData(scale)
            action.setChecked(scale == 1.0)
            action.triggered.connect(
                lambda checked, s=scale: mc.set_size_scale(s)
            )
            size_menu.addAction(action)
            size_actions.append(action)
        mc.register_size_actions(size_actions)

        view_menu.addSeparator()

        hud_menu = view_menu.addMenu("信息显示")

        scalebar_action = hud_menu.addAction("显示比例尺")
        scalebar_action.setCheckable(True)
        scalebar_action.setChecked(True)
        scalebar_action.toggled.connect(window.hud.set_scale_bar_visible)

        infobar_action = hud_menu.addAction("显示坐标信息")
        infobar_action.setCheckable(True)
        infobar_action.setChecked(True)
        infobar_action.toggled.connect(window.hud.set_info_bar_visible)

        mag_action = hud_menu.addAction("显示放大倍率")
        mag_action.setCheckable(True)
        mag_action.setChecked(True)
        mag_action.toggled.connect(window.hud.set_magnification_visible)

    def _build_analyze_menu(self):
        window = self.window
        analyze_menu = window.menuBar().addMenu("分析")

        analyze_action = analyze_menu.addAction("开始全片检测")
        analyze_action.triggered.connect(window.start_ai_analysis)

        roi_action = analyze_menu.addAction("框选 ROI 分析")
        roi_action.setCheckable(True)
        roi_action.triggered.connect(window.btn_roi_analyze.setChecked)
        window.btn_roi_analyze.toggled.connect(roi_action.setChecked)

        analyze_menu.addSeparator()

        cancel_action = analyze_menu.addAction("取消分析")
        cancel_action.triggered.connect(window.cancel_ai_analysis)

        clear_action = analyze_menu.addAction("清除分析结果")
        clear_action.triggered.connect(window.clear_ai_results)

        analyze_menu.addSeparator()

        model_action = analyze_menu.addAction("选择模型权重")
        model_action.triggered.connect(window.select_model)

        analyze_menu.addSeparator()

        show_ai_action = analyze_menu.addAction("显示预测框")
        show_ai_action.setCheckable(True)
        show_ai_action.setChecked(True)
        show_ai_action.toggled.connect(window.chk_show_ai.setChecked)
        window.chk_show_ai.toggled.connect(show_ai_action.setChecked)

        show_heatmap_action = analyze_menu.addAction("显示热力图")
        show_heatmap_action.setCheckable(True)
        show_heatmap_action.setChecked(False)
        show_heatmap_action.toggled.connect(
            lambda checked: window.chk_show_heatmap.setChecked(checked)
        )
        window.chk_show_heatmap.toggled.connect(
            lambda checked: (
                show_heatmap_action.blockSignals(True),
                show_heatmap_action.setChecked(checked),
                show_heatmap_action.blockSignals(False),
            )
        )

    def _build_help_menu(self):
        window = self.window
        help_menu = window.menuBar().addMenu("帮助")

        shortcuts_action = help_menu.addAction("快捷键参考")
        shortcuts_action.triggered.connect(lambda: _show_shortcuts(window))

        help_menu.addSeparator()

        about_action = help_menu.addAction("关于系统")
        about_action.triggered.connect(lambda: _show_about(window))
