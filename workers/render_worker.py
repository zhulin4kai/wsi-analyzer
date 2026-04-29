from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from .tile_scheduler import PriorityTileScheduler, TileSchedulerSignals


class RenderWorker(QObject):
    """
    基于 PriorityTileScheduler 的并发瓦片渲染协调器。
    作为调度器的薄适配层：对外保持与原有 ``image_ready`` 信号相同的接口，
    内部将所有任务分发委托给 ``PriorityTileScheduler``。
    """

    image_ready = Signal(str, int, int, int, int, QImage, int, int, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        # TileSchedulerSignals 必须在主线程创建
        self._signals = TileSchedulerSignals()
        self._signals.image_ready.connect(self.image_ready)
        self._scheduler = PriorityTileScheduler(self._signals, num_workers=4)

    def start(self) -> None:
        """空操作：调度器线程已在 __init__ 中启动。"""
        pass

    def stop(self) -> None:
        """清空队列中所有待处理任务（正在执行的任务不受影响）。"""
        self._scheduler.cancel_all()

    def shutdown(self) -> None:
        """停止所有调度器工作线程，在应用退出时调用一次。"""
        self._scheduler.shutdown()

    def get_active_version(self) -> int:
        return self._scheduler.get_active_version()

    def set_version(self, version: int) -> None:
        """推进活跃渲染版本号，使旧版本任务被跳过。"""
        self._scheduler.set_version(version)

    def request_render(
        self,
        path: str,
        level: int,
        col: int,
        row: int,
        x: int,
        y: int,
        w: int,
        h: int,
        scale: float,
        version: int,
        priority: float = 0.0,
    ) -> None:
        self._scheduler.set_version(version)
        self._scheduler.submit(
            priority, path, level, col, row, x, y, w, h, scale, version
        )
