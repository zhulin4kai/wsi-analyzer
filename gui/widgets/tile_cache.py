from collections import OrderedDict
from typing import Any, List, Optional, Tuple


class TileLRUCache:
    """
    基于 OrderedDict 实现的 WSI 瓦片 LRU (最近最少使用) 缓存池。
    用于管理内存中驻留的图块(QGraphicsPixmapItem)，防止无限加载瓦片导致内存溢出。
    """

    def __init__(self, max_capacity: int = 200):
        """
        初始化 LRU 缓存池。
        :param max_capacity: 最大缓存的瓦片数量。默认 200 张 512x512 的图块大约占用 150MB 内存。
        """
        self.max_capacity = max_capacity
        # OrderedDict 能够记住字典元素插入的顺序
        self._cache: OrderedDict[Tuple[int, int, int], Any] = OrderedDict()

    def get(self, key: Tuple[int, int, int]) -> Optional[Any]:
        """
        获取缓存中的瓦片。
        如果瓦片存在，将其移动到字典末尾（标记为最新活跃），并返回。
        :param key: 瓦片的唯一标识，通常为 (level, col, row)
        :return: 缓存的瓦片对象 (通常是 QGraphicsPixmapItem)，不存在则返回 None
        """
        if key not in self._cache:
            return None

        # 移动到末尾，表示刚刚被访问过（最近使用）
        self._cache.move_to_end(key)
        return self._cache[key]

    def put(self, key: Tuple[int, int, int], item: Any) -> Optional[Any]:
        """
        存入新的瓦片。
        如果当前缓存已达到最大容量，则淘汰并弹出最老的一个瓦片。

        :param key: 瓦片的唯一标识 (level, col, row)
        :param item: 要缓存的图块对象
        :return: 被淘汰出局的老瓦片对象 (如果没有发生淘汰则返回 None)，供调用方从 UI Scene 中安全移除
        """
        evicted_item = None

        if key in self._cache:
            # 如果已经存在，直接更新值并移动到末尾
            self._cache.move_to_end(key)

        self._cache[key] = item

        # 检查容量，如果超限则弹出最老的记录（位于字典头部的位置）
        if len(self._cache) > self.max_capacity:
            # popitem(last=False) 采用 FIFO 模式弹出第一个插入的元素（即最久未访问的元素）
            _, evicted_item = self._cache.popitem(last=False)

        return evicted_item

    def contains(self, key: Tuple[int, int, int]) -> bool:
        """
        判断瓦片是否在缓存中。
        与 get() 不同，此方法仅做探测，不会改变瓦片在 LRU 中的活跃度排序。
        """
        return key in self._cache

    def clear(self) -> List[Any]:
        """
        清空所有缓存。
        :return: 返回当前缓存中所有的瓦片对象列表，供外部集中执行清理销毁操作。
        """
        items = list(self._cache.values())
        self._cache.clear()
        return items

    def __len__(self) -> int:
        """获取当前缓存的瓦片数量"""
        return len(self._cache)
