from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelMetadata:
    """Training-time parameters for an AI model.

    Loaded from a .model.yaml / .model.json sidecar file placed
    alongside the model checkpoint (e.g. best.pt -> best.model.yaml).

    Fields:
        model_name:       Human-readable name.
        backend:          Inference backend (e.g. 'ultralytics_yolo').
        task:             Task type ('detect', 'segment', ...).
        model_input_size: Side length (px) fed to the model at training time.
        target_mpp:       Microns per pixel the model was trained at.
        coordinate_system: Frame of reference for coordinates (default 'level0').
        trained_level:    OpenSlide level used during training.
        classes:          Class ID -> label mapping or list of class names.
        dataset_name:     Optional dataset identifier.
        source_mpp:       WSI native MPP of the training data (may differ from target_mpp).
    """

    model_name: str
    backend: str
    task: str
    model_input_size: int
    target_mpp: float
    coordinate_system: str = "level0"
    trained_level: int = 0
    classes: dict[int, str] = field(default_factory=dict)
    dataset_name: str | None = None
    source_mpp: float | None = None

    def __post_init__(self):
        if self.model_input_size <= 0:
            raise ValueError("model_input_size must be > 0")
        if self.target_mpp <= 0:
            raise ValueError("target_mpp must be > 0")

    def to_dict(self) -> dict:
        d: dict = {
            "model_name": self.model_name,
            "backend": self.backend,
            "task": self.task,
            "model_input_size": self.model_input_size,
            "target_mpp": self.target_mpp,
            "coordinate_system": self.coordinate_system,
            "trained_level": self.trained_level,
            "classes": self.classes,
        }
        if self.dataset_name:
            d["dataset_name"] = self.dataset_name
        if self.source_mpp:
            d["source_mpp"] = self.source_mpp
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "ModelMetadata":
        raw_classes = data.get("classes", {})
        if isinstance(raw_classes, list):
            classes = {i: name for i, name in enumerate(raw_classes)}
        elif isinstance(raw_classes, dict):
            classes = {int(k): v for k, v in raw_classes.items()}
        else:
            classes = {}

        model_input_size = _resolve_int(data, ["model_input_size", "training_patch.model_input_size"])
        target_mpp = _resolve_float(data, ["target_mpp", "training_patch.source_mpp"])

        if model_input_size is None:
            raise ValueError("model_input_size is required in metadata")
        if target_mpp is None:
            raise ValueError("target_mpp is required in metadata")

        dataset = data.get("dataset", {}) or {}
        return cls(
            model_name=data.get("model_name", "unknown"),
            backend=data.get("backend", "unknown"),
            task=data.get("task", "detect"),
            model_input_size=model_input_size,
            target_mpp=target_mpp,
            coordinate_system=data.get("coordinate_system", "level0"),
            trained_level=data.get("trained_level", 0),
            classes=classes,
            dataset_name=dataset.get("name") or data.get("dataset_name"),
            source_mpp=_resolve_float(data, ["source_mpp", "training_patch.source_mpp"]),
        )


def _traverse(data: dict, key: str):
    """Walk dotted key path through nested dicts, return leaf value or None."""
    parts = key.split(".")
    val = data
    for p in parts:
        if isinstance(val, dict):
            val = val.get(p)
        else:
            return None
    return val


def _resolve_int(data: dict, keys: list[str]) -> int | None:
    for key in keys:
        val = _traverse(data, key)
        if val is None:
            continue
        # Reject bool (isinstance(True, int) but type(True) is bool)
        if type(val) is bool:
            return None
        if type(val) in (int, float):
            return int(val)
        if isinstance(val, str) and val.lstrip("-").isdigit():
            return int(val)
    return None


def _resolve_float(data: dict, keys: list[str]) -> float | None:
    for key in keys:
        val = _traverse(data, key)
        if val is None:
            continue
        if type(val) is bool:
            return None
        if type(val) in (int, float):
            return float(val)
        if isinstance(val, str):
            try:
                return float(val)
            except ValueError:
                pass
    return None
