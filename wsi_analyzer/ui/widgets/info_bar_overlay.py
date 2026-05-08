from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QFontDatabase, QPainter, QPen
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
    WIDGET_W = 240
    WIDGET_H = 52

    def __init__(self, parent=None):
        super().__init__(parent)
        # 鼠标穿透 + 透明背景
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

        self._mpp_x = None  # 水平微米/像素
        self._mpp_y = None  # 垂直微米/像素
        self._path = None  # 当前切片路径，用于 ImageServer.sample_pixel() 采样
        self._level_0_dim = (0, 0)  # Level-0 dimensions for bounds checking

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

        # 跨平台等宽字体（QFontDatabase 自动匹配系统默认等宽字体）
        self._mono_font_9 = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        self._mono_font_9.setPointSize(9)
        self._mono_font_8 = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        self._mono_font_8.setPointSize(8)

    # ── 公共 API ─────────────────────────────────────────────────────────

    def load(self, metadata):
        """将叠加层绑定到新的切片，metadata 为 SlideMetadata 实例。"""
        self._path = metadata.path
        self._level_0_dim = metadata.level_0_dim
        mpp = metadata.mpp
        self._mpp_x = mpp[0] if mpp else None
        self._mpp_y = mpp[1] if mpp else None
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
        if not self._path:
            return
        try:
            from wsi_analyzer.infrastructure.imaging import ImageServer

            w, h = self._level_0_dim
            lx, ly = self._pending_lx, self._pending_ly
            if 0 <= lx < w and 0 <= ly < h:
                patch = ImageServer.instance().sample_pixel(self._path, lx, ly)
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

        w = self.width()
        pad = _PADDING
        swatch = _SWATCH_SIZE

        # 半透明背景
        p.fillRect(self.rect(), _BG_COLOR)

        # ── 坐标文字（上方，右侧留色块位置）──
        p.setPen(_FG_COLOR)
        p.setFont(self._mono_font_9)
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
            p.setFont(self._mono_font_8)
            p.setPen(_DIM_COLOR)
            p.drawText(
                pad, 28, w - 2 * pad, 20, Qt.AlignLeft | Qt.AlignVCenter, self._rgb_text
            )

        p.end()
