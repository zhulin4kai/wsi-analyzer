import json
import time
from pathlib import Path
from typing import Optional

from wsi_analyzer.app.dependency_container import container
from wsi_analyzer.application.evaluation import EvaluationService
from wsi_analyzer.domain.evaluation import (
    EvaluationResult, EvalBox,
    detections_to_eval_boxes, geojson_annotations_to_eval_boxes,
)


class BatchEvaluationService:
    def __init__(self, model_path: str) -> None:
        self._model_path = model_path
        self._eval_service = EvaluationService()

    def run_single(
        self,
        slide_id: str,
        wsi_path: str,
        gt_path: str,
        iou_threshold: float = 0.5,
        resume_data: Optional[dict] = None,
    ) -> EvaluationResult:
        factory = container.analysis_service_factory
        handle = factory.create(wsi_path, self._model_path)
        try:
            t0 = time.perf_counter()
            result_dict = handle.service.run(
                progress_callback=None,
                status_callback=None,
                resume_data=resume_data,
            )
            elapsed = time.perf_counter() - t0

            predictions = detections_to_eval_boxes(
                result_dict.detections, slide_id,
            )
            ground_truths = geojson_annotations_to_eval_boxes(gt_path, slide_id)

            eval_result = self._eval_service.evaluate_slide(
                slide_id, predictions, ground_truths, iou_threshold,
            )
            # attach timing metadata via dict (not stored on frozen dataclass)
            setattr(eval_result, "analysis_seconds", round(elapsed, 2))
            setattr(eval_result, "detection_count", len(predictions))
            setattr(eval_result, "gt_count", len(ground_truths))
            return eval_result
        finally:
            handle.close()
