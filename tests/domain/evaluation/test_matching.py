from wsi_analyzer.domain.evaluation import EvalBox, MatchRecord
from wsi_analyzer.domain.evaluation.matching import match_predictions_to_ground_truth


def _pred(box_id="p1", slide_id="s1", conf=0.9, class_id=0, x1=0.0, y1=0.0, x2=10.0, y2=10.0):
    return EvalBox(box_id=box_id, slide_id=slide_id, confidence=conf, class_id=class_id,
                   x1=x1, y1=y1, x2=x2, y2=y2, source="prediction")


def _gt(box_id="g1", slide_id="s1", class_id=0, x1=0.0, y1=0.0, x2=10.0, y2=10.0):
    return EvalBox(box_id=box_id, slide_id=slide_id, confidence=None, class_id=class_id,
                   x1=x1, y1=y1, x2=x2, y2=y2, source="ground_truth")


class TestMatching:
    def test_tp(self):
        preds = [_pred(conf=0.9)]
        gts = [_gt()]
        matches = match_predictions_to_ground_truth(preds, gts)
        assert matches[0].status == "TP"
        assert matches[0].iou == 1.0

    def test_fp(self):
        preds = [_pred(x2=20, y2=20)]
        gts = [_gt()]
        matches = match_predictions_to_ground_truth(preds, gts)
        assert matches[0].status == "FP"

    def test_fn(self):
        preds = []
        gts = [_gt()]
        matches = match_predictions_to_ground_truth(preds, gts)
        assert matches[0].status == "FN"

    def test_highest_confidence_wins(self):
        preds = [
            _pred("p1", conf=0.9, x1=0, y1=0, x2=10, y2=10),
            _pred("p2", conf=0.6, x1=1, y1=1, x2=11, y2=11),
        ]
        gts = [_gt(x1=0, y1=0, x2=10, y2=10)]
        matches = match_predictions_to_ground_truth(preds, gts)
        tp = [m for m in matches if m.status == "TP"]
        fp = [m for m in matches if m.status == "FP"]
        assert len(tp) == 1
        assert tp[0].prediction.box_id == "p1"
        assert len(fp) == 1
        assert fp[0].prediction.box_id == "p2"

    def test_gt_matched_once(self):
        preds = [
            _pred("p1", conf=0.9),
            _pred("p2", conf=0.85),
        ]
        gts = [_gt("g1")]
        matches = match_predictions_to_ground_truth(preds, gts)
        tp = [m for m in matches if m.status == "TP"]
        fp = [m for m in matches if m.status == "FP"]
        assert len(tp) == 1
        assert len(fp) == 1

    def test_below_threshold(self):
        preds = [_pred(x2=20, y2=20)]
        gts = [_gt(x1=0, y1=0, x2=10, y2=10)]
        matches = match_predictions_to_ground_truth(preds, gts, iou_threshold=0.5)
        assert matches[0].status == "FP"
        # GT is also unmatched → FN
        fn = [m for m in matches if m.status == "FN"]
        assert len(fn) == 1

    def test_class_aware_separates(self):
        preds = [_pred(class_id=1)]
        gts = [_gt(class_id=0)]
        matches = match_predictions_to_ground_truth(preds, gts, class_aware=True)
        fp = [m for m in matches if m.status == "FP"]
        fn = [m for m in matches if m.status == "FN"]
        assert len(fp) == 1
        assert len(fn) == 1
