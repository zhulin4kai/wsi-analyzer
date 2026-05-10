import threading
from collections import OrderedDict
from typing import Dict, Set

from wsi_analyzer.infrastructure.imaging.openslide_engine import OpenSlideEngine


class SlidePool:
    def __init__(self, max_engines: int = 3):
        self.max_engines = max_engines
        self._engines: OrderedDict = OrderedDict()
        self._refcounts: Dict[str, int] = {}
        self._pending_close: Set[str] = set()
        self._lock = threading.Lock()

    def acquire(self, path: str):
        with self._lock:
            if path in self._engines:
                self._engines.move_to_end(path)
                self._pending_close.discard(path)
                self._refcounts[path] = self._refcounts.get(path, 0) + 1
                return self._engines[path]

            if len(self._engines) >= self.max_engines:
                self._evict_one()

            engine = OpenSlideEngine(path)
            self._engines[path] = engine
            self._refcounts[path] = 1
            return engine

    def release(self, path: str):
        with self._lock:
            if path not in self._refcounts:
                return
            self._refcounts[path] = max(0, self._refcounts[path] - 1)
            if self._refcounts[path] == 0 and path in self._pending_close:
                self._do_close(path)

    def preload(self, path: str):
        with self._lock:
            if path in self._engines:
                self._engines.move_to_end(path)
                return
            if len(self._engines) >= self.max_engines:
                self._evict_one()
            engine = OpenSlideEngine(path)
            self._engines[path] = engine
            self._refcounts[path] = 0

    def _evict_one(self):
        for path in self._engines:
            if self._refcounts.get(path, 0) == 0:
                self._do_close(path)
                return
        oldest = next(iter(self._engines))
        self._pending_close.add(oldest)

    def _do_close(self, path: str):
        engine = self._engines.pop(path, None)
        self._refcounts.pop(path, None)
        self._pending_close.discard(path)
        if engine:
            engine.close()  # type: ignore[union-attr]

    def close_all(self):
        with self._lock:
            for engine in self._engines.values():
                engine.close()
            self._engines.clear()
            self._refcounts.clear()
            self._pending_close.clear()
