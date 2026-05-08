import numpy as np

from wsi_analyzer.domain.analysis.patch_plan import PatchPlanner


class TestPatchPlanner:
    def test_plan_with_all_valid_mask(self):
        mask = np.ones((100, 100), dtype=np.uint8) * 255
        planner = PatchPlanner(patch_size=512, stride=1000)
        coords = planner.plan(mask, (10000, 8000), downsample_factor=100.0)

        assert len(coords) > 0
        for pc in coords:
            assert pc.x >= 0
            assert pc.y >= 0
            assert pc.size == 512
            assert pc.x + pc.size <= 10000, f"x out of bounds: {pc.x}"
            assert pc.y + pc.size <= 8000, f"y out of bounds: {pc.y}"

    def test_empty_mask_returns_empty(self):
        mask = np.zeros((100, 100), dtype=np.uint8)
        planner = PatchPlanner(patch_size=512, stride=1000)
        coords = planner.plan(mask, (10000, 8000), downsample_factor=100.0)
        assert coords == []

    def test_partial_mask(self):
        mask = np.zeros((100, 100), dtype=np.uint8)
        mask[10:20, 10:20] = 255  # Small valid region
        planner = PatchPlanner(patch_size=512, stride=200)
        coords = planner.plan(mask, (5000, 5000), downsample_factor=50.0)
        assert len(coords) > 0
        # All coords should have their centre in the valid mask region
        for pc in coords:
            cx = pc.x + pc.size / 2
            cy = pc.y + pc.size / 2
            mx = int(cx / 50.0)
            my = int(cy / 50.0)
            assert 0 <= mx < 100
            assert 0 <= my < 100
            assert mask[my, mx] == 255


class TestROIPlanner:
    def test_empty_if_invalid_bbox(self):
        from wsi_analyzer.domain.analysis.roi_planner import ROIPlanner
        planner = ROIPlanner(patch_size=512, stride=400)
        result = planner.plan((10, 10, 5, 5), (10000, 8000))
        assert result == []

    def test_coords_within_bbox(self):
        from wsi_analyzer.domain.analysis.roi_planner import ROIPlanner
        planner = ROIPlanner(patch_size=512, stride=500)
        coords = planner.plan((500, 300, 3000, 2500), (10000, 8000))
        assert len(coords) > 0
        for pc in coords:
            assert pc.x >= 500
            assert pc.y >= 300
            assert pc.x + pc.size <= 10000
            assert pc.y + pc.size <= 8000

    def test_mask_filtering(self):
        from wsi_analyzer.domain.analysis.roi_planner import ROIPlanner
        mask = np.ones((100, 100), dtype=np.uint8) * 255
        planner = ROIPlanner(patch_size=512, stride=1000)
        coords = planner.plan(
            (0, 0, 5000, 5000), (10000, 8000),
            solid_mask=mask, downsample_factor=100.0,
        )
        assert len(coords) > 0
