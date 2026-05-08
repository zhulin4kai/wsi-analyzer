import threading
from collections import OrderedDict
from typing import Optional

from PySide6.QtGui import QImage


class TileDataCache:
    def __init__(self, max_capacity: int = 2000):
        self.max_capacity = max_capacity
        self._cache: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def get(self, path: str, level: int, col: int, row: int) -> Optional[QImage]:
        key = (path, level, col, row)
        with self._lock:
            if key not in self._cache:
                return None
            self._cache.move_to_end(key)
            return self._cache[key]

    def put(self, path: str, level: int, col: int, row: int, qimg: QImage):
        key = (path, level, col, row)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = qimg
            if len(self._cache) > self.max_capacity:
                self._cache.popitem(last=False)

    def clear(self):
        with self._lock:
            self._cache.clear()
