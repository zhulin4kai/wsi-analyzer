import threading
from typing import Dict

from wsi_analyzer.domain.slide.metadata import SlideMetadata
from wsi_analyzer.infrastructure.imaging.slide_pool import SlidePool


class MetadataService:
    def __init__(self, slide_pool: SlidePool):
        self._slide_pool = slide_pool
        self._store: Dict[str, SlideMetadata] = {}
        self._lock = threading.Lock()

    def get(self, path: str) -> SlideMetadata:
        with self._lock:
            if path in self._store:
                return self._store[path]

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

        with self._lock:
            self._store[path] = metadata
        return metadata
