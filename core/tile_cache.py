import threading
from collections import OrderedDict
from typing import Any, List, Optional, Tuple

from PySide6.QtGui import QImage


class TileLRUCache:
    def __init__(self, max_capacity: int = 1024):
        """
        初始化 LRU 缓存池。
        :param max_capacity: 缓存图块的最大数量
        """
        self.max_capacity = max_capacity
        # OrderedDict 记录元素插入顺序，便于 LRU 淘汰
        self._cache: OrderedDict[Tuple[int, int, int], Any] = OrderedDict()

    def get(self, key: Tuple[int, int, int]) -> Optional[Any]:
        """
        获取缓存中的瓦片。
        若存在，则将其移动至末尾（标记为最近使用）并返回。
        :param key: 瓦片唯一标识，通常为 (level, col, row)
        :return: 缓存的瓦片对象（通常是 QGraphicsPixmapItem），不存在则返回 None
        """
        if key not in self._cache:
            return None
        self._cache.move_to_end(key)
        return self._cache[key]

    def put(self, key: Tuple[int, int, int], item: Any) -> Optional[Any]:
        """
        存入新的瓦片。达到容量上限时移除最旧的图块。
        :param key: 瓦片唯一标识 (level, col, row)
        :param item: 要缓存的图块对象
        :return: 被淘汰的图块对象，若无淘汰则返回 None
        """
        evicted_item = None
        if key in self._cache:
            # 已存在则更新值并移动到末尾
            self._cache.move_to_end(key)
        self._cache[key] = item
        # 超出容量时淘汰最久未访问的元素
        if len(self._cache) > self.max_capacity:
            _, evicted_item = self._cache.popitem(last=False)
        return evicted_item

    def contains(self, key: Tuple[int, int, int]) -> bool:
        """
        判断瓦片是否在缓存中（仅探测，不改变缓存顺序）。
        """
        return key in self._cache

    def clear(self) -> List[Any]:
        """
        清空所有缓存。
        :return: 缓存中所有图块对象的列表
        """
        items = list(self._cache.values())
        self._cache.clear()
        return items

    def __len__(self) -> int:
        """获取当前缓存的瓦片数量"""
        return len(self._cache)


class TileDataCache:
    """
    线程安全的跨切片 LRU 像素数据缓存（存储 QImage）。

    与 TileLRUCache（存储 QGraphicsPixmapItem，切换切片时清空）不同，
    本缓存跨切片保留，重新访问同一切片时可跳过磁盘 I/O。
    """

    def __init__(self, max_capacity: int = 2000):
        self.max_capacity = max_capacity
        self._cache: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def get(self, path: str, level: int, col: int, row: int) -> Optional[QImage]:
        """获取指定瓦片的 QImage，未命中则返回 None。"""
        key = (path, level, col, row)
        with self._lock:
            if key not in self._cache:
                return None
            self._cache.move_to_end(key)
            return self._cache[key]

    def put(self, path: str, level: int, col: int, row: int, qimg: QImage) -> None:
        """写入已解码的瓦片像素数据，超出容量时淘汰最旧条目。"""
        key = (path, level, col, row)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = qimg
            if len(self._cache) > self.max_capacity:
                self._cache.popitem(last=False)

    def clear(self) -> None:
        """清空全部缓存条目。"""
        with self._lock:
            self._cache.clear()
