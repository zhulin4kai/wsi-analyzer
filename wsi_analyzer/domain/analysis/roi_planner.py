from wsi_analyzer.domain.analysis.inference_geometry import InferenceGeometry
from wsi_analyzer.domain.slide.coordinates import PatchCoordinate


class ROIPlanner:
    """Generate PatchCoordinate list restricted to a user-drawn ROI bbox."""

    def __init__(self, geometry: InferenceGeometry):
        self._geom = geometry

    def plan(
        self,
        roi_bbox: tuple,
        level_0_dim: tuple[int, int],
        solid_mask=None,
        downsample_factor: float = 1.0,
    ) -> list[PatchCoordinate]:
        geom = self._geom
        w, h = level_0_dim
        win = geom.level0_window_size
        stride = geom.level0_stride

        x_min, y_min, x_max, y_max = roi_bbox
        x_min = max(0, int(x_min))
        y_min = max(0, int(y_min))
        x_max = min(w, int(x_max))
        y_max = min(h, int(y_max))

        if x_min >= x_max or y_min >= y_max:
            return []

        seen: set[tuple[int, int]] = set()
        coords: list[PatchCoordinate] = []
        for y in range(y_min, y_max, stride):
            for x in range(x_min, x_max, stride):
                cx = min(x, w - win) if x + win > w else x
                cy = min(y, h - win) if y + win > h else y
                cx = max(0, cx)
                cy = max(0, cy)

                if solid_mask is not None:
                    centre_x = cx + win / 2
                    centre_y = cy + win / 2
                    mx = min(max(int(centre_x / downsample_factor), 0), solid_mask.shape[1] - 1)
                    my = min(max(int(centre_y / downsample_factor), 0), solid_mask.shape[0] - 1)
                    if solid_mask[my, mx] != 255:
                        continue

                key = (cx, cy)
                if key not in seen:
                    seen.add(key)
                    coords.append(PatchCoordinate(
                        x=cx,
                        y=cy,
                        level0_size=win,
                        model_input_size=geom.model_input_size,
                        read_level=geom.read_level,
                        read_downsample=geom.read_downsample,
                    ))
        return coords


def generate_roi_coordinates(
    roi_bbox,
    patch_size: int,
    stride: int,
    max_width: int,
    max_height: int,
    solid_mask=None,
    downsample_factor: float = 1.0,
) -> list:
    """Backward-compatible ROI coordinate generator for legacy callers.

    Still used by older code paths that expect [(x, y)] list output.
    """
    geom = InferenceGeometry(
        model_input_size=patch_size,
        target_mpp=1.0,
        slide_mpp=None,
        level0_window_size=patch_size,
        level0_stride=stride,
        read_level=0,
        read_downsample=1.0,
    )
    planner = ROIPlanner(geom)
    coords = planner.plan(
        roi_bbox=roi_bbox,
        level_0_dim=(max_width, max_height),
        solid_mask=solid_mask,
        downsample_factor=downsample_factor,
    )
    return [(c.x, c.y) for c in coords]
