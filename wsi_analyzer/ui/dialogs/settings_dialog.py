from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from wsi_analyzer.config import config
from wsi_analyzer.app.dependency_container import container
from wsi_analyzer.infrastructure.hardware import HardwareProfiler


def _mpp_to_label(mpp: float, options: dict) -> str:
    """将 MPP 值反查为倍率标签，若未精确匹配则返回'自定义 (MPP)'。"""
    for label, val in options.items():
        if val is not None and abs(val - mpp) < 1e-4:
            return label
    return "自定义 (MPP)"


class SettingsDialog(QDialog):
    """系统设置对话框"""

    def __init__(self, parent=None, current_wsi_path=None):
        super().__init__(parent)
        self.current_wsi_path = current_wsi_path
        self.setWindowTitle("系统设置")
        self.resize(400, 300)

        self._db = container.database
        self._current_capacity = self._db.get_max_capacity()
        self._drive_prefix = ""
        self._profile = None

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._build_basic_tab(), "基本设置")
        tabs.addTab(self._build_perf_tab(), "性能与硬件加速")
        tabs.addTab(self._build_ai_tab(), "分析参数设置")
        layout.addWidget(tabs)

        btn_save = QPushButton("保存")
        btn_save.clicked.connect(self._on_save_clicked)
        layout.addWidget(btn_save)

        # 初始化启用状态
        self._toggle_ai_inputs()

    def _build_basic_tab(self):
        tab = QWidget()
        layout = QFormLayout(tab)

        self.spin_capacity = QSpinBox()
        self.spin_capacity.setRange(getattr(config, "DB_MIN_CAPACITY_MB", 50), 10000)
        self.spin_capacity.setSingleStep(50)
        self.spin_capacity.setValue(self._current_capacity)
        layout.addRow("数据库最大容量 (MB):", self.spin_capacity)

        return tab

    def _build_perf_tab(self):
        tab = QWidget()
        layout = QFormLayout(tab)

        if self.current_wsi_path:
            self._drive_prefix = HardwareProfiler.get_storage_key(
                self.current_wsi_path
            )

        self._profile = (
            self._db.get_system_profile(self._drive_prefix)
            if self._drive_prefix
            else None
        )

        lbl_device = QLabel(
            self._profile.get("device", "未知") if self._profile else "未知"
        )
        lbl_io_speed = QLabel(
            f"{self._profile.get('io_speed', 0):.2f} MB/s "
            f"({self._profile.get('io_rating', '未知')})"
            if self._profile
            else "未知"
        )

        self.spin_batch = QSpinBox()
        self.spin_batch.setRange(1, getattr(config, "BATCH_SIZE_CAP_NVME_SSD", 256))
        self.spin_batch.setValue(
            self._profile.get("batch_size", 16) if self._profile else 16
        )

        layout.addRow("计算设备:", lbl_device)
        layout.addRow(
            "当前盘符:",
            QLabel(self._drive_prefix if self._drive_prefix else "未加载文件"),
        )
        layout.addRow("当前 I/O 速度:", lbl_io_speed)
        layout.addRow("Batch Size (可手动覆盖):", self.spin_batch)

        return tab

    def _build_ai_tab(self):
        tab = QWidget()
        layout = QFormLayout(tab)

        self.chk_auto_tune = QCheckBox("开启自动调优 (推荐)")
        self.chk_auto_tune.setChecked(self._db.get_auto_tune_enabled())

        self.combo_model_type = QComboBox()
        self.combo_model_type.addItems(["YOLO"])
        self.combo_model_type.setCurrentText(
            self._db.get_setting("ai_model_type", "YOLO")
        )

        # 模型训练倍率 / MPP
        self.combo_mag = QComboBox()
        mag_options = getattr(config, "AI_MAG_OPTIONS", {})
        self.combo_mag.addItems(list(mag_options.keys()))
        # 根据已保存的 MPP 反查倍率标签
        saved_mpp = float(
            self._db.get_setting(
                "ai_model_target_mpp", getattr(config, "AI_MODEL_TARGET_MPP", 2.0)
            )
        )
        mag_label = _mpp_to_label(saved_mpp, mag_options)
        self.combo_mag.setCurrentText(mag_label)
        self.combo_mag.currentTextChanged.connect(self._on_mag_changed)

        self.spin_mpp = QDoubleSpinBox()
        self.spin_mpp.setRange(0.01, 100.0)
        self.spin_mpp.setSingleStep(0.1)
        self.spin_mpp.setDecimals(2)
        self.spin_mpp.setValue(saved_mpp)
        self.spin_mpp.setVisible(mag_label == "自定义 (MPP)")
        self.spin_mpp.setToolTip("模型训练时的物理分辨率 (μm/px)")

        self.spin_patch_size = QSpinBox()
        self.spin_patch_size.setRange(128, 4096)
        self.spin_patch_size.setSingleStep(128)
        self.spin_patch_size.setValue(
            self._db.get_setting("ai_patch_size", getattr(config, "AI_PATCH_SIZE", 512))
        )

        self.spin_stride = QSpinBox()
        self.spin_stride.setRange(64, 4096)
        self.spin_stride.setSingleStep(64)
        self.spin_stride.setValue(
            self._db.get_setting("ai_stride", getattr(config, "AI_STRIDE", 400))
        )

        self.spin_iou = QDoubleSpinBox()
        self.spin_iou.setRange(0.01, 1.0)
        self.spin_iou.setSingleStep(0.05)
        self.spin_iou.setValue(
            self._db.get_setting(
                "ai_nms_iou_thresh", getattr(config, "AI_NMS_IOU_THRESH", 0.25)
            )
        )

        self.spin_conf = QDoubleSpinBox()
        self.spin_conf.setRange(0.01, 1.0)
        self.spin_conf.setSingleStep(0.05)
        self.spin_conf.setValue(
            self._db.get_setting(
                "ai_conf_thresh", getattr(config, "AI_CONF_THRESH", 0.5)
            )
        )

        self.chk_imported_heatmap = QCheckBox("导入标注参与热力图")
        self.chk_imported_heatmap.setChecked(
            self._db.get_setting("show_imported_heatmap", True)
        )

        layout.addRow("", self.chk_auto_tune)
        layout.addRow("模型架构 (Architecture):", self.combo_model_type)
        layout.addRow("模型训练倍率:", self.combo_mag)
        layout.addRow("模型目标 MPP (μm/px):", self.spin_mpp)
        layout.addRow("切片尺寸 (Patch Size):", self.spin_patch_size)
        layout.addRow("滑动步长 (Stride):", self.spin_stride)
        layout.addRow("NMS IOU 阈值:", self.spin_iou)
        layout.addRow("置信度阈值 (Conf):", self.spin_conf)
        layout.addRow("", self.chk_imported_heatmap)

        self.chk_auto_tune.clicked.connect(self._toggle_ai_inputs)
        self.combo_model_type.currentTextChanged.connect(self._toggle_ai_inputs)

        return tab

    def _toggle_ai_inputs(self):
        is_manual = not self.chk_auto_tune.isChecked()
        is_yolo = self.combo_model_type.currentText() == "YOLO"
        self.spin_patch_size.setEnabled(is_manual or not is_yolo)
        self.spin_stride.setEnabled(is_manual)
        self.spin_iou.setEnabled(is_manual)
        self.spin_conf.setEnabled(is_manual)

    def _on_mag_changed(self, label: str):
        """倍率下拉切换时，同步更新 MPP 输入框的值与可见性。"""
        mag_options = getattr(config, "AI_MAG_OPTIONS", {})
        mpp_val = mag_options.get(label)
        if mpp_val is not None:
            self.spin_mpp.setValue(mpp_val)
            self.spin_mpp.setVisible(False)
        else:
            self.spin_mpp.setVisible(True)

    def _on_save_clicked(self):
        patch_size = self.spin_patch_size.value()
        stride = self.spin_stride.value()
        if stride > patch_size:
            QMessageBox.warning(
                self,
                "参数警告",
                f"滑动步长 ({stride}) 大于切片尺寸 ({patch_size})，可能导致推断区域遗漏。\n"
                f"建议步长小于或等于切片尺寸。",
            )
            return
        self.accept()

    def apply_settings(self):
        """将对话框中的值持久化到数据库。需在 exec() 返回 Accepted 后调用。"""
        new_capacity = self.spin_capacity.value()
        if new_capacity != self._current_capacity:
            self._db.set_max_capacity(new_capacity)

        if self._profile and self._drive_prefix:
            self._profile["batch_size"] = self.spin_batch.value()
            self._db.save_system_profile(self._drive_prefix, self._profile)

        # 应用安全边界后写库
        patch_size = max(
            getattr(config, "AI_PATCH_SIZE_MIN", 128),
            min(
                self.spin_patch_size.value(),
                getattr(config, "AI_PATCH_SIZE_MAX", 4096),
            ),
        )
        stride = max(
            getattr(config, "AI_STRIDE_MIN", 64),
            min(self.spin_stride.value(), getattr(config, "AI_STRIDE_MAX", 4096)),
        )
        iou = max(
            float(getattr(config, "AI_NMS_IOU_THRESH_MIN", 0.01)),
            min(self.spin_iou.value(), float(getattr(config, "AI_NMS_IOU_THRESH_MAX", 1.0))),
        )
        conf = max(
            float(getattr(config, "AI_CONF_THRESH_MIN", 0.01)),
            min(self.spin_conf.value(), float(getattr(config, "AI_CONF_THRESH_MAX", 1.0))),
        )

        self._db.set_setting("ai_patch_size", patch_size)
        self._db.set_setting("ai_stride", stride)
        self._db.set_setting("ai_nms_iou_thresh", iou)
        self._db.set_setting("ai_conf_thresh", conf)
        self._db.set_setting("ai_model_type", self.combo_model_type.currentText())
        self._db.set_setting("ai_model_target_mpp", str(self.spin_mpp.value()))
        self._db.set_auto_tune_enabled(self.chk_auto_tune.isChecked())
        self._db.set_setting(
            "show_imported_heatmap", str(self.chk_imported_heatmap.isChecked())
        )
