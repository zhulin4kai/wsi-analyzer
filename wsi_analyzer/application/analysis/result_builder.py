from wsi_analyzer.domain.analysis.inference_geometry import InferenceGeometry
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
        raw_boxes_all=None,
        raw_scores_all=None,
        raw_classes_all=None,
    ) -> AnalysisResult:
        """raw_boxes/scores/classes are post-NMS final detections.
        raw_*_all (if provided) are pre-NMS raw for forward compat / review.
        """
        detections = _boxes_to_detections(raw_boxes, raw_scores, raw_classes)
        return AnalysisResult(
            status="completed",
            detections=detections,
            valid_coords=valid_coords,
            processed_patches=processed_patches,
            total_patches=total_patches,
            raw_boxes=raw_boxes_all,
            raw_scores=raw_scores_all,
            raw_classes=raw_classes_all,
        )

    @staticmethod
    def interrupted(
        final_boxes,
        final_scores,
        final_classes,
        raw_boxes,
        raw_scores,
        raw_classes,
        valid_coords,
        processed_patches,
        total_patches,
        geometry: InferenceGeometry | None = None,
    ) -> AnalysisResult:
        """final_*: NMS-filtered detections for UI display.
        raw_*:   PRE-NMS raw detections for resume merge.
        """
        detections = _boxes_to_detections(final_boxes, final_scores, final_classes)
        return AnalysisResult(
            status="interrupted",
            detections=detections,
            valid_coords=valid_coords,
            processed_patches=processed_patches,
            total_patches=total_patches,
            raw_boxes=raw_boxes,
            raw_scores=raw_scores,
            raw_classes=raw_classes,
            level0_window_size=geometry.level0_window_size if geometry else 0,
            level0_stride=geometry.level0_stride if geometry else 0,
            model_input_size=geometry.model_input_size if geometry else 0,
            read_level=geometry.read_level if geometry else 0,
            read_downsample=geometry.read_downsample if geometry else 0.0,
        )

    @staticmethod
    def error(message: str) -> AnalysisResult:
        return AnalysisResult(status="error", message=message)
