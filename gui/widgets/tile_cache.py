from collections import OrderedDict
from typing import Any, List, Optional, Tuple


class TileLRUCache:
    """
    基于 OrderedDict 实现的 WSI 瓦片 LRU (最近最少使用) 缓存池。
    管理内存中的图块，避免内存溢出。
    """

    def __init__(self, max_capacity: int = 1024):
        """
        初始化 LRU 缓存池。
        :param max_capacity: 缓存图块的最大数量
        """
        self.max_capacity = max_capacity
        # OrderedDict 能够记住字典元素插入的顺序
        self._cache: OrderedDict[Tuple[int, int, int], Any] = OrderedDict()

    def get(self, key: Tuple[int, int, int]) -> Optional[Any]:
        """
        获取缓存中的瓦片。
        若存在，则移动至末尾并返回。
        :param key: 瓦片的唯一标识，通常为 (level, col, row)
        :return: 缓存的瓦片对象 (通常是 QGraphicsPixmapItem)，不存在则返回 None
        """
        if key not in self._cache:
            return None

        # 记录访问状态
        self._cache.move_to_end(key)
        item = self._cache[key]

        return item

    def put(self, key: Tuple[int, int, int], item: Any) -> Optional[Any]:
        """
        存入新的瓦片。
        达到容量上限时移除最旧的图块。

        :param key: 瓦片的唯一标识 (level, col, row)
        :param item: 要缓存的图块对象
        :return: 被移除的图块对象
        """
        evicted_item = None

        if key in self._cache:
            # 如果已经存在，直接更新值并移动到末尾
            self._cache.move_to_end(key)

        self._cache[key] = item

        # 检查容量并清理过期记录
        if len(self._cache) > self.max_capacity:
            # 移除最久未访问元素
            _, evicted_item = self._cache.popitem(last=False)

        return evicted_item

    def contains(self, key: Tuple[int, int, int]) -> bool:
        """
        判断瓦片是否在缓存中。
        仅探测是否存在，不改变缓存顺序。
        """
        return key in self._cache

    def clear(self) -> List[Any]:
        """
        清空所有缓存。
        :return: 缓存的所有图块对象列表
        """
        items = list(self._cache.values())
        self._cache.clear()
        return items

    def __len__(self) -> int:
        """获取当前缓存的瓦片数量"""
        return len(self._cache)
