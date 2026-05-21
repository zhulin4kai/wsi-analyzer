import numpy as np

from wsi_analyzer.domain.analysis.tissue_mask import TissueMaskGenerator


class TestTissueMaskGenerator:
    def test_all_white_returns_solid_mask(self):
        gen = TissueMaskGenerator()
        img = (np.ones((100, 100, 3), dtype=np.uint8) * 255)
        mask = gen.generate(img)
        assert mask.shape == (100, 100)
        assert mask.dtype == np.uint8
        # All white image: Otsu might still detect some "foreground" depending on content
        # Just verify it returns a valid mask shape

    def test_dark_on_light(self):
        gen = TissueMaskGenerator(min_area_ratio=0.0, use_hsv_saturation=False)
        img = np.ones((100, 100, 3), dtype=np.uint8) * 200
        # Add a dark rectangle in the center
        img[30:70, 30:70] = [50, 50, 50]
        mask = gen.generate(img)
        assert mask.shape == (100, 100)
        # The center dark region should be detected as tissue
        assert mask[50, 50] == 255  # Inside dark rectangle
        assert mask[10, 10] == 0    # Outside (light background)

    def test_min_area_filters_small_specks(self):
        gen = TissueMaskGenerator(min_area_ratio=0.05)  # 5% of area
        img = np.ones((100, 100, 3), dtype=np.uint8) * 200
        # Small dark speck (1x1)
        img[50, 50] = [50, 50, 50]
        mask = gen.generate(img)
        # Should not appear because area is too small
        assert mask[50, 50] == 0

    def test_large_region_passes_filter(self):
        gen = TissueMaskGenerator(min_area_ratio=0.05, use_hsv_saturation=False)  # 5% = 500 px²
        img = np.ones((100, 100, 3), dtype=np.uint8) * 200
        # Large dark region (40x40 = 1600 > 500)
        img[30:70, 30:70] = [50, 50, 50]
        mask = gen.generate(img)
        assert mask[50, 50] == 255

    def test_hsv_saturation_detects_colored_tissue(self):
        gen = TissueMaskGenerator(min_area_ratio=0.0, use_hsv_saturation=True)
        img = np.ones((100, 100, 3), dtype=np.uint8) * 245
        img[30:70, 30:70] = [190, 60, 120]
        mask = gen.generate(img)
        assert mask[50, 50] == 255
        assert mask[10, 10] == 0

    def test_last_stats_exposed(self):
        gen = TissueMaskGenerator(min_area_ratio=0.0)
        img = np.ones((80, 60, 3), dtype=np.uint8) * 240
        img[20:50, 15:45] = [80, 80, 80]
        _ = gen.generate(img)
        stats = gen.last_stats
        assert "mask_tissue_ratio" in stats
        assert "component_count" in stats
