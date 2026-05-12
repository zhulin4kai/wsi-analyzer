import json
import os

import cv2
import numpy as np

from wsi_analyzer.domain.detection.heatmap import compute_heatmap_grid, grid_to_rgba
from wsi_analyzer.config.config import (
    HEATMAP_ALPHA, HEATMAP_ALPHA_GAMMA, HEATMAP_BIN_SIZE,
    HEATMAP_BLUR_SIGMA, HEATMAP_COLORMAP,
)


def render_prediction_overlay(
    thumbnail: np.ndarray,
    detections: list,
    downsample_factor: float,
    conf_threshold: float = 0.0,
    output_path: str | None = None,
) -> np.ndarray:
    """Draw AI detection boxes on a WSI thumbnail.

    Parameters:
        thumbnail:        RGB numpy array (H, W, 3).
        detections:        List of dicts with 'bbox' and 'confidence'.
        downsample_factor: Thumbnail downsample relative to Level-0.
        conf_threshold:    Only draw boxes with confidence >= threshold.
    """
    h, w = thumbnail.shape[:2]
    img = thumbnail.copy()

    for det in detections:
        conf = det.get("confidence", 0)
        if conf < conf_threshold:
            continue
        b = det["bbox"]
        x1 = max(0, int(b[0] / downsample_factor))
        y1 = max(0, int(b[1] / downsample_factor))
        x2 = min(w - 1, int(b[2] / downsample_factor))
        y2 = min(h - 1, int(b[3] / downsample_factor))
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(img, f"{conf:.2f}", (x1, max(y1 - 4, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)

    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        cv2.imwrite(output_path, cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    return img


def render_gt_vs_pred_overlay(
    thumbnail: np.ndarray,
    detections: list,
    gt_boxes: list,
    matches: list,
    downsample_factor: float,
    output_path: str | None = None,
) -> np.ndarray:
    """Draw GT vs prediction comparison with TP/FP/FN coloring.

    GT:     blue dashed rectangles.
    Pred TP: green solid rectangles.
    Pred FP: red solid rectangles.
    """
    h, w = thumbnail.shape[:2]
    img = thumbnail.copy()

    # Draw GT boxes (blue)
    for gt in gt_boxes:
        x1 = max(0, int(gt["x1"] / downsample_factor))
        y1 = max(0, int(gt["y1"] / downsample_factor))
        x2 = min(w - 1, int(gt["x2"] / downsample_factor))
        y2 = min(h - 1, int(gt["y2"] / downsample_factor))
        cv2.rectangle(img, (x1, y1), (x2, y2), (255, 0, 0), 2)

    # Match records
    for m in matches:
        if m["status"] == "TP" and m.get("prediction"):
            b = m["prediction"]
            x1 = max(0, int(b["x1"] / downsample_factor))
            y1 = max(0, int(b["y1"] / downsample_factor))
            x2 = min(w - 1, int(b["x2"] / downsample_factor))
            y2 = min(h - 1, int(b["y2"] / downsample_factor))
            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
        elif m["status"] == "FP" and m.get("prediction"):
            b = m["prediction"]
            x1 = max(0, int(b["x1"] / downsample_factor))
            y1 = max(0, int(b["y1"] / downsample_factor))
            x2 = min(w - 1, int(b["x2"] / downsample_factor))
            y2 = min(h - 1, int(b["y2"] / downsample_factor))
            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 2)

    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        cv2.imwrite(output_path, cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    return img


def render_heatmap_image(
    detections: list,
    wsi_w: int,
    wsi_h: int,
    output_path: str | None = None,
) -> np.ndarray:
    """Generate a heatmap image from detection results."""
    grid = compute_heatmap_grid(
        detections, wsi_w, wsi_h,
        bin_size=HEATMAP_BIN_SIZE, blur_sigma=HEATMAP_BLUR_SIGMA,
    )
    rgba = grid_to_rgba(
        grid, alpha=HEATMAP_ALPHA, alpha_gamma=HEATMAP_ALPHA_GAMMA,
        colormap=HEATMAP_COLORMAP,
    )
    bgr = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2BGR)
    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        cv2.imwrite(output_path, bgr)
    return bgr
