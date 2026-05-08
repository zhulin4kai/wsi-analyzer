import numpy as np

from wsi_analyzer.domain.detection.entities import Detection
from wsi_analyzer.domain.slide.coordinates import Level0Box


class TestDetection:
    def test_create(self):
        bbox = Level0Box(10, 20, 30, 40)
        d = Detection(bbox=bbox, confidence=0.95, class_id=1)
        assert d.bbox == bbox
        assert d.confidence == 0.95
        assert d.class_id == 1

    def test_immutable(self):
        d = Detection(bbox=Level0Box(0, 0, 1, 1), confidence=0.5, class_id=0)
        try:
            d.confidence = 1.0
            assert False, "should raise"
        except Exception:
            pass


class TestAnalysisResult:
    def test_completed(self):
        from wsi_analyzer.domain.detection.entities import AnalysisResult
        dets = [Detection(bbox=Level0Box(0, 0, 10, 10), confidence=0.9, class_id=1)]
        r = AnalysisResult(status="completed", detections=dets, total_patches=100, processed_patches=100)
        assert r.status == "completed"
        assert len(r.detections) == 1

    def test_interrupted_with_raw(self):
        from wsi_analyzer.domain.detection.entities import AnalysisResult
        r = AnalysisResult(
            status="interrupted",
            detections=[],
            total_patches=50,
            processed_patches=30,
            raw_boxes=[[0, 0, 10, 10]],
            raw_scores=[0.8],
            raw_classes=[1],
        )
        assert r.raw_boxes == [[0, 0, 10, 10]]
        assert r.raw_scores == [0.8]

    def test_error_with_message(self):
        from wsi_analyzer.domain.detection.entities import AnalysisResult
        r = AnalysisResult(
            status="error", detections=[], total_patches=0, processed_patches=0,
            message="No tissue found"
        )
        assert r.status == "error"
        assert r.message == "No tissue found"
