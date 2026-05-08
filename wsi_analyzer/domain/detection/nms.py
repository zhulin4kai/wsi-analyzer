import numpy as np


def nms_numpy(
    boxes: np.ndarray, scores: np.ndarray, iou_threshold: float
) -> np.ndarray:
    if len(boxes) == 0:
        return np.array([], dtype=np.int64)

    x1 = boxes[:, 0].astype(np.float64)
    y1 = boxes[:, 1].astype(np.float64)
    x2 = boxes[:, 2].astype(np.float64)
    y2 = boxes[:, 3].astype(np.float64)

    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)

    order = scores.argsort()[::-1].copy()

    keep = []

    while len(order) > 0:
        i = int(order[0])
        keep.append(i)

        if len(order) == 1:
            break

        rest = order[1:]

        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])

        inter_w = np.maximum(0.0, xx2 - xx1)
        inter_h = np.maximum(0.0, yy2 - yy1)
        inter = inter_w * inter_h

        union = areas[i] + areas[rest] - inter
        iou = np.where(union > 0.0, inter / union, 0.0)

        order = rest[iou <= iou_threshold]

    return np.array(keep, dtype=np.int64)
