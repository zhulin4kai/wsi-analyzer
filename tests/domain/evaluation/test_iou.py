import pytest
from wsi_analyzer.domain.evaluation import EvalBox
from wsi_analyzer.domain.evaluation.matching import box_iou


def make_box(box_id="b1", slide_id="s1", x1=0.0, y1=0.0, x2=10.0, y2=10.0):
    return EvalBox(box_id=box_id, slide_id=slide_id, x1=x1, y1=y1, x2=x2, y2=y2)


class TestBoxIoU:
    def test_identical_boxes(self):
        a = make_box(x1=0, y1=0, x2=10, y2=10)
        b = make_box(x1=0, y1=0, x2=10, y2=10)
        assert box_iou(a, b) == 1.0

    def test_no_overlap(self):
        a = make_box(x1=0, y1=0, x2=10, y2=10)
        b = make_box(x1=20, y1=20, x2=30, y2=30)
        assert box_iou(a, b) == 0.0

    def test_partial_overlap(self):
        a = make_box(x1=0, y1=0, x2=10, y2=10)
        b = make_box(x1=5, y1=5, x2=15, y2=15)
        iou = box_iou(a, b)
        # inter=25, union=175, iou=0.142...
        assert 0.14 < iou < 0.15

    def test_edge_touching(self):
        a = make_box(x1=0, y1=0, x2=10, y2=10)
        b = make_box(x1=10, y1=0, x2=20, y2=10)
        assert box_iou(a, b) == 0.0

    def test_invalid_box_normalized(self):
        a = EvalBox(box_id="a", slide_id="s", x1=10, y1=10, x2=0, y2=0)
        b = make_box(x1=0, y1=0, x2=10, y2=10)
        iou = box_iou(a, b)
        assert iou == 1.0

    def test_zero_area(self):
        a = make_box(x1=0, y1=0, x2=0, y2=0)
        b = make_box(x1=0, y1=0, x2=0, y2=0)
        assert box_iou(a, b) == 0.0
