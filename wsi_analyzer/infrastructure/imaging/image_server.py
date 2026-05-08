import threading

from wsi_analyzer.infrastructure.imaging.metadata_service import MetadataService
from wsi_analyzer.infrastructure.imaging.slide_pool import SlidePool
from wsi_analyzer.infrastructure.imaging.tile_data_cache import TileDataCache


class ImageServer:
    _instance = None
    _instance_lock = threading.Lock()

    def __init__(self):
        self._slide_pool = SlidePool(max_engines=3)
        self._tile_cache = TileDataCache(max_capacity=2000)
        self._metadata_service = MetadataService(self._slide_pool)

    @classmethod
    def instance(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = ImageServer()
        return cls._instance

    def get_metadata(self, path):
        return self._metadata_service.get(path)

    def get_tile(self, path: str, level: int, col: int, row: int):
        return self._tile_cache.get(path, level, col, row)

    def cache_tile(self, path: str, level: int, col: int, row: int, qimg):
        self._tile_cache.put(path, level, col, row, qimg)

    def acquire_engine(self, path: str):
        return self._slide_pool.acquire(path)

    def release_engine(self, path: str):
        self._slide_pool.release(path)

    def preload_engine(self, path: str):
        self._slide_pool.preload(path)

    def get_thumbnail(self, path: str, level_from_last: int = 1):
        engine = self._slide_pool.acquire(path)
        try:
            return engine.get_thumbnail(level_from_last=level_from_last)
        finally:
            self._slide_pool.release(path)

    def sample_pixel(self, path: str, lx: int, ly: int):
        engine = self._slide_pool.acquire(path)
        try:
            return engine.read_region((lx, ly), 0, (1, 1))
        finally:
            self._slide_pool.release(path)

    def shutdown(self):
        self._slide_pool.close_all()
        self._tile_cache.clear()
