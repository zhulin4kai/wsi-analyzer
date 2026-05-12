from wsi_analyzer.domain.evaluation.entities import (
    EvalBox, EvaluationMetrics, MatchRecord,
)
from wsi_analyzer.domain.evaluation.matching import match_predictions_to_ground_truth


def compute_detection_metrics(matches: list[MatchRecord]) -> EvaluationMetrics:
    tp = sum(1 for m in matches if m.status == "TP")
    fp = sum(1 for m in matches if m.status == "FP")
    fn = sum(1 for m in matches if m.status == "FN")

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return EvaluationMetrics(
        tp=tp, fp=fp, fn=fn,
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
    )


def compute_ap50(
    predictions: list[EvalBox],
    ground_truths: list[EvalBox],
    iou_threshold: float = 0.5,
) -> float:
    """Compute AP@50 using 11-point interpolation.

    Steps:
      1. Sort predictions by confidence descending.
      2. For each confidence threshold, match predictions to GT and compute P/R.
      3. Interpolate precision at 11 recall levels [0, 0.1, ..., 1.0].
      4. Average the interpolated precisions.
    """
    if not predictions or not ground_truths:
        return 0.0

    sorted_preds = sorted(
        predictions,
        key=lambda p: p.confidence if p.confidence is not None else 0.0,
        reverse=True,
    )
    n_gt = len(ground_truths)

    tp_cumul = 0
    fp_cumul = 0
    precisions: list[float] = []
    recalls: list[float] = []
    matched_gt: set[str] = set()

    for pred in sorted_preds:
        best_gt: EvalBox | None = None
        best_iou = 0.0
        for gt in ground_truths:
            if gt.box_id in matched_gt:
                continue
            iou = _box_iou_fast(pred, gt)
            if iou > best_iou:
                best_iou = iou
                best_gt = gt

        if best_iou >= iou_threshold and best_gt is not None:
            matched_gt.add(best_gt.box_id)
            tp_cumul += 1
        else:
            fp_cumul += 1

        precision = tp_cumul / (tp_cumul + fp_cumul) if (tp_cumul + fp_cumul) > 0 else 0.0
        recall = tp_cumul / n_gt
        precisions.append(precision)
        recalls.append(recall)

    # 11-point interpolation
    ap = 0.0
    for r_level in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
        max_p = 0.0
        for p, r in zip(precisions, recalls):
            if r >= r_level and p > max_p:
                max_p = p
        ap += max_p
    return ap / 11.0


def _box_iou_fast(a: EvalBox, b: EvalBox) -> float:
    inter_x1 = max(a.x1, b.x1)
    inter_y1 = max(a.y1, b.y1)
    inter_x2 = min(a.x2, b.x2)
    inter_y2 = min(a.y2, b.y2)
    if inter_x1 >= inter_x2 or inter_y1 >= inter_y2:
        return 0.0
    inter = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
    area_a = (a.x2 - a.x1) * (a.y2 - a.y1) if a.x2 >= a.x1 and a.y2 >= a.y1 else 0.0
    area_b = (b.x2 - b.x1) * (b.y2 - b.y1) if b.x2 >= b.x1 and b.y2 >= b.y1 else 0.0
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0
