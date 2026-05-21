import importlib.machinery
import sys
import types

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

from wsi_analyzer.application.analysis.analysis_config_resolver import (
    AnalysisConfigResolver,
)


class _Db:
    def __init__(self, settings=None, profile=None, auto_tune=False):
        self._settings = settings or {}
        self._profile = profile
        self._auto_tune = auto_tune

    def get_setting(self, key, default=None):
        return self._settings.get(key, default)

    def get_system_profile(self, drive_prefix):
        return self._profile

    def get_auto_tune_enabled(self):
        return self._auto_tune


def _resolve(monkeypatch, db, detected_device="cuda"):
    monkeypatch.setattr(
        "wsi_analyzer.application.analysis.analysis_config_resolver."
        "HardwareProfiler.get_storage_key",
        lambda path: "/slides",
    )
    monkeypatch.setattr(
        "wsi_analyzer.application.analysis.analysis_config_resolver."
        "HardwareProfiler.get_compute_device",
        lambda: detected_device,
    )
    monkeypatch.setattr(
        "wsi_analyzer.application.analysis.analysis_config_resolver."
        "os.path.getsize",
        lambda path: 100 * 1024 * 1024,
    )
    resolver = AnalysisConfigResolver(db)
    return resolver.resolve("/slides/a.svs", "/models/a.pt")


def test_default_device_mode_is_cpu_even_when_profile_has_cuda(monkeypatch):
    db = _Db(profile={"device": "cuda", "batch_size": 8})

    config = _resolve(monkeypatch, db, detected_device="cuda")

    assert config.device == "cpu"
    assert config.batch_size == 8


def test_legacy_auto_device_setting_does_not_override_cpu_default(monkeypatch):
    db = _Db(
        settings={"ai_device_mode": "auto"},
        profile={"device": "cuda", "batch_size": 8},
    )

    config = _resolve(monkeypatch, db, detected_device="cuda")

    assert config.device == "cpu"


def test_device_mode_auto_uses_profile_device(monkeypatch):
    db = _Db(
        settings={"ai_inference_device_mode": "auto"},
        profile={"device": "cuda", "batch_size": 8},
    )

    config = _resolve(monkeypatch, db, detected_device="cpu")

    assert config.device == "cuda"
    assert config.batch_size == 8


def test_device_mode_cpu_overrides_profile_device(monkeypatch):
    db = _Db(
        settings={"ai_inference_device_mode": "cpu"},
        profile={"device": "cuda", "batch_size": 8},
    )

    config = _resolve(monkeypatch, db, detected_device="cuda")

    assert config.device == "cpu"


def test_device_mode_cpu_survives_auto_tune(monkeypatch):
    db = _Db(
        settings={"ai_inference_device_mode": "cpu"},
        profile={"device": "cuda", "batch_size": 8, "io_speed": 100.0},
        auto_tune=True,
    )

    config = _resolve(monkeypatch, db, detected_device="cuda")

    assert config.device == "cpu"


def test_device_mode_gpu_uses_detected_gpu(monkeypatch):
    db = _Db(settings={"ai_inference_device_mode": "gpu"}, profile={"device": "cpu"})

    config = _resolve(monkeypatch, db, detected_device="mps")

    assert config.device == "mps"


def test_device_mode_gpu_falls_back_to_cpu(monkeypatch):
    db = _Db(settings={"ai_inference_device_mode": "gpu"}, profile={"device": "cpu"})

    config = _resolve(monkeypatch, db, detected_device="cpu")

    assert config.device == "cpu"
