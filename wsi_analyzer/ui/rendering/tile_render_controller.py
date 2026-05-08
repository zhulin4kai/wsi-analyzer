from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem

from wsi_analyzer.infrastructure.imaging import ImageServer
from wsi_analyzer.ui.rendering import compute_visible_tile_requests


class TileRenderController:
    def __init__(self, render_worker, tile_cache, scene_canvas):
        self.render_worker = render_worker
        self.tile_cache = tile_cache
        self.scene_canvas = scene_canvas
        self.render_version = 0
        self.active_path = None
        self.active_metadata = None

    # ── lifecycle ──────────────────────────────────────────────────

    def invalidate(self):
        self.render_version += 1000
        self.render_worker.set_version(self.render_version)
        self.render_worker.stop()
        self.active_path = None
        self.active_metadata = None

    def activate(self, path, metadata):
        self.active_path = path
        self.active_metadata = metadata

    # ── tile dispatch ──────────────────────────────────────────────

    def request_tiles(self, visible_scene_rect, scene_rect, current_scale):
        if not self.active_path or not self.active_metadata:
            return

        requests = compute_visible_tile_requests(
            metadata=self.active_metadata,
            visible_scene_rect=visible_scene_rect,
            scene_rect=scene_rect,
            current_scale=current_scale,
            tile_size=512,
        )
        if not requests:
            return

        best_level = requests[0].level
        self._hide_coarse_tiles(best_level)
        self.render_version += 1

        for req in requests:
            key = (req.level, req.col, req.row)

            # Level 1: scene-item LRU cache (no I/O)
            cached_item = self.tile_cache.get(key)
            if cached_item:
                if not cached_item.scene():
                    self.scene_canvas.addItem(cached_item)
                cached_item.setVisible(True)
                continue

            # Level 2: cross-slide pixel data cache (no I/O)
            cached_qimg = ImageServer.instance().get_tile(
                self.active_path, req.level, req.col, req.row
            )
            if cached_qimg is not None:
                self._add_tile_to_scene(
                    cached_qimg, req.level, req.col, req.row,
                    req.x, req.y, req.scale,
                )
                continue

            # Level 3: dispatch background I/O task
            self.render_worker.request_render(
                self.active_path,
                req.level, req.col, req.row,
                req.x, req.y, req.width, req.height,
                req.scale,
                self.render_version,
                priority=req.priority,
            )

    # ── image-ready callback ───────────────────────────────────────
    # Returns True if a tile was placed into the scene.

    def on_image_ready(self, path, version, level, col, row, qimg, x, y, scale):
        if path != self.active_path:
            return False
        if version < self.render_version:
            return False
        key = (level, col, row)
        if self.tile_cache.contains(key):
            return False
        self._add_tile_to_scene(qimg, level, col, row, x, y, scale)
        return True

    # ── helpers ────────────────────────────────────────────────────

    def set_cache_capacity(self, capacity: int):
        self.tile_cache.max_capacity = capacity

    def clear_tile_items(self):
        old_items = self.tile_cache.clear()
        for item in old_items:
            if item.scene():
                self.scene_canvas.removeItem(item)

    def _hide_coarse_tiles(self, best_level):
        for key, item in self.tile_cache.iter_items():
            cached_level = key[0]
            item.setVisible(cached_level >= best_level)

    def _add_tile_to_scene(self, qimg, level, col, row, x, y, scale):
        key = (level, col, row)
        if self.tile_cache.contains(key):
            return
        pixmap = QPixmap.fromImage(qimg)
        item = QGraphicsPixmapItem(pixmap)
        item.setPos(x, y)
        item.setScale(scale)
        item.setZValue(self.active_metadata.level_count - level)
        self.scene_canvas.addItem(item)
        evicted = self.tile_cache.put(key, item)
        if evicted and evicted.scene():
            self.scene_canvas.removeItem(evicted)
