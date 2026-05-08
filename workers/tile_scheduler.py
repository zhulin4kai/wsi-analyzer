import heapq
import threading

from PIL.ImageQt import ImageQt
from PySide6.QtCore import QObject, QRunnable, Signal
from PySide6.QtGui import QImage

from wsi_analyzer.infrastructure.logging.logger import logger

class TileSchedulerSignals(QObject):
    """在主线程创建一次；由后台守护线程发射。"""
    image_ready = Signal(str, int, int, int, int, QImage, int, int, float)

class ScheduledTileTask:
    """支持 heapq 优先级排序的瓦片渲染任务。"""

    __slots__ = (
        "priority",
        "seq",
        "path",
        "level",
        "col",
        "row",
        "x",
        "y",
        "w",
        "h",
        "scale",
        "version",
        "_active_version_func",
        "signals",
    )

    def __init__(
        self,
        priority: float,
        seq: int,
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
        active_version_func,
        signals: TileSchedulerSignals,
    ):
        self.priority = priority
        self.seq = seq
        self.path = path
        self.level = level
        self.col = col
        self.row = row
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.scale = scale
        self.version = version
        self._active_version_func = active_version_func
        self.signals = signals

    def __lt__(self, other: "ScheduledTileTask") -> bool:
        # heapq 是最小堆；(priority, seq) 越小越优先执行
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.seq < other.seq

    def run(self) -> None:
        if self.version < self._active_version_func():
            return

        from core import ImageServer

        server = ImageServer.instance()
        engine = None
        try:
            engine = server.acquire_engine(self.path)
            pil_img = engine.read_region((self.x, self.y), self.level, (self.w, self.h))

            if self.version < self._active_version_func():
                return

            qimg = ImageQt(pil_img).copy()
            server.cache_tile(self.path, self.level, self.col, self.row, qimg)
            self.signals.image_ready.emit(
                self.path,
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
            logger.exception(f"ScheduledTileTask 执行出错 (path={self.path!r}): {e}")
        finally:
            if engine is not None:
                server.release_engine(self.path)

class PriorityTileScheduler:
    """固定线程数的优先级瓦片调度器。

    使用二叉堆（heapq）进行优先级排序，使用固定数量的守护线程作为消费者。

    优先级分值：数值越小，优先级越高。
    调用方应按以下公式计算：distance(瓦片中心, 视口中心) / 层级降采样率

    Args:
        signals:     在主线程创建的共享 ``TileSchedulerSignals`` QObject。
        num_workers: 消费者线程数量（默认 4）。
    """

    MAX_QUEUE_SIZE: int = 2000

    def __init__(self, signals: TileSchedulerSignals, num_workers: int = 4):
        self._signals = signals
        self._queue: list = []  # heapq，由 _cond 保护
        self._seq: int = 0  # 单调递增的任务序列号
        self._active_version: int = 0
        self._cond = threading.Condition(threading.Lock())
        self._shutdown_event = threading.Event()
        self._workers: list[threading.Thread] = []
        for _ in range(num_workers):
            t = threading.Thread(target=self._worker_loop, daemon=True)
            t.start()
            self._workers.append(t)

    def get_active_version(self) -> int:
        return self._active_version

    def set_version(self, version: int) -> None:
        """推进活跃版本号；版本号较旧的任务将被跳过。"""
        if version > self._active_version:
            self._active_version = version

    def submit(
        self,
        priority: float,
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
    ) -> None:
        """将瓦片渲染任务加入优先级队列。

        若清理过期任务后队列仍满，则静默丢弃该任务（溢出保护，防止内存无限增长）。
        """
        with self._cond:
            if len(self._queue) >= self.MAX_QUEUE_SIZE:
                self._purge_stale_locked()
                if len(self._queue) >= self.MAX_QUEUE_SIZE:
                    return  # 队列仍满，丢弃低优先级的新任务
            self._seq += 1
            task = ScheduledTileTask(
                priority=priority,
                seq=self._seq,
                path=path,
                level=level,
                col=col,
                row=row,
                x=x,
                y=y,
                w=w,
                h=h,
                scale=scale,
                version=version,
                active_version_func=self.get_active_version,
                signals=self._signals,
            )
            heapq.heappush(self._queue, task)
            self._cond.notify()

    def cancel_all(self) -> None:
        """清空队列中所有待处理任务，不停止工作线程。"""
        with self._cond:
            self._queue.clear()

    def shutdown(self) -> None:
        """停止所有工作线程，在应用退出时调用一次。"""
        self._shutdown_event.set()
        with self._cond:
            self._cond.notify_all()
        for t in self._workers:
            t.join(timeout=2.0)
        self._workers.clear()

    def _purge_stale_locked(self) -> None:
        """移除版本号小于活跃版本的过期任务。调用方须持锁。"""
        v = self._active_version
        self._queue = [t for t in self._queue if t.version >= v]
        heapq.heapify(self._queue)

    def _worker_loop(self) -> None:
        """消费者线程主循环。"""
        while not self._shutdown_event.is_set():
            task: ScheduledTileTask | None = None
            with self._cond:
                while not self._queue and not self._shutdown_event.is_set():
                    self._cond.wait(timeout=0.1)
                if self._queue:
                    task = heapq.heappop(self._queue)
            if task is not None and task.version >= self._active_version:
                task.run()

class PreloadTask(QRunnable):
    """预热 SlidePool 的 QRunnable 任务，不增加引擎引用计数。

    在 ``QThreadPool.globalInstance()`` 以低优先级运行，不与前台瓦片渲染竞争 I/O。

    用法::

        from PySide6.QtCore import QThreadPool
        QThreadPool.globalInstance().start(PreloadTask(path), -1)  # priority=-1
    """

    def __init__(self, path: str):
        super().__init__()
        self.path = path
        self.setAutoDelete(True)

    def run(self) -> None:
        import os

        if not os.path.exists(self.path):
            return
        try:
            from core import ImageServer

            ImageServer.instance().preload_engine(self.path)
        except Exception as e:
            logger.warning(f"PreloadTask 预热失败 {self.path!r}: {e}")
