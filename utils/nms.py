import numpy as np


def nms_numpy(
    boxes: np.ndarray, scores: np.ndarray, iou_threshold: float
) -> np.ndarray:
    """
    :param boxes:         shape (N, 4)  [x1, y1, x2, y2]  float32，像素坐标
    :param scores:        shape (N,)    float32，每个框的置信度得分
    :param iou_threshold: IoU 阈值，超过该值的重叠框将被抑制
    :return:              shape (K,)    int64，保留框在原数组中的索引
    """
    if len(boxes) == 0:
        return np.array([], dtype=np.int64)

    # 使用 float64 提高数值稳定性，避免大坐标下的浮点误差
    x1 = boxes[:, 0].astype(np.float64)
    y1 = boxes[:, 1].astype(np.float64)
    x2 = boxes[:, 2].astype(np.float64)
    y2 = boxes[:, 3].astype(np.float64)

    # 各框面积（负面积视为 0，防御异常坐标）
    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)

    # 按置信度降序排列；.copy() 确保后续索引操作不会写入原数组
    order = scores.argsort()[::-1].copy()

    keep: list[int] = []

    while len(order) > 0:
        # 当前最高分的框直接保留
        i = int(order[0])
        keep.append(i)

        if len(order) == 1:
            break

        rest = order[1:]

        # 计算当前框与剩余所有框的交集区域
        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])

        inter_w = np.maximum(0.0, xx2 - xx1)
        inter_h = np.maximum(0.0, yy2 - yy1)
        inter = inter_w * inter_h

        # IoU = 交集 / 并集（并集为零时 IoU 置 0，防止除零）
        union = areas[i] + areas[rest] - inter
        iou = np.where(union > 0.0, inter / union, 0.0)

        # 只保留与当前框 IoU 不超过阈值的框，进入下一轮
        order = rest[iou <= iou_threshold]

    return np.array(keep, dtype=np.int64)
