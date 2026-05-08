from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QWidget

from wsi_analyzer.config.config import (
    HUD_MAG_DEFAULT_OBJECTIVE,
    HUD_MAG_MAX,
    HUD_MAG_WIDGET_H,
    HUD_MAG_WIDGET_W,
)


class MagnificationWidget(QWidget):

    zoom_to_scale = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._objective_power = None  # 来自切片元数据，None 时使用默认值
        self._current_scale = 0.0  # WSIView.transform().m11()
        self._editing = False  # 当前是否处于编辑模式

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 显示标签（正常模式）──────────────────────────────────────────
        self._label = QLabel("─ ×")
        self._label.setFixedSize(HUD_MAG_WIDGET_W, HUD_MAG_WIDGET_H)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.installEventFilter(self)

        # ── 编辑输入框（编辑模式，默认隐藏）────────────────────────────
        self._editor = QLineEdit()
        self._editor.setFixedSize(HUD_MAG_WIDGET_W, HUD_MAG_WIDGET_H)
        self._editor.setAlignment(Qt.AlignCenter)
        self._editor.setVisible(False)
        self._editor.installEventFilter(self)

        layout.addWidget(self._label)
        layout.addWidget(self._editor)

        # returnPressed 负责"按 Enter 确认"，FocusOut 通过 eventFilter 处理
        self._editor.returnPressed.connect(self._confirm_edit)

        self.setFixedSize(HUD_MAG_WIDGET_W, HUD_MAG_WIDGET_H)

    # ── 公共 API ─────────────────────────────────────────────────────────

    def load(self, objective_power):
        self._objective_power = objective_power
        self._refresh_label()

    def reset(self):
        """切换切片前或关闭切片时重置控件到初始占位状态。"""
        self._objective_power = None
        self._current_scale = 0.0
        self._label.setText("─ ×")
        self._exit_edit_mode(apply=False)

    def on_zoom_changed(self, scale: float):
        self._current_scale = scale
        if not self._editing:
            self._refresh_label()

    # ── 内部计算 ──────────────────────────────────────────────────────────

    def _obj(self) -> float:
        """返回当前有效的物镜倍率（优先元数据，否则使用默认值）。"""
        return (
            self._objective_power
            if self._objective_power
            else HUD_MAG_DEFAULT_OBJECTIVE
        )

    def _effective_mag(self) -> float:
        """计算当前等效放大倍率：objective_power × m11。"""
        return self._obj() * self._current_scale

    def _refresh_label(self):
        """根据当前缩放刷新只读标签文字。"""
        if self._current_scale <= 0:
            self._label.setText("─ ×")
            return
        mag = self._effective_mag()
        self._label.setText(f"{mag:.2f} ×")

    # ── 编辑模式管理 ──────────────────────────────────────────────────────

    def _enter_edit_mode(self):
        """切换到编辑模式：显示输入框并选中全部文字。"""
        if self._current_scale <= 0:
            return  # 未加载切片时不允许编辑
        self._editing = True
        mag = self._effective_mag()
        self._editor.setText(f"{mag:.2f}")
        self._label.setVisible(False)
        self._editor.setVisible(True)
        self._editor.selectAll()
        self._editor.setFocus()

    def _confirm_edit(self):
        """
        解析输入值，校验范围，发射 zoom_to_scale 信号，退出编辑模式。
        无效输入时静默忽略，保持原倍率。
        """
        if not self._editing:
            return

        text = self._editor.text().strip().rstrip("×xX ").strip()
        try:
            target_mag = float(text)
            obj = self._obj()
            # 硬性限制：不超过 HUD_MAG_MAX，也不超过物镜倍率本身
            max_mag = min(HUD_MAG_MAX, obj)
            target_mag = max(0.01, min(target_mag, max_mag))
            # 换算为 m11 scale，再次硬性限制在 [1e-4, 1.0]
            target_scale = max(1e-4, min(target_mag / obj, 1.0))
            self.zoom_to_scale.emit(target_scale)
        except ValueError:
            pass  # 非法输入，静默恢复

        self._exit_edit_mode(apply=True)

    def _exit_edit_mode(self, apply: bool = True):
        if not self._editing and apply:
            return
        self._editing = False  # 必须先置 False，防止 FocusOut 二次触发
        self._editor.setVisible(False)
        self._label.setVisible(True)
        if apply:
            self._refresh_label()

    # ── 事件过滤器 ────────────────────────────────────────────────────────

    def eventFilter(self, watched, event):
        # ── 标签：双击进入编辑模式 ──────────────────────────────────────
        if watched is self._label:
            if event.type() == QEvent.Type.MouseButtonDblClick:
                if event.button() == Qt.LeftButton:
                    self._enter_edit_mode()
                    return True

        # ── 输入框：Esc 取消 / 失焦确认 ─────────────────────────────────
        elif watched is self._editor:
            if event.type() == QEvent.Type.KeyPress:
                if event.key() == Qt.Key_Escape:
                    self._exit_edit_mode(apply=False)
                    return True
            elif event.type() == QEvent.Type.FocusOut:
                # returnPressed 已将 _editing 置 False，此处不会二次触发
                if self._editing:
                    self._confirm_edit()
                # 返回 False：让 Qt 继续处理焦点转移，避免事件循环阻塞
                return False

        return super().eventFilter(watched, event)
