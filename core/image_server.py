import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from PySide6.QtGui import QImage

from .tile_cache import TileDataCache


@dataclass(frozen=True)
class SlideMetadata:
    """切片金字塔元数据的不可变快照，可安全跨线程传递。"""

    path: str
    level_0_dim: Tuple[int, int]
    level_count: int
    level_dimensions: List[Tuple[int, int]]
    level_downsamples: List[float]
    mpp: Optional[Tuple[float, float]]
    objective_power: Optional[float]

    def get_best_level_for_downsample(self, target_downsample: float) -> int:
        """返回降采样率不超过目标值的最高分辨率层级索引。"""
        best = 0
        for i, ds in enumerate(self.level_downsamples):
            if ds <= target_downsample + 1e-6:
                best = i
        return best


class SlidePool:
    """带引用计数的 WSIDataEngine LRU 引擎池。

    通过引用计数防止 use-after-free：即使引擎已被逻辑驱逐，
    在引用计数归零之前也不会真正关闭。
    """

    def __init__(self, max_engines: int = 3):
        self.max_engines = max_engines
        # OrderedDict 维护 LRU 顺序：队首 = 最旧，队尾 = 最近访问
        self._engines: OrderedDict = OrderedDict()
        self._refcounts: Dict[str, int] = {}
        # 已从 _engines 驱逐但仍被后台任务持有引用的路径
        self._pending_close: Set[str] = set()
        self._lock = threading.Lock()

    def acquire(self, path: str):
        """增加引用计数并返回引擎，必须与 release() 配对调用。"""
        with self._lock:
            if path in self._engines:
                self._engines.move_to_end(path)
                self._pending_close.discard(path)
                self._refcounts[path] = self._refcounts.get(path, 0) + 1
                return self._engines[path]

            if len(self._engines) >= self.max_engines:
                self._evict_one()

            from .slide_engine import WSIDataEngine

            engine = WSIDataEngine(path)
            self._engines[path] = engine
            self._refcounts[path] = 1
            return engine

    def release(self, path: str) -> None:
        """减少引用计数。若引擎处于待关闭状态且引用归零，则立即关闭。"""
        with self._lock:
            if path not in self._refcounts:
                return
            self._refcounts[path] = max(0, self._refcounts[path] - 1)
            if self._refcounts[path] == 0 and path in self._pending_close:
                self._do_close(path)

    def preload(self, path: str) -> None:
        """打开并缓存引擎，不增加引用计数（仅预热引擎池）。"""
        with self._lock:
            if path in self._engines:
                self._engines.move_to_end(path)
                return
            if len(self._engines) >= self.max_engines:
                self._evict_one()
            from .slide_engine import WSIDataEngine

            engine = WSIDataEngine(path)
            self._engines[path] = engine
            self._refcounts[path] = 0

    def _evict_one(self) -> None:
        """驱逐最旧的空闲引擎；若所有引擎均被引用，则标记最旧者为延迟关闭。调用方须持锁。"""
        for path in self._engines:
            if self._refcounts.get(path, 0) == 0:
                self._do_close(path)
                return
        # 所有引擎均有引用；标记最旧者待引用归零后关闭
        oldest = next(iter(self._engines))
        self._pending_close.add(oldest)

    def _do_close(self, path: str) -> None:
        """从池中移除并关闭引擎。调用方须持锁。"""
        engine = self._engines.pop(path, None)
        self._refcounts.pop(path, None)
        self._pending_close.discard(path)
        if engine:
            engine.close()

    def close_all(self) -> None:
        """无条件关闭所有引擎，在应用退出时调用。"""
        with self._lock:
            for engine in self._engines.values():
                engine.close()
            self._engines.clear()
            self._refcounts.clear()
            self._pending_close.clear()


class ImageServer:
    """进程级单例，WSI 数据访问的统一入口。

    协调 SlidePool（引擎生命周期）、TileDataCache（跨切片像素缓存）
    和元数据存储。GUI 组件不应直接持有 WSIDataEngine 引用；
    对于生命周期超过单次调用的访问，须使用 acquire_engine/release_engine。
    """

    _instance: Optional["ImageServer"] = None
    _instance_lock = threading.Lock()

    def __init__(self):
        self._slide_pool = SlidePool(max_engines=3)
        self._tile_cache = TileDataCache(max_capacity=2000)
        self._metadata_store: Dict[str, SlideMetadata] = {}
        self._meta_lock = threading.Lock()

    @classmethod
    def instance(cls) -> "ImageServer":
        """获取进程级单例实例（双重检查锁定）。"""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = ImageServer()
        return cls._instance

    # ------------------------------------------------------------------
    # 元数据
    # ------------------------------------------------------------------

    def get_metadata(self, path: str) -> SlideMetadata:
        """返回缓存的元数据，首次访问时自动打开引擎读取后关闭。"""
        with self._meta_lock:
            if path in self._metadata_store:
                return self._metadata_store[path]

        engine = self._slide_pool.acquire(path)
        try:
            slide = engine.slide
            metadata = SlideMetadata(
                path=path,
                level_0_dim=engine.level_0_dim,
                level_count=slide.level_count,
                level_dimensions=list(slide.level_dimensions),
                level_downsamples=list(slide.level_downsamples),
                mpp=engine.get_mpp(),
                objective_power=engine.get_objective_power(),
            )
        finally:
            self._slide_pool.release(path)

        with self._meta_lock:
            self._metadata_store[path] = metadata
        return metadata

    # ------------------------------------------------------------------
    # 瓦片像素数据
    # ------------------------------------------------------------------

    def get_tile(self, path: str, level: int, col: int, row: int) -> Optional[QImage]:
        """查询跨切片瓦片缓存，未命中返回 None。"""
        return self._tile_cache.get(path, level, col, row)

    def cache_tile(
        self, path: str, level: int, col: int, row: int, qimg: QImage
    ) -> None:
        """将已解码的瓦片写入跨切片缓存，线程安全。"""
        self._tile_cache.put(path, level, col, row, qimg)

    # ------------------------------------------------------------------
    # 引擎借用（适用于长生命周期任务）
    # ------------------------------------------------------------------

    def acquire_engine(self, path: str):
        """增加引用计数并返回引擎，调用方必须调用 release_engine()。"""
        return self._slide_pool.acquire(path)

    def release_engine(self, path: str) -> None:
        """减少引用计数，若引擎处于待驱逐状态则可能触发关闭。"""
        self._slide_pool.release(path)

    def preload_engine(self, path: str) -> None:
        """打开并缓存引擎，不增加引用计数（仅预热引擎池，降低首次访问延迟）。"""
        self._slide_pool.preload(path)

    # ------------------------------------------------------------------
    # 便捷接口（内部自动 acquire/release）
    # ------------------------------------------------------------------

    def get_thumbnail(self, path: str, level_from_last: int = 1):
        """借用引擎获取缩略图，返回 (PIL.Image, 降采样系数)。"""
        engine = self._slide_pool.acquire(path)
        try:
            return engine.get_thumbnail(level_from_last=level_from_last)
        finally:
            self._slide_pool.release(path)

    def sample_pixel(self, path: str, lx: int, ly: int):
        """借用引擎在 Level-0 坐标处采样单像素，返回 1x1 PIL.Image。"""
        engine = self._slide_pool.acquire(path)
        try:
            return engine.read_region((lx, ly), 0, (1, 1))
        finally:
            self._slide_pool.release(path)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """关闭所有引擎并清空缓存，在应用退出时调用。"""
        self._slide_pool.close_all()
        self._tile_cache.clear()
