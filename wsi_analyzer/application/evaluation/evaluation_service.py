from wsi_analyzer.domain.evaluation import (
    EvalBox, EvaluationMetrics, EvaluationResult,
    detections_to_eval_boxes, geojson_annotations_to_eval_boxes,
    match_predictions_to_ground_truth, compute_detection_metrics, compute_ap50,
)


class EvaluationService:
    def evaluate_slide(
        self,
        slide_id: str,
        predictions: list[EvalBox],
        ground_truths: list[EvalBox],
        iou_threshold: float = 0.5,
    ) -> EvaluationResult:
        matches = match_predictions_to_ground_truth(
            predictions, ground_truths, iou_threshold=iou_threshold,
        )
        metrics = compute_detection_metrics(matches)
        ap50 = compute_ap50(predictions, ground_truths, iou_threshold)
        return EvaluationResult(
            slide_id=slide_id,
            iou_threshold=iou_threshold,
            metrics=EvaluationMetrics(
                tp=metrics.tp, fp=metrics.fp, fn=metrics.fn,
                precision=metrics.precision, recall=metrics.recall,
                f1=metrics.f1, ap50=round(ap50, 4),
            ),
            matches=matches,
        )

    def evaluate_from_files(
        self,
        slide_id: str,
        prediction_json_path: str,
        ground_truth_geojson_path: str,
        iou_threshold: float = 0.5,
    ) -> EvaluationResult:
        import json
        with open(prediction_json_path, "r", encoding="utf-8") as f:
            pred_data = json.load(f)
        pred_boxes = detections_to_eval_boxes(
            pred_data.get("results", pred_data.get("detections", [])), slide_id,
        )
        gt_boxes = geojson_annotations_to_eval_boxes(
            ground_truth_geojson_path, slide_id,
        )
        return self.evaluate_slide(slide_id, pred_boxes, gt_boxes, iou_threshold)
