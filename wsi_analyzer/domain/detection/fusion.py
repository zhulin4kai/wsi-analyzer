import numpy as np

from wsi_analyzer.domain.detection.entities import Detection
from wsi_analyzer.domain.detection.nms import nms_numpy


def compute_roi_coordinates(
    roi_bbox,
    patch_size: int,
    stride: int,
    max_width: int,
    max_height: int,
    solid_mask=None,
    downsample_factor: float = 1.0,
) -> list:
    x_min, y_min, x_max, y_max = roi_bbox
    x_min = max(0, int(x_min))
    y_min = max(0, int(y_min))
    x_max = min(max_width, int(x_max))
    y_max = min(max_height, int(y_max))

    if x_min >= x_max or y_min >= y_max:
        return []

    valid_coords = []
    for y in range(y_min, y_max, stride):
        for x in range(x_min, x_max, stride):
            cx = min(x, max_width - patch_size) if x + patch_size > max_width else x
            cy = min(y, max_height - patch_size) if y + patch_size > max_height else y
            cx = max(0, cx)
            cy = max(0, cy)

            if solid_mask is not None:
                centre_x = cx + patch_size / 2
                centre_y = cy + patch_size / 2
                mx = min(max(int(centre_x / downsample_factor), 0), solid_mask.shape[1] - 1)
                my = min(max(int(centre_y / downsample_factor), 0), solid_mask.shape[0] - 1)
                if solid_mask[my, mx] != 255:
                    continue

            valid_coords.append((cx, cy))

    return list(dict.fromkeys(valid_coords))


def fuse_results(existing_results, new_results, nms_iou_thresh: float) -> list[Detection]:
    combined = existing_results + new_results
    if not combined:
        return []

    boxes = np.array([r["bbox"] for r in combined], dtype=np.float32)
    scores = np.array([r["confidence"] for r in combined], dtype=np.float32)
    keep = nms_numpy(boxes, scores, nms_iou_thresh)

    return [combined[idx] for idx in keep]
