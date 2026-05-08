from collections import OrderedDict
from typing import Any, List, Optional, Tuple


class TileLRUCache:
    def __init__(self, max_capacity: int = 1024):
        self.max_capacity = max_capacity
        self._cache: OrderedDict[Tuple[int, int, int], Any] = OrderedDict()

    def get(self, key: Tuple[int, int, int]) -> Optional[Any]:
        if key not in self._cache:
            return None
        self._cache.move_to_end(key)
        return self._cache[key]

    def put(self, key: Tuple[int, int, int], item: Any) -> Optional[Any]:
        evicted_item = None
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = item
        if len(self._cache) > self.max_capacity:
            _, evicted_item = self._cache.popitem(last=False)
        return evicted_item

    def contains(self, key: Tuple[int, int, int]) -> bool:
        return key in self._cache

    def clear(self) -> List[Any]:
        items = list(self._cache.values())
        self._cache.clear()
        return items

    def __len__(self) -> int:
        return len(self._cache)

    def iter_items(self):
        return self._cache.items()
