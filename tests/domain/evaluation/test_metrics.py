from wsi_analyzer.domain.evaluation import (
    EvalBox, MatchRecord, compute_detection_metrics, compute_ap50,
)


def _pred(conf=0.9, box_id="p1", x1=0.0, y1=0.0, x2=10.0, y2=10.0):
    return EvalBox(box_id=box_id, slide_id="s1", confidence=conf,
                   x1=x1, y1=y1, x2=x2, y2=y2, source="prediction")


def _gt(box_id="g1", x1=0.0, y1=0.0, x2=10.0, y2=10.0):
    return EvalBox(box_id=box_id, slide_id="s1", confidence=None,
                   x1=x1, y1=y1, x2=x2, y2=y2, source="ground_truth")


class TestMetrics:
    def test_standard_case(self):
        matches = [
            MatchRecord(prediction=_pred(), ground_truth=_gt(), iou=0.8, status="TP"),
            MatchRecord(prediction=_pred(), ground_truth=_gt(), iou=0.8, status="TP"),
            MatchRecord(prediction=_pred(), ground_truth=_gt(), iou=0.8, status="TP"),
            MatchRecord(prediction=_pred(), ground_truth=_gt(), iou=0.8, status="TP"),
            MatchRecord(prediction=_pred(), ground_truth=_gt(), iou=0.8, status="TP"),
            MatchRecord(prediction=_pred(), ground_truth=_gt(), iou=0.8, status="TP"),
            MatchRecord(prediction=_pred(), ground_truth=_gt(), iou=0.8, status="TP"),
            MatchRecord(prediction=_pred(), ground_truth=_gt(), iou=0.8, status="TP"),
            MatchRecord(prediction=_pred(), ground_truth=None, iou=0.0, status="FP"),
            MatchRecord(prediction=_pred(), ground_truth=None, iou=0.0, status="FP"),
            MatchRecord(prediction=None, ground_truth=_gt(), iou=0.0, status="FN"),
            MatchRecord(prediction=None, ground_truth=_gt(), iou=0.0, status="FN"),
        ]
        m = compute_detection_metrics(matches)
        assert m.tp == 8
        assert m.fp == 2
        assert m.fn == 2
        assert m.precision == 0.8
        assert m.recall == 0.8
        assert m.f1 == 0.8

    def test_no_predictions(self):
        matches = [MatchRecord(prediction=None, ground_truth=_gt(), iou=0.0, status="FN")]
        m = compute_detection_metrics(matches)
        assert m.tp == 0
        assert m.precision == 0.0
        assert m.recall == 0.0
        assert m.f1 == 0.0

    def test_no_gt(self):
        matches = [MatchRecord(prediction=_pred(), ground_truth=None, iou=0.0, status="FP")]
        m = compute_detection_metrics(matches)
        assert m.fp == 1
        assert m.recall == 0.0

    def test_all_fp(self):
        matches = [MatchRecord(prediction=_pred(), ground_truth=None, iou=0.0, status="FP")
                   for _ in range(5)]
        m = compute_detection_metrics(matches)
        assert m.precision == 0.0
        assert m.recall == 0.0

    def test_all_fn(self):
        matches = [MatchRecord(prediction=None, ground_truth=_gt(), iou=0.0, status="FN")
                   for _ in range(5)]
        m = compute_detection_metrics(matches)
        assert m.recall == 0.0


class TestAP50:
    def test_perfect_detection(self):
        preds = [_pred(conf=0.9, x1=0, y1=0, x2=10, y2=10),
                 _pred(conf=0.8, x1=10, y1=10, x2=20, y2=20)]
        gts = [_gt("g1", 0, 0, 10, 10), _gt("g2", 10, 10, 20, 20)]
        ap = compute_ap50(preds, gts)
        assert ap == 1.0

    def test_all_false_positives(self):
        preds = [_pred(conf=0.5, x1=100, y1=100, x2=110, y2=110)]
        gts = [_gt("g1", 0, 0, 10, 10)]
        ap = compute_ap50(preds, gts)
        assert ap == 0.0

    def test_no_predictions(self):
        ap = compute_ap50([], [_gt()])
        assert ap == 0.0

    def test_no_gt(self):
        ap = compute_ap50([_pred()], [])
        assert ap == 0.0
