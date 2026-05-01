import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from config import (
    HUD_BG_COLOR,
    HUD_DIM_COLOR,
    HUD_FG_COLOR,
    HUD_PADDING,
    HUD_SCALE_BAR_TARGET_PX,
)

# ── 视觉常量（从 config 构造）────────────────────────────────────────────
_TARGET_BAR_PX = HUD_SCALE_BAR_TARGET_PX
_PADDING = HUD_PADDING
_BG_COLOR = QColor(*HUD_BG_COLOR)
_FG_COLOR = QColor(*HUD_FG_COLOR)
_DIM_COLOR = QColor(*HUD_DIM_COLOR)


def _nice_value(value: float) -> float:
    """将任意正值规整到最近的 1/2/5 × 10^n 档位，用于比例尺取整。"""
    if value <= 0:
        return 1.0
    exp = math.floor(math.log10(value))
    mag = 10**exp
    for factor in (1, 2, 5, 10, 20, 50):
        candidate = float(factor * mag)
        if candidate >= value * 0.5:
            return candidate
    return float(value)


class ScaleBarOverlay(QWidget):
    """
    左下角比例尺 HUD 叠加层。

    使用方式：
        overlay = ScaleBarOverlay(viewer_widget)
        overlay.load(mpp_x, mpp_y, objective_power)
        viewer.zoom_changed.connect(overlay.on_zoom_changed)
    """

    WIDGET_W = 200
    WIDGET_H = 38

    def __init__(self, parent=None):
        super().__init__(parent)
        # 鼠标穿透 + 透明背景，不遮挡交互
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

        self._mpp_x = None  # 微米/像素（Level-0）
        self._current_scale = 1.0  # view.transform().m11()

        self._bar_px = 0  # 实际比例尺屏幕宽度（像素）
        self._bar_label = ""  # 比例尺文字，如 "800 μm"

        self.setFixedSize(self.WIDGET_W, self.WIDGET_H)
        self.setVisible(False)

        # 跨平台默认字体
        self._font_9 = QFont()
        self._font_9.setPointSize(9)
        self._font_8 = QFont()
        self._font_8.setPointSize(8)

    # ── 公共 API ─────────────────────────────────────────────────────────

    def load(self, mpp_x, mpp_y):
        """
        加载新切片时由主窗口调用，传入物理分辨率元数据。

        :param mpp_x: 水平方向微米/像素，无元数据时传 None
        :param mpp_y: 垂直方向微米/像素，无元数据时传 None（当前不使用）
        """
        self._mpp_x = mpp_x
        self.setVisible(True)

    def on_zoom_changed(self, scale: float):
        """连接 WSIView.zoom_changed 信号的槽函数。"""
        self._current_scale = scale
        self._update_labels()
        self.update()

    # ── 内部计算 ──────────────────────────────────────────────────────────

    def _update_labels(self):
        self._calc_scale_bar()

    def _calc_scale_bar(self):
        """根据当前缩放和 MPP 计算比例尺的像素宽度和文字标签。"""
        if not self._mpp_x or self._mpp_x <= 0:
            self._bar_px = 0
            self._bar_label = ""
            return

        # 屏幕像素数 / 微米 = current_scale / mpp_x
        # ∴ raw_um = 目标像素宽 × mpp_x / current_scale
        raw_um = _TARGET_BAR_PX * self._mpp_x / self._current_scale
        nice_um = _nice_value(raw_um)
        self._bar_px = max(1, int(nice_um * self._current_scale / self._mpp_x))

        # 防止比例尺溢出控件宽度
        max_bar = self.WIDGET_W - 2 * _PADDING
        if self._bar_px > max_bar:
            self._bar_px = max_bar

        # 格式化标签
        if nice_um >= 1_000:
            mm_val = nice_um / 1000
            self._bar_label = f"{mm_val:.3g} mm"
        else:
            self._bar_label = f"{nice_um:.3g} μm"

    # ── 绘制 ──────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        if not self.isVisible():
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        w = self.width()
        pad = _PADDING

        # 半透明背景
        p.fillRect(self.rect(), _BG_COLOR)

        # ── 比例尺图形（仅在有 MPP 数据时绘制）──
        if self._bar_px > 0:
            bar_y = 14
            tick_top = bar_y - 5
            tick_bot = bar_y + 5

            pen = QPen(_FG_COLOR, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            p.setPen(pen)

            # 水平主线
            p.drawLine(pad, bar_y, pad + self._bar_px, bar_y)
            # 左端刻度
            p.drawLine(pad, tick_top, pad, tick_bot)
            # 右端刻度
            p.drawLine(pad + self._bar_px, tick_top, pad + self._bar_px, tick_bot)

            # 比例尺标签（居中在线下方）
            p.setFont(self._font_9)
            p.setPen(_DIM_COLOR)
            p.drawText(
                pad, bar_y + 5, self._bar_px, 16, Qt.AlignCenter, self._bar_label
            )
        else:
            # 无 MPP 元数据时提示
            p.setFont(self._font_8)
            p.setPen(_DIM_COLOR)
            p.drawText(
                pad, 8, w - 2 * pad, 20, Qt.AlignLeft | Qt.AlignVCenter, "无标定信息"
            )

        p.end()
