import math
from dataclasses import dataclass

from PySide6.QtCore import QRectF


@dataclass(frozen=True)
class TileRequest:
    level: int
    col: int
    row: int
    x: int
    y: int
    width: int
    height: int
    scale: float
    priority: float


def compute_visible_tile_requests(
    metadata,
    visible_scene_rect: QRectF,
    scene_rect: QRectF,
    current_scale: float,
    tile_size: int = 512,
) -> list:
    intersected_rect = visible_scene_rect.intersected(scene_rect)
    if intersected_rect.isEmpty() or current_scale <= 0:
        return []

    target_downsample = 1.0 / current_scale
    best_level = metadata.get_best_level_for_downsample(target_downsample)
    level_downsample = metadata.level_downsamples[best_level]
    level_dim = metadata.level_dimensions[best_level]

    start_col = int((intersected_rect.left() / level_downsample) // tile_size) - 1
    end_col = int((intersected_rect.right() / level_downsample) // tile_size) + 1
    start_row = int((intersected_rect.top() / level_downsample) // tile_size) - 1
    end_row = int((intersected_rect.bottom() / level_downsample) // tile_size) + 1

    max_col = (level_dim[0] - 1) // tile_size
    max_row = (level_dim[1] - 1) // tile_size

    start_col = max(0, min(start_col, max_col))
    end_col = max(0, min(end_col, max_col))
    start_row = max(0, min(start_row, max_row))
    end_row = max(0, min(end_row, max_row))

    viewport_center = visible_scene_rect.center()
    requests = []

    for row in range(start_row, end_row + 1):
        for col in range(start_col, end_col + 1):
            abs_x = col * tile_size * level_downsample
            abs_y = row * tile_size * level_downsample

            tile_w = level_dim[0] - col * tile_size if col == max_col else tile_size
            tile_h = level_dim[1] - row * tile_size if row == max_row else tile_size

            tile_center_x = abs_x + tile_w * level_downsample * 0.5
            tile_center_y = abs_y + tile_h * level_downsample * 0.5
            dist = math.hypot(
                tile_center_x - viewport_center.x(),
                tile_center_y - viewport_center.y(),
            )
            priority = dist / max(level_downsample, 1e-6)

            requests.append(
                TileRequest(
                    level=best_level,
                    col=col,
                    row=row,
                    x=int(abs_x),
                    y=int(abs_y),
                    width=int(tile_w),
                    height=int(tile_h),
                    scale=level_downsample,
                    priority=priority,
                )
            )

    return requests
