import importlib.machinery
import sys
import types

import numpy as np

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

from wsi_analyzer.domain.slide.coordinates import PatchCoordinate
from wsi_analyzer.infrastructure.inference.prediction_mapper import PredictionMapper


def _coord(x=100, y=200, level0_size=1024, model_input_size=512):
    return PatchCoordinate(
        x=x,
        y=y,
        level0_size=level0_size,
        model_input_size=model_input_size,
        read_level=0,
        read_downsample=1.0,
    )


def test_to_level0_single_empty_predictions():
    boxes, scores, classes = PredictionMapper.to_level0_single(
        np.empty((0, 4), dtype=np.float32),
        np.empty((0,), dtype=np.float32),
        np.empty((0,), dtype=np.float32),
        _coord(),
    )

    assert boxes == []
    assert scores == []
    assert classes == []


def test_to_level0_single_vectorized_mapping_matches_expected():
    boxes, scores, classes = PredictionMapper.to_level0_single(
        np.array([[0, 0, 10, 20], [5, 10, 15, 25]], dtype=np.float32),
        np.array([0.9, 0.7], dtype=np.float32),
        np.array([1, 2], dtype=np.float32),
        _coord(),
    )

    assert boxes == [[100.0, 200.0, 120.0, 240.0], [110.0, 220.0, 130.0, 250.0]]
    assert scores == [np.float32(0.9), np.float32(0.7)]
    assert classes == [np.float32(1), np.float32(2)]


def test_to_level0_batch_handles_mixed_empty_results():
    raw_predictions = [
        (
            np.array([[1, 2, 3, 4]], dtype=np.float32),
            np.array([0.8], dtype=np.float32),
            np.array([0], dtype=np.float32),
        ),
        (
            np.empty((0, 4), dtype=np.float32),
            np.empty((0,), dtype=np.float32),
            np.empty((0,), dtype=np.float32),
        ),
        (
            np.array([[0, 0, 2, 2]], dtype=np.float32),
            np.array([0.6], dtype=np.float32),
            np.array([1], dtype=np.float32),
        ),
    ]
    coords = [_coord(x=10, y=20, level0_size=512), _coord(), _coord(x=50, y=60)]

    boxes, scores, classes = PredictionMapper.to_level0_batch(raw_predictions, coords)

    assert boxes == [[11.0, 22.0, 13.0, 24.0], [50.0, 60.0, 54.0, 64.0]]
    assert scores == [np.float32(0.8), np.float32(0.6)]
    assert classes == [np.float32(0), np.float32(1)]
