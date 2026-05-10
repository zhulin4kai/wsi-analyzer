from wsi_analyzer.domain.slide.coordinates import PatchCoordinate


class ROIPlanner:
    def __init__(self, patch_size: int, stride: int):
        self.patch_size = patch_size
        self.stride = stride

    def plan(
        self,
        roi_bbox: tuple,
        level_0_dim: tuple,
        solid_mask=None,
        downsample_factor: float = 1.0,
        target_level: int = 0,
        target_downsample: float = 1.0,
    ) -> list[PatchCoordinate]:
        w, h = level_0_dim
        x_min, y_min, x_max, y_max = roi_bbox
        x_min = max(0, int(x_min))
        y_min = max(0, int(y_min))
        x_max = min(w, int(x_max))
        y_max = min(h, int(y_max))

        if x_min >= x_max or y_min >= y_max:
            return []

        seen = set()
        coords = []
        for y in range(y_min, y_max, self.stride):
            for x in range(x_min, x_max, self.stride):
                cx = min(x, w - self.patch_size) if x + self.patch_size > w else x
                cy = min(y, h - self.patch_size) if y + self.patch_size > h else y
                cx = max(0, cx)
                cy = max(0, cy)

                if solid_mask is not None:
                    centre_x = cx + self.patch_size / 2
                    centre_y = cy + self.patch_size / 2
                    mx = min(max(int(centre_x / downsample_factor), 0), solid_mask.shape[1] - 1)
                    my = min(max(int(centre_y / downsample_factor), 0), solid_mask.shape[0] - 1)
                    if solid_mask[my, mx] != 255:
                        continue

                key = (cx, cy)
                if key not in seen:
                    seen.add(key)
                    coords.append(PatchCoordinate(
                        x=cx, y=cy,
                        size=self.patch_size,
                        level=target_level,
                        downsample=target_downsample,
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
    planner = ROIPlanner(patch_size=patch_size, stride=stride)
    coords = planner.plan(
        roi_bbox=roi_bbox,
        level_0_dim=(max_width, max_height),
        solid_mask=solid_mask,
        downsample_factor=downsample_factor,
        target_level=0,
        target_downsample=1.0,
    )
    return [(c.x, c.y) for c in coords]
