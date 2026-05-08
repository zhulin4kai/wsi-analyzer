import numpy as np

from wsi_analyzer.domain.analysis.roi_planner import generate_roi_coordinates as compute_roi_coordinates
from wsi_analyzer.domain.detection.fusion import fuse_results


class TestROICoordinates:
    def test_empty_if_invalid_bbox(self):
        result = compute_roi_coordinates(
            (10, 10, 5, 5), patch_size=512, stride=400,
            max_width=1000, max_height=1000,
        )
        assert result == []

    def test_generates_coords(self):
        result = compute_roi_coordinates(
            (0, 0, 1000, 800), patch_size=512, stride=400,
            max_width=10000, max_height=8000,
        )
        assert len(result) > 0
        for cx, cy in result:
            assert cx >= 0
            assert cy >= 0
            assert cx + 512 <= 10000
            assert cy + 512 <= 8000

    def test_respects_max_bounds(self):
        result = compute_roi_coordinates(
            (9000, 7000, 10000, 8000), patch_size=512, stride=400,
            max_width=10000, max_height=8000,
        )
        for cx, cy in result:
            assert cx + 512 <= 10000
            assert cy + 512 <= 8000

    def test_mask_filtering(self):
        mask = np.ones((50, 50), dtype=np.uint8) * 255  # All valid
        result = compute_roi_coordinates(
            (0, 0, 4000, 4000), patch_size=512, stride=1000,
            max_width=10000, max_height=8000,
            solid_mask=mask, downsample_factor=80.0,  # 10000/50 ≈ 200... actually let me think
        )
        # With all-valid mask, should return all coords
        assert len(result) > 0


class TestFuseResults:
    def test_empty_returns_empty(self):
        assert fuse_results([], [], 0.5) == []

    def test_combined(self):
        a = [{"bbox": [0, 0, 10, 10], "confidence": 0.9, "class_id": 1}]
        b = [{"bbox": [0, 0, 10, 10], "confidence": 0.8, "class_id": 1}]
        result = fuse_results(a, b, 0.1)
        assert len(result) == 1
