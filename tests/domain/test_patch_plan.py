import numpy as np

from wsi_analyzer.domain.analysis.inference_geometry import InferenceGeometry
from wsi_analyzer.domain.analysis.patch_plan import (
    PatchPlanner,
    TissueMaskIndex,
    _grid_positions,
)


def _make_geom(patch_size: int = 512, stride: int = 1000) -> InferenceGeometry:
    return InferenceGeometry(
        model_input_size=patch_size,
        target_mpp=1.0,
        slide_mpp=None,
        level0_window_size=patch_size,
        level0_stride=stride,
        read_level=0,
        read_downsample=1.0,
    )


class TestPatchPlanner:
    def test_plan_with_all_valid_mask(self):
        mask = np.ones((100, 100), dtype=np.uint8) * 255
        geom = _make_geom(patch_size=512, stride=1000)
        planner = PatchPlanner(geom)
        coords = planner.plan(mask, (10000, 8000), downsample_factor=100.0)

        assert len(coords) > 0
        for pc in coords:
            assert pc.x >= 0
            assert pc.y >= 0
            assert pc.level0_size == 512
            assert pc.x + pc.level0_size <= 10000, f"x out of bounds: {pc.x}"
            assert pc.y + pc.level0_size <= 8000, f"y out of bounds: {pc.y}"

    def test_empty_mask_returns_empty(self):
        mask = np.zeros((100, 100), dtype=np.uint8)
        geom = _make_geom(patch_size=512, stride=1000)
        planner = PatchPlanner(geom)
        coords = planner.plan(mask, (10000, 8000), downsample_factor=100.0)
        assert coords == []

    def test_partial_mask(self):
        mask = np.zeros((100, 100), dtype=np.uint8)
        mask[10:20, 10:20] = 255
        geom = _make_geom(patch_size=512, stride=200)
        planner = PatchPlanner(geom)
        coords = planner.plan(mask, (5000, 5000), downsample_factor=50.0)
        assert len(coords) > 0
        for pc in coords:
            mx1 = max(int(pc.x / 50.0), 0)
            my1 = max(int(pc.y / 50.0), 0)
            mx2 = min(int((pc.x + pc.level0_size) / 50.0), mask.shape[1])
            my2 = min(int((pc.y + pc.level0_size) / 50.0), mask.shape[0])
            patch_mask = mask[my1:my2, mx1:mx2]
            tissue_ratio = np.count_nonzero(patch_mask == 255) / patch_mask.size
            assert tissue_ratio >= 0.01

    def test_fast_planner_matches_reference_masks(self):
        rng = np.random.default_rng(42)
        cases = [
            np.zeros((30, 40), dtype=np.uint8),
            np.ones((30, 40), dtype=np.uint8) * 255,
            (rng.random((30, 40)) > 0.8).astype(np.uint8) * 255,
            _edge_mask(30, 40),
        ]
        geom = _make_geom(patch_size=128, stride=96)

        for mask in cases:
            planner = PatchPlanner(geom)
            coords = planner.plan(mask, (2400, 1800), downsample_factor=60.0)
            expected = _reference_plan(mask, geom, (2400, 1800), 60.0)
            assert [(c.x, c.y) for c in coords] == expected

    def test_integral_tissue_query_matches_reference(self):
        rng = np.random.default_rng(7)
        mask = (rng.random((25, 35)) > 0.75).astype(np.uint8) * 255
        index = TissueMaskIndex(mask)
        for x in range(0, 1600, 137):
            for y in range(0, 1400, 149):
                assert index.has_tissue_in_window(
                    x=x, y=y, win=256, downsample_factor=50.0,
                ) == _reference_has_tissue(mask, x, y, 256, 50.0)


