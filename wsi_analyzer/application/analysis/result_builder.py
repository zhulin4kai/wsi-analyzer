from wsi_analyzer.domain.analysis.result import AnalysisResult
from wsi_analyzer.domain.detection.entities import Detection
from wsi_analyzer.domain.slide.coordinates import Level0Box


def _boxes_to_detections(boxes: list, scores: list, classes: list) -> list:
    return [
        Detection(bbox=Level0Box(*b[:4]), confidence=s, class_id=c)
        for b, s, c in zip(boxes, scores, classes)
    ]


class AnalysisResultBuilder:
    @staticmethod
    def completed(
        raw_boxes,
        raw_scores,
        raw_classes,
        valid_coords,
        processed_patches,
        total_patches,
    ) -> AnalysisResult:
        detections = _boxes_to_detections(raw_boxes, raw_scores, raw_classes)
        return AnalysisResult(
            status="completed",
            detections=detections,
            valid_coords=valid_coords,
            processed_patches=processed_patches,
            total_patches=total_patches,
        )

    @staticmethod
    def interrupted(
        raw_boxes,
        raw_scores,
        raw_classes,
        valid_coords,
        processed_patches,
        total_patches,
    ) -> AnalysisResult:
        detections = _boxes_to_detections(raw_boxes, raw_scores, raw_classes)
        return AnalysisResult(
            status="interrupted",
            detections=detections,
            valid_coords=valid_coords,
            processed_patches=processed_patches,
            total_patches=total_patches,
            raw_boxes=raw_boxes,
            raw_scores=raw_scores,
            raw_classes=raw_classes,
        )

    @staticmethod
    def error(message: str) -> AnalysisResult:
        return AnalysisResult(status="error", message=message)
