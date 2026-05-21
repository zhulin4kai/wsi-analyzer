from dataclasses import dataclass
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
tqdm_module.tqdm = lambda *args, **kwargs: _NoopProgress()
tqdm_module.__spec__ = importlib.machinery.ModuleSpec("tqdm", loader=None)
sys.modules.setdefault("tqdm", tqdm_module)

ultralytics = types.ModuleType("ultralytics")
ultralytics.YOLO = object
ultralytics.__spec__ = importlib.machinery.ModuleSpec("ultralytics", loader=None)
sys.modules.setdefault("ultralytics", ultralytics)

from wsi_analyzer.infrastructure.inference.batch_inferencer import BatchInferencer


@dataclass(frozen=True)
class _Coord:
    idx: int

    @property
    def x(self):
        return self.idx * 10

    @property
    def y(self):
        return 0

    @property
    def local_to_level0_scale(self):
        return 1.0


class _Reader:
    def __init__(self):
        self.read_indices = []

    def read(self, coord):
        self.read_indices.append(coord.idx)
        return coord


class _Adapter:
    def __init__(self, fail_first_large_batch=False):
        self.fail_first_large_batch = fail_first_large_batch
        self.calls = []

    def predict(self, batch_imgs, device, conf_thresh, imgsz=None):
        indices = [img.idx for img in batch_imgs]
        self.calls.append(indices)
        if self.fail_first_large_batch and len(batch_imgs) > 1:
            self.fail_first_large_batch = False
            raise RuntimeError("out of memory")

        results = []
        for _img in batch_imgs:
            results.append((
                np.array([[0.0, 0.0, 1.0, 1.0]], dtype=np.float32),
                np.array([0.9], dtype=np.float32),
                np.array([0], dtype=np.float32),
            ))
        return results


def _coords(count):
    return [_Coord(i) for i in range(count)]


def test_infer_preserves_order_and_progress(monkeypatch):
    monkeypatch.setattr(
        "wsi_analyzer.infrastructure.inference.batch_inferencer.tqdm",
        lambda *args, **kwargs: _NoopProgress(),
    )
    adapter = _Adapter()
    reader = _Reader()
    inferencer = BatchInferencer(adapter, reader, "cpu", 2, 0.5, 512)
    progress = []

    boxes, scores, classes, processed = inferencer.infer(
        _coords(5),
        progress_callback=progress.append,
    )

    assert processed == 5
    assert adapter.calls == [[0, 1], [2, 3], [4]]
    assert progress == [2, 4, 5]
    assert [box[0] for box in boxes] == [0, 10, 20, 30, 40]
    assert len(scores) == 5
    assert len(classes) == 5


def test_infer_cancel_stops_before_next_prefetched_batch(monkeypatch):
    monkeypatch.setattr(
        "wsi_analyzer.infrastructure.inference.batch_inferencer.tqdm",
        lambda *args, **kwargs: _NoopProgress(),
    )
    adapter = _Adapter()
    inferencer = BatchInferencer(adapter, _Reader(), "cpu", 2, 0.5, 512)
    cancelled = False

    def progress_callback(_processed):
        nonlocal cancelled
        cancelled = True

    _boxes, _scores, _classes, processed = inferencer.infer(
        _coords(5),
        progress_callback=progress_callback,
        cancel_check=lambda: cancelled,
    )

    assert processed == 2
    assert adapter.calls == [[0, 1]]


def test_infer_oom_retries_failed_batch_from_start(monkeypatch):
    monkeypatch.setattr(
        "wsi_analyzer.infrastructure.inference.batch_inferencer.tqdm",
        lambda *args, **kwargs: _NoopProgress(),
    )
    adapter = _Adapter(fail_first_large_batch=True)
    inferencer = BatchInferencer(adapter, _Reader(), "cpu", 4, 0.5, 512)
    progress = []

    boxes, _scores, _classes, processed = inferencer.infer(
        _coords(5),
        progress_callback=progress.append,
    )

    assert processed == 5
    assert inferencer.batch_size == 2
    assert adapter.calls == [[0, 1, 2, 3], [0, 1], [2, 3], [4]]
    assert progress == [2, 4, 5]
    assert [box[0] for box in boxes] == [0, 10, 20, 30, 40]


def test_prefetch_batches_shrink_when_memory_is_tight(monkeypatch):
    monkeypatch.setattr(
        "wsi_analyzer.infrastructure.inference.batch_inferencer._available_memory_bytes",
        lambda: 1,
    )
    inferencer = BatchInferencer(_Adapter(), _Reader(), "cpu", 16, 0.5, 4096)

    assert inferencer._resolve_prefetch_batches() == 1


def test_prefetch_batches_are_bounded(monkeypatch):
    monkeypatch.setattr(
        "wsi_analyzer.infrastructure.inference.batch_inferencer._available_memory_bytes",
        lambda: 1024 * 1024 * 1024 * 1024,
    )
    inferencer = BatchInferencer(_Adapter(), _Reader(), "cpu", 1, 0.5, 128)

    assert inferencer._resolve_prefetch_batches() == 4


class _NoopProgress:
    def update(self, _count):
        pass

    def close(self):
        pass
