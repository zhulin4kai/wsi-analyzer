"""
坐标与色彩信息叠加层（右下角）
显示：鼠标所在位置的 Level-0 物理坐标（μm）+ 像素 RGB 色彩
连接 WSIView.mouse_scene_pos_changed 信号后自动刷新。
RGB 读取使用 OpenSlide 精确采样，并附加 150ms 防抖避免 I/O 过载。
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from config import (
    HUD_BG_COLOR,
    HUD_DIM_COLOR,
    HUD_FG_COLOR,
    HUD_INFO_RGB_DEBOUNCE_MS,
    HUD_INFO_SWATCH_SIZE,
    HUD_PADDING,
)

# ── 视觉常量（由 config.py 统一管理，此处构造 QColor 对象）────────────
_BG_COLOR = QColor(*HUD_BG_COLOR)
_FG_COLOR = QColor(*HUD_FG_COLOR)
_DIM_COLOR = QColor(*HUD_DIM_COLOR)
_PADDING = HUD_PADDING
_SWATCH_SIZE = HUD_INFO_SWATCH_SIZE
_RGB_DEBOUNCE_MS = HUD_INFO_RGB_DEBOUNCE_MS


class InfoBarOverlay(QWidget):
    """
    右下角坐标/色彩 HUD 叠加层。

    使用方式：
        overlay = InfoBarOverlay(viewer_widget)
        overlay.load(slide_engine, mpp_x, mpp_y)
        viewer.mouse_scene_pos_changed.connect(overlay.on_mouse_moved)
    """

    WIDGET_W = 240
    WIDGET_H = 52

    def __init__(self, parent=None):
        super().__init__(parent)
        # 鼠标穿透 + 透明背景
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

        self._mpp_x = None  # 水平微米/像素
        self._mpp_y = None  # 垂直微米/像素
        self._slide_engine = None  # WSIDataEngine 实例，用于精确 RGB 采样

        self._coord_text = ""  # 坐标文字
        self._rgb_text = ""  # RGB 文字，如 "R 187  G 110  B 184"
        self._rgb_color = QColor(0, 0, 0, 0)  # 透明 = 暂无色彩数据

        # 待采样的 Level-0 坐标（防抖后使用）
        self._pending_lx = 0
        self._pending_ly = 0

        # RGB 采样防抖定时器
        self._rgb_timer = QTimer(self)
        self._rgb_timer.setSingleShot(True)
        self._rgb_timer.setInterval(_RGB_DEBOUNCE_MS)
        self._rgb_timer.timeout.connect(self._sample_rgb)

        self.setFixedSize(self.WIDGET_W, self.WIDGET_H)
        self.setVisible(False)

    # ── 公共 API ─────────────────────────────────────────────────────────

    def load(self, slide_engine, mpp_x, mpp_y):
        """
        加载新切片时由主窗口调用，重置状态并绑定数据引擎。

        :param slide_engine: WSIDataEngine 实例
        :param mpp_x: 水平方向微米/像素，无元数据时传 None
        :param mpp_y: 垂直方向微米/像素，无元数据时传 None
        """
        self._slide_engine = slide_engine
        self._mpp_x = mpp_x
        self._mpp_y = mpp_y
        # 切换切片时清空旧数据
        self._coord_text = ""
        self._rgb_text = ""
        self._rgb_color = QColor(0, 0, 0, 0)
        self.setVisible(True)

    def on_mouse_moved(self, scene_x: float, scene_y: float):
        """连接 WSIView.mouse_scene_pos_changed 信号的槽函数。"""
        if not self.isVisible():
            return

        # ── 计算物理坐标文字 ──
        if self._mpp_x and self._mpp_y:
            phy_x = scene_x * self._mpp_x
            phy_y = scene_y * self._mpp_y
            self._coord_text = f"{phy_x:.2f},  {phy_y:.2f}  μm"
        else:
            self._coord_text = f"{int(scene_x)},  {int(scene_y)}  px"

        # ── 启动 RGB 采样防抖 ──
        self._pending_lx = int(scene_x)
        self._pending_ly = int(scene_y)
        self._rgb_timer.start()

        self.update()

    # ── 内部 ──────────────────────────────────────────────────────────────

    def _sample_rgb(self):
        """防抖后由 QTimer 触发，精确读取 Level-0 像素色彩。"""
        if not self._slide_engine:
            return
        try:
            w, h = self._slide_engine.level_0_dim
            lx, ly = self._pending_lx, self._pending_ly
            if 0 <= lx < w and 0 <= ly < h:
                patch = self._slide_engine.read_region((lx, ly), 0, (1, 1))
                r, g, b = patch.convert("RGB").getpixel((0, 0))
                self._rgb_text = f"R {r:3d}  G {g:3d}  B {b:3d}"
                self._rgb_color = QColor(r, g, b)
                self.update()
        except Exception:
            pass

    # ── 绘制 ──────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        if not self.isVisible() or not self._coord_text:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        w, h = self.width(), self.height()
        pad = _PADDING
        swatch = _SWATCH_SIZE

        # 半透明背景
        p.fillRect(self.rect(), _BG_COLOR)

        # ── 坐标文字（上方，右侧留色块位置）──
        p.setPen(_FG_COLOR)
        p.setFont(QFont("Consolas", 9))
        text_w = w - 2 * pad - swatch - 8
        p.drawText(pad, 2, text_w, 22, Qt.AlignLeft | Qt.AlignVCenter, self._coord_text)

        # ── RGB 预览色块（右上角）──
        if self._rgb_color.alpha() > 0:
            cx = w - pad - swatch
            cy = 9
            p.setBrush(QBrush(self._rgb_color))
            p.setPen(QPen(QColor(150, 150, 150), 1))
            p.drawRoundedRect(cx, cy, swatch, swatch, 3, 3)

        # ── RGB 文字（下方）──
        if self._rgb_text:
            p.setFont(QFont("Consolas", 8))
            p.setPen(_DIM_COLOR)
            p.drawText(
                pad, 28, w - 2 * pad, 20, Qt.AlignLeft | Qt.AlignVCenter, self._rgb_text
            )

        p.end()