class TestROIPlanner:
    def test_empty_if_invalid_bbox(self):
        from wsi_analyzer.domain.analysis.roi_planner import ROIPlanner
        geom = _make_geom(patch_size=512, stride=400)
        planner = ROIPlanner(geom)
        result = planner.plan((10, 10, 5, 5), (10000, 8000))
        assert result == []

    def test_coords_within_bbox(self):
        from wsi_analyzer.domain.analysis.roi_planner import ROIPlanner
        geom = _make_geom(patch_size=512, stride=500)
        planner = ROIPlanner(geom)
        coords = planner.plan((500, 300, 3000, 2500), (10000, 8000))
        assert len(coords) > 0
        for pc in coords:
            assert pc.x >= 500
            assert pc.y >= 300
            assert pc.x + pc.level0_size <= 10000
            assert pc.y + pc.level0_size <= 8000

    def test_mask_filtering(self):
        from wsi_analyzer.domain.analysis.roi_planner import ROIPlanner
        mask = np.ones((100, 100), dtype=np.uint8) * 255
        geom = _make_geom(patch_size=512, stride=1000)
        planner = ROIPlanner(geom)
        coords = planner.plan(
            (0, 0, 5000, 5000), (10000, 8000),
            solid_mask=mask, downsample_factor=100.0,
        )
        assert len(coords) > 0

    def test_roi_fast_planner_matches_reference_mask(self):
        from wsi_analyzer.domain.analysis.roi_planner import ROIPlanner

        rng = np.random.default_rng(123)
        mask = (rng.random((40, 50)) > 0.82).astype(np.uint8) * 255
        geom = _make_geom(patch_size=256, stride=180)
        roi_bbox = (200, 300, 2200, 1800)
        planner = ROIPlanner(geom)

        coords = planner.plan(
            roi_bbox, (3000, 2600), solid_mask=mask, downsample_factor=60.0,
        )
        expected = _reference_roi_plan(
            mask, geom, roi_bbox, (3000, 2600), 60.0,
        )
        assert [(c.x, c.y) for c in coords] == expected


def _edge_mask(height: int, width: int) -> np.ndarray:
    mask = np.zeros((height, width), dtype=np.uint8)
    mask[0, :] = 255
    mask[:, -1] = 255
    mask[-3:, :4] = 255
    return mask


def _reference_plan(mask, geom, level_0_dim, downsample_factor):
    w, h = level_0_dim
    coords = []
    for y in _grid_positions(h, geom.level0_window_size, geom.level0_stride):
        for x in _grid_positions(w, geom.level0_window_size, geom.level0_stride):
            if _reference_has_tissue(mask, x, y, geom.level0_window_size, downsample_factor):
                coords.append((x, y))
    return coords


def _reference_roi_plan(mask, geom, roi_bbox, level_0_dim, downsample_factor):
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
    coords = []
    seen = set()
    for y in _grid_positions(y_max, win, stride):
        if y < y_start:
            continue
        for x in _grid_positions(x_max, win, stride):
            if x < x_start:
                continue
            if not _reference_has_tissue(mask, x, y, win, downsample_factor):
                continue
            if (x, y) not in seen:
                seen.add((x, y))
                coords.append((x, y))
    return coords


def _reference_has_tissue(
    solid_mask: np.ndarray,
    x: int,
    y: int,
    win: int,
    downsample_factor: float,
    min_tissue_ratio: float = 0.01,
) -> bool:
    mx1 = min(max(int(x / downsample_factor), 0), solid_mask.shape[1] - 1)
    my1 = min(max(int(y / downsample_factor), 0), solid_mask.shape[0] - 1)
    mx2 = min(max(int((x + win) / downsample_factor), mx1 + 1), solid_mask.shape[1])
    my2 = min(max(int((y + win) / downsample_factor), my1 + 1), solid_mask.shape[0])
    patch_mask = solid_mask[my1:my2, mx1:mx2]
    if patch_mask.size == 0:
        return False
    tissue_ratio = float(np.count_nonzero(patch_mask == 255)) / float(patch_mask.size)
    return tissue_ratio >= min_tissue_ratio
