import math

import cv2
import numpy as np


def compute_heatmap_grid(
    results: list,
    wsi_w: int,
    wsi_h: int,
    bin_size: int,
    blur_sigma: float,
) -> np.ndarray:
    """Build a normalized heatmap grid from detection results.

    Returns a 2D float32 array with values in [0, 1].
    """
    grid_w = max(1, math.ceil(wsi_w / bin_size))
    grid_h = max(1, math.ceil(wsi_h / bin_size))
    grid = np.zeros((grid_h, grid_w), dtype=np.float32)

    for det in results:
        try:
            x_min, y_min, x_max, y_max = det["bbox"]
            confidence = float(det["confidence"])
        except (KeyError, ValueError, TypeError):
            continue

        cx = (x_min + x_max) * 0.5
        cy = (y_min + y_max) * 0.5
        gx = min(int(cx / bin_size), grid_w - 1)
        gy = min(int(cy / bin_size), grid_h - 1)
        gx = max(0, gx)
        gy = max(0, gy)
        grid[gy, gx] += confidence

    base_sigma = float(blur_sigma)
    if base_sigma > 0 and grid.max() > 1e-8:
        n = len(results)
        if n < 50:
            sigma_val = 5.0
        elif n < 500:
            sigma_val = base_sigma
        else:
            sigma_val = max(2.0, base_sigma * 0.6)

        k = int(math.ceil(3.0 * sigma_val)) * 2 + 1
        k = max(3, k)
        short_side = min(grid_h, grid_w)
        k_max = max(3, short_side // 2 * 2 - 1)
        k = min(k, k_max)
        grid = cv2.GaussianBlur(grid, (k, k), sigma_val)

    max_val = float(grid.max())
    if max_val > 1e-8:
        grid = grid / max_val

    return grid.astype(np.float32)  # type: ignore[union-attr]


def grid_to_rgba(
    grid_norm: np.ndarray,
    alpha: int,
    alpha_gamma: float,
    colormap: int,
) -> np.ndarray:
    """Convert a normalized heatmap grid to an RGBA colormap image.

    Returns an H×W×4 uint8 array.
    """
    gray_u8 = np.clip(grid_norm * 255.0, 0, 255).astype(np.uint8)
    colormap_bgr = cv2.applyColorMap(gray_u8, colormap)
    rgba = cv2.cvtColor(colormap_bgr, cv2.COLOR_BGR2RGBA)
    alpha_channel = np.clip(
        np.power(grid_norm, alpha_gamma) * float(alpha), 0, 255
    ).astype(np.uint8)
    rgba[:, :, 3] = alpha_channel
    return rgba
