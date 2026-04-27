from PIL.ImageQt import ImageQt
from PySide6.QtCore import QThread, Signal

from core.slide_engine import WSIDataEngine
from utils import logger


class ThumbnailWorker(QThread):
    """
    图像列表缩略图异步加载线程。
    按序打开 WSI，生成预览缩略图后发射信号，不阻塞主线程。
    """

    # 信号：(列表索引, QImage 缩略图)
    thumb_ready = Signal(int, object)

    def __init__(self, tasks: list, thumb_w: int, thumb_h: int):
        """
        :param tasks: [(index, path), ...] 待处理任务列表
        :param thumb_w: 缩略图目标宽度（像素）
        :param thumb_h: 缩略图目标高度（像素）
        """
        super().__init__()
        self.tasks = tasks
        self.thumb_w = thumb_w
        self.thumb_h = thumb_h
        self._cancelled = False

    def run(self):
        from PIL import Image

        resample = getattr(Image, "Resampling", Image).LANCZOS

        for index, path in self.tasks:
            if self._cancelled:
                break

            engine = None
            try:
                engine = WSIDataEngine(path)
                thumb_img, _ = engine.get_thumbnail(level_from_last=1)

                # 等比缩放至目标尺寸
                thumb_img.thumbnail((self.thumb_w, self.thumb_h), resample)

                # 转为 QImage 并深拷贝，防止 PIL Image 被回收后指针悬空
                qimg = ImageQt(thumb_img).copy()
                self.thumb_ready.emit(index, qimg)

            except Exception as e:
                logger.error(f"ThumbnailWorker 缩略图生成失败 [{path}]: {e}")

            finally:
                if engine:
                    engine.close()

    def cancel(self):
        """中断缩略图加载任务"""
        self._cancelled = True
