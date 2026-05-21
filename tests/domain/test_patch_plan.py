import numpy as np

from wsi_analyzer.domain.analysis.inference_geometry import InferenceGeometry
from wsi_analyzer.domain.analysis.patch_plan import PatchPlanner


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
