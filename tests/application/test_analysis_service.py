import importlib.machinery
import logging
import sys
import types
from types import SimpleNamespace

openslide = types.ModuleType("openslide")
openslide.OpenSlide = lambda *args, **kwargs: None
openslide.PROPERTY_NAME_MPP_X = "mpp-x"
openslide.PROPERTY_NAME_MPP_Y = "mpp-y"
openslide.PROPERTY_NAME_OBJECTIVE_POWER = "objective-power"
sys.modules.setdefault("openslide", openslide)

pyside = types.ModuleType("PySide6")
qtgui = types.ModuleType("PySide6.QtGui")
qtgui.QImage = object
sys.modules.setdefault("PySide6", pyside)
sys.modules.setdefault("PySide6.QtGui", qtgui)

tqdm_module = types.ModuleType("tqdm")
tqdm_module.tqdm = lambda *args, **kwargs: None
tqdm_module.__spec__ = importlib.machinery.ModuleSpec("tqdm", loader=None)
sys.modules.setdefault("tqdm", tqdm_module)

ultralytics = types.ModuleType("ultralytics")
ultralytics.YOLO = object
ultralytics.__spec__ = importlib.machinery.ModuleSpec("ultralytics", loader=None)
sys.modules.setdefault("ultralytics", ultralytics)

config_module = types.ModuleType("config")
sys.modules.setdefault("config", config_module)

from wsi_analyzer.application.analysis.analysis_service import FullSlideAnalysisService


def test_apply_nms_logs_timing_without_changing_result(caplog):
    service = FullSlideAnalysisService(
        coordinate_service=None,
        inferencer=None,
        config=SimpleNamespace(nms_iou_thresh=0.1),
        session=None,
        geometry=None,
    )
    boxes = [[0, 0, 10, 10], [0, 0, 10, 10], [100, 100, 110, 110]]
    scores = [0.9, 0.8, 0.7]
    classes = [1, 1, 2]

    caplog.set_level(logging.INFO, logger="WSIAnalyzer")
    kept_boxes, kept_scores, kept_classes = service._apply_nms(boxes, scores, classes)

    assert kept_boxes == [[0.0, 0.0, 10.0, 10.0], [100.0, 100.0, 110.0, 110.0]]
    assert kept_scores == [0.9, 0.7]
    assert kept_classes == [1, 2]
    assert any("[nms timing]" in record.message for record in caplog.records)
