from PIL.ImageQt import ImageQt
from PySide6.QtCore import QThread, Signal

from wsi_analyzer.infrastructure.logging import logger


class ThumbnailWorker(QThread):
    thumb_ready = Signal(int, object)

    def __init__(self, tasks: list, thumb_w: int, thumb_h: int):
        super().__init__()
        self.tasks = tasks
        self.thumb_w = thumb_w
        self.thumb_h = thumb_h
        self._cancelled = False

    def run(self):
        from PIL import Image

        from wsi_analyzer.infrastructure.imaging import ImageServer

        resample = getattr(Image, "Resampling", Image).LANCZOS

        for index, path in self.tasks:
            if self._cancelled:
                break
            try:
                thumb_img, _ = ImageServer.instance().get_thumbnail(
                    path, level_from_last=1
                )
                thumb_img.thumbnail((self.thumb_w, self.thumb_h), resample)
                qimg = ImageQt(thumb_img).copy()
                self.thumb_ready.emit(index, qimg)
            except Exception as e:
                logger.error(f"ThumbnailWorker 缩略图生成失败 [{path}]: {e}")

    def cancel(self):
        self._cancelled = True
