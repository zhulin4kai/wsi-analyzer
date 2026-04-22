from PIL.ImageQt import ImageQt
from PySide6.QtCore import QMutex, QMutexLocker, QThread, QWaitCondition, Signal
from PySide6.QtGui import QImage

from utils.logger import logger


class RenderWorker(QThread):
    """
    独立于主界面的后台渲染线程。
    负责执行极其耗时的 OpenSlide IO 读取和 PIL 转 QImage 像素计算。
    """

    # 信号：传递 版本号, 图像数据, X坐标, Y坐标, 放大比例
    image_ready = Signal(int, QImage, int, int, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mutex = QMutex()
        self._cond = QWaitCondition()
        self._request = None
        self._is_running = True

    def request_render(self, slide_engine, x, y, level, w, h, scale, version):
        """主线程调用此方法，提交最新的渲染请求"""
        with QMutexLocker(self._mutex):
            # 永远只保留最新的一次请求，覆盖掉旧的未处理请求
            self._request = (slide_engine, x, y, level, w, h, scale, version)
            self._cond.wakeOne()  # 唤醒等待中的后台线程

    def run(self):
        """后台常驻循环"""
        while self._is_running:
            self._mutex.lock()
            # 如果没有任务，让线程睡眠，不占 CPU
            if self._request is None:
                self._cond.wait(self._mutex)

            if not self._is_running:
                self._mutex.unlock()
                break

            # 取出最新的任务，并清空槽位
            req = self._request
            self._request = None
            self._mutex.unlock()

            if req:
                slide_engine, x, y, level, w, h, scale, version = req
                try:
                    # 1. 耗时操作：底层 C 库读取图像
                    pil_img = slide_engine.read_region((x, y), level, (w, h))

                    # 2. 耗时操作：内存像素格式转换
                    # 必须调用 .copy() 切断与 PIL 的内存绑定，防止跨线程引发 C++ 崩溃
                    qimg = ImageQt(pil_img).copy()

                    # 3. 将成品图像发回给主 UI 线程
                    self.image_ready.emit(version, qimg, x, y, scale)
                except Exception as e:
                    logger.exception(f"RenderWorker 发生异常: {e}")

    def stop(self):
        """安全停止线程"""
        self._is_running = False
        with QMutexLocker(self._mutex):
            self._cond.wakeOne()
        self.wait()
