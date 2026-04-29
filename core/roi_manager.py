import numpy as np

from utils import nms_numpy


def generate_roi_coordinates(
    roi_bbox,
    patch_size,
    stride,
    max_width,
    max_height,
    solid_mask=None,
    downsample_factor=1.0,
):
    """为 ROI 边界框生成 Level-0 滑动窗口坐标。"""
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
            coord_x = min(x, max_width - patch_size) if x + patch_size > max_width else x
            coord_y = min(y, max_height - patch_size) if y + patch_size > max_height else y
            coord_x = max(0, coord_x)
            coord_y = max(0, coord_y)

            if solid_mask is not None:
                cx = coord_x + patch_size / 2
                cy = coord_y + patch_size / 2
                mx = min(max(int(cx / downsample_factor), 0), solid_mask.shape[1] - 1)
                my = min(max(int(cy / downsample_factor), 0), solid_mask.shape[0] - 1)
                if solid_mask[my, mx] != 255:
                    continue

            valid_coords.append((coord_x, coord_y))

    return list(dict.fromkeys(valid_coords))


def fuse_results(existing_results, new_results, nms_iou_thresh):
    """使用 NMS 融合全局结果与 ROI 结果，消除重叠框。"""
    combined = existing_results + new_results
    if not combined:
        return []

    boxes = np.array([r["bbox"] for r in combined], dtype=np.float32)
    scores = np.array([r["confidence"] for r in combined], dtype=np.float32)
    keep = nms_numpy(boxes, scores, nms_iou_thresh)

    return [combined[idx] for idx in keep]
