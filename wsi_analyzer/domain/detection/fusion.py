import numpy as np

from wsi_analyzer.domain.detection.nms import nms_numpy


def fuse_results(existing_results, new_results, nms_iou_thresh: float) -> list:
    combined = existing_results + new_results
    if not combined:
        return []

    boxes = np.array([r["bbox"] for r in combined], dtype=np.float32)
    scores = np.array([r["confidence"] for r in combined], dtype=np.float32)
    keep = nms_numpy(boxes, scores, nms_iou_thresh)

    return [combined[idx] for idx in keep]
