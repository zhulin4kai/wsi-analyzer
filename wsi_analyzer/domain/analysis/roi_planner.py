from wsi_analyzer.domain.analysis.inference_geometry import InferenceGeometry
from wsi_analyzer.domain.analysis.patch_plan import TissueMaskIndex, _grid_positions
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

        x_start = min(x_min, max(0, w - win))
        y_start = min(y_min, max(0, h - win))
        x_end = min(x_max, w)
        y_end = min(y_max, h)
        x_positions = _grid_positions(x_end, win, stride)
        y_positions = _grid_positions(y_end, win, stride)
        tissue_index = TissueMaskIndex(solid_mask) if solid_mask is not None else None

        seen: set[tuple[int, int]] = set()
        coords: list[PatchCoordinate] = []
        for y in y_positions:
            if y < y_start:
                continue
            for x in x_positions:
                if x < x_start:
                    continue
                cx = x
                cy = y

                if tissue_index is not None:
                    if not tissue_index.has_tissue_in_window(
                        x=cx,
                        y=cy,
                        win=win,
                        downsample_factor=downsample_factor,
                    ):
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
