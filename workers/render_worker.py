from PIL.ImageQt import ImageQt
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage

from utils.logger import logger


class RenderWorkerSignals(QObject):
    """用于 QRunnable 发射信号的辅助类"""

    # 信号：传递 版本号, level, col, row, 图像数据, X坐标, Y坐标, 放大比例
    image_ready = Signal(int, int, int, int, QImage, int, int, float)


class TileRenderTask(QRunnable):
    """
    独立的瓦片渲染任务。
    放入 QThreadPool 并发执行。
    """

    def __init__(
        self,
        slide_engine,
        level,
        col,
        row,
        x,
        y,
        w,
        h,
        scale,
        version,
        active_version_func,
    ):
        super().__init__()
        self.slide_engine = slide_engine
        self.level = level
        self.col = col
        self.row = row
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.scale = scale
        self.version = version
        self.active_version_func = active_version_func
        self.signals = RenderWorkerSignals()

    def run(self):
        # 检查任务是否过期
        if self.version < self.active_version_func():
            return

        try:
            # 1. 读取图像区域
            pil_img = self.slide_engine.read_region(
                (self.x, self.y), self.level, (self.w, self.h)
            )

            # 读取后再次检查任务是否过期
            if self.version < self.active_version_func():
                return

            # 2. 像素格式转换
            # 使用 .copy() 解除与 PIL 的内存绑定，避免跨线程异常
            qimg = ImageQt(pil_img).copy()

            # 3. 发送图像数据信号
            self.signals.image_ready.emit(
                self.version,
                self.level,
                self.col,
                self.row,
                qimg,
                self.x,
                self.y,
                self.scale,
            )
        except Exception as e:
            logger.exception(f"TileRenderTask 发生异常: {e}")


class RenderWorker(QObject):
    """
    并发渲染管理器。
    负责接收渲染请求并将其分发给 QThreadPool。
    """

    # 信号：传递 版本号, level, col, row, 图像数据, X坐标, Y坐标, 放大比例
    image_ready = Signal(int, int, int, int, QImage, int, int, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread_pool = QThreadPool.globalInstance()
        self.active_version = 0

    def start(self):
        """兼容旧接口"""
        pass

    def stop(self):
        """清理未执行的任务"""
        self.thread_pool.clear()

    def get_active_version(self):
        return self.active_version

    def request_render(self, slide_engine, level, col, row, x, y, w, h, scale, version):
        """提交渲染请求"""
        self.active_version = max(self.active_version, version)

        task = TileRenderTask(
            slide_engine,
            level,
            col,
            row,
            x,
            y,
            w,
            h,
            scale,
            version,
            self.get_active_version,
        )
        task.signals.image_ready.connect(self.image_ready)

        # 将任务提交到线程池
        self.thread_pool.start(task)
