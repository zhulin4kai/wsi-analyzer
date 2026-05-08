import numpy as np

from wsi_analyzer.domain.detection.nms import nms_numpy


class TestNMS:
    def test_empty_returns_empty(self):
        result = nms_numpy(
            np.empty((0, 4), dtype=np.float32),
            np.empty((0,), dtype=np.float32),
            0.5,
        )
        assert len(result) == 0

    def test_single_box_kept(self):
        boxes = np.array([[10, 10, 50, 50]], dtype=np.float32)
        scores = np.array([0.9], dtype=np.float32)
        result = nms_numpy(boxes, scores, 0.5)
        assert list(result) == [0]

    def test_non_overlapping_kept(self):
        boxes = np.array([
            [10, 10, 20, 20],
            [100, 100, 120, 120],
        ], dtype=np.float32)
        scores = np.array([0.9, 0.8], dtype=np.float32)
        result = nms_numpy(boxes, scores, 0.5)
        assert sorted(result.tolist()) == [0, 1]

    def test_fully_overlapping_suppressed(self):
        boxes = np.array([
            [10, 10, 100, 100],
            [10, 10, 100, 100],
        ], dtype=np.float32)
        scores = np.array([0.9, 0.8], dtype=np.float32)
        result = nms_numpy(boxes, scores, 0.1)
        # Higher score should win, lower suppressed
        assert 0 in result
        assert 1 not in result

    def test_order_by_confidence(self):
        boxes = np.array([
            [0, 0, 10, 10],
            [0, 0, 10, 10],
            [0, 0, 10, 10],
        ], dtype=np.float32)
        scores = np.array([0.3, 0.9, 0.6], dtype=np.float32)
        result = nms_numpy(boxes, scores, 0.1)
        assert list(result) == [1]  # index 1 has highest score

    def test_partial_overlap(self):
        boxes = np.array([
            [0, 0, 100, 100],
            [50, 50, 150, 150],  # ~25% IoU with first
            [200, 200, 300, 300],
        ], dtype=np.float32)
        scores = np.array([0.9, 0.8, 0.7], dtype=np.float32)
        # IoU(0,1) = 0.142..., IoU threshold 0.5 => both kept
        result = nms_numpy(boxes, scores, 0.5)
        assert list(result) == [0, 1, 2]
