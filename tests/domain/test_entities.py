import numpy as np

from wsi_analyzer.domain.analysis.result import AnalysisResult
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
            setattr(d, 'confidence', 1.0)
            assert False, "should raise"
        except Exception:
            pass


class TestAnalysisResult:
    def test_completed(self):
        dets = [Detection(bbox=Level0Box(0, 0, 10, 10), confidence=0.9, class_id=1)]
        r = AnalysisResult(status="completed", detections=dets, total_patches=100, processed_patches=100)
        assert r.status == "completed"
        assert len(r.detections) == 1

    def test_interrupted_with_raw(self):
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
        r = AnalysisResult(
            status="error", detections=[], total_patches=0, processed_patches=0,
            message="No tissue found"
        )
        assert r.status == "error"
        assert r.message == "No tissue found"

    def test_to_dict(self):
        dets = [Detection(bbox=Level0Box(10, 20, 30, 40), confidence=0.95, class_id=1)]
        r = AnalysisResult(
            status="completed", detections=dets,
            total_patches=100, processed_patches=100,
            valid_coords=[(0, 1)],
        )
        d = r.to_dict()
        assert d["status"] == "completed"
        assert d["results"][0]["bbox"] == [10, 20, 30, 40]
        assert d["results"][0]["confidence"] == 0.95
        assert d["results"][0]["class_id"] == 1
        assert d["valid_coords"] == [(0, 1)]
        assert d["total_patches"] == 100

    def test_from_cache(self):
        cache = {
            "status": "completed",
            "results": [{"bbox": [1, 2, 3, 4], "confidence": 0.8, "class_id": 2}],
            "total_patches": 50,
            "processed_patches": 50,
        }
        r = AnalysisResult.from_cache(cache)
        assert r.status == "completed"
        assert len(r.detections) == 1
        assert r.detections[0].bbox == Level0Box(1, 2, 3, 4)
