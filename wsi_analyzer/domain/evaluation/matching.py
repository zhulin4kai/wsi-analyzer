from wsi_analyzer.domain.evaluation.entities import EvalBox, MatchRecord


def box_iou(a: EvalBox, b: EvalBox) -> float:
    """Intersection over Union between two axis-aligned boxes.

    Returns 0.0 when boxes are disjoint or invalid.
    """
    a = a.normalize()
    b = b.normalize()

    inter_x1 = max(a.x1, b.x1)
    inter_y1 = max(a.y1, b.y1)
    inter_x2 = min(a.x2, b.x2)
    inter_y2 = min(a.y2, b.y2)

    if inter_x1 >= inter_x2 or inter_y1 >= inter_y2:
        return 0.0

    inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
    a_area = a.area()
    b_area = b.area()
    union_area = a_area + b_area - inter_area

    if union_area <= 0:
        return 0.0
    return inter_area / union_area


def match_predictions_to_ground_truth(
    predictions: list[EvalBox],
    ground_truths: list[EvalBox],
    iou_threshold: float = 0.5,
    class_aware: bool = True,
) -> list[MatchRecord]:
    """Greedy one-to-one matching of predictions to ground truth boxes.

    Rules:
      1. Process predictions by confidence descending.
      2. Each prediction matches at most one GT (the best IoU >= threshold).
      3. Each GT is matched at most once.
      4. Matched → TP. Unmatched prediction → FP. Unmatched GT → FN.
    """
    sorted_preds = sorted(
        predictions,
        key=lambda p: p.confidence if p.confidence is not None else 0.0,
        reverse=True,
    )
    matched_gt_ids: set[str] = set()
    records: list[MatchRecord] = []

    for pred in sorted_preds:
        best_gt: EvalBox | None = None
        best_iou = 0.0
        for gt in ground_truths:
            if gt.box_id in matched_gt_ids:
                continue
            if class_aware and pred.class_id != gt.class_id:
                continue
            current_iou = box_iou(pred, gt)
            if current_iou > best_iou:
                best_iou = current_iou
                best_gt = gt

        if best_iou >= iou_threshold and best_gt is not None:
            matched_gt_ids.add(best_gt.box_id)
            records.append(MatchRecord(prediction=pred, ground_truth=best_gt,
                                       iou=best_iou, status="TP"))
        else:
            records.append(MatchRecord(prediction=pred, ground_truth=None,
                                       iou=best_iou, status="FP"))

    # unmatched GTs → FN
    for gt in ground_truths:
        if gt.box_id not in matched_gt_ids:
            records.append(MatchRecord(prediction=None, ground_truth=gt,
                                       iou=0.0, status="FN"))

    return records
