from PIL.ImageQt import ImageQt
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage

from utils.logger import logger


class RenderWorkerSignals(QObject):
    """用于 QRunnable 发射信号的辅助类"""

    image_ready = Signal(int, QImage, int, int, float)


class TileRenderTask(QRunnable):
    """
    独立的瓦片渲染任务。
    放入 QThreadPool 并发执行。
    """

    def __init__(
        self, slide_engine, x, y, level, w, h, scale, version, active_version_func
    ):
        super().__init__()
        self.slide_engine = slide_engine
        self.x = x
        self.y = y
        self.level = level
        self.w = w
        self.h = h
        self.scale = scale
        self.version = version
        self.active_version_func = active_version_func
        self.signals = RenderWorkerSignals()

    def run(self):
        # 如果任务在排队期间已经过期，直接丢弃
        if self.version < self.active_version_func():
            return

        try:
            # 1. 耗时操作：底层 C 库读取图像
            pil_img = self.slide_engine.read_region(
                (self.x, self.y), self.level, (self.w, self.h)
            )

            # 再次检查是否过期（读取耗时可能较长）
            if self.version < self.active_version_func():
                return

            # 2. 耗时操作：内存像素格式转换
            # 必须调用 .copy() 切断与 PIL 的内存绑定，防止跨线程引发 C++ 崩溃
            qimg = ImageQt(pil_img).copy()

            # 3. 将成品图像发回给主 UI 线程
            self.signals.image_ready.emit(
                self.version, qimg, self.x, self.y, self.scale
            )
        except Exception as e:
            logger.exception(f"TileRenderTask 发生异常: {e}")


class RenderWorker(QObject):
    """
    并发渲染管理器。
    负责接收渲染请求并将其分发给 QThreadPool。
    """

    # 信号：传递 版本号, 图像数据, X坐标, Y坐标, 放大比例
    image_ready = Signal(int, QImage, int, int, float)

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

    def request_render(self, slide_engine, x, y, level, w, h, scale, version):
        """主线程调用此方法，提交最新的渲染请求"""
        self.active_version = max(self.active_version, version)

        task = TileRenderTask(
            slide_engine, x, y, level, w, h, scale, version, self.get_active_version
        )
        task.signals.image_ready.connect(self.image_ready)

        # 将任务提交到线程池
        self.thread_pool.start(task)
