import json
import os
from pathlib import Path

from wsi_analyzer.domain.model import ModelMetadata

try:
    import yaml as _yaml
    _HAS_YAML = True
except ImportError:
    _yaml = None
    _HAS_YAML = False


_SIDECAR_EXTENSIONS = [".model.yaml", ".model.yml", ".model.json"]


class ModelMetadataLoader:
    """Load ModelMetadata from a sidecar file or YOLO checkpoint."""

    def load(self, model_path: str) -> ModelMetadata | None:
        """Try sidecar files, then checkpoint metadata, then return None."""
        metadata = self._load_from_sidecar(model_path)
        if metadata is not None:
            return metadata
        metadata = self._load_from_checkpoint(model_path)
        if metadata is not None:
            return metadata
        return None

    # ── sidecar loading ─────────────────────────────────────────────

    def _load_from_sidecar(self, model_path: str) -> ModelMetadata | None:
        base = os.path.splitext(model_path)[0]
        for ext in _SIDECAR_EXTENSIONS:
            sidecar = base + ext
            if os.path.isfile(sidecar):
                return self._parse_file(sidecar)
        return None

    def _parse_file(self, path: str) -> ModelMetadata:
        if path.endswith(".json"):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        elif path.endswith((".yaml", ".yml")):
            if not _HAS_YAML:
                raise ImportError(
                    f"YAML sidecar detected ({path}) but PyYAML is not installed."
                )
            with open(path, "r", encoding="utf-8") as f:
                data = _yaml.safe_load(f)
        else:
            return None
        if not isinstance(data, dict):
            raise ValueError(f"Sidecar {path} must contain a YAML/JSON mapping, got {type(data)}")
        return ModelMetadata.from_dict(data)

    # ── checkpoint fallback ──────────────────────────────────────────

    def _load_from_checkpoint(self, model_path: str) -> ModelMetadata | None:
        if not model_path.endswith((".pt", ".pth")):
            return None
        try:
            import torch
            checkpoint = torch.load(model_path, map_location="cpu", weights_only=False)
        except ImportError:
            return None
        except Exception:
            return None

        if not isinstance(checkpoint, dict):
            return None

        # -- try 'model_metadata' key first, then 'wsi_metadata' --
        for key in ("model_metadata", "wsi_metadata"):
            raw = checkpoint.get(key)
            if isinstance(raw, dict):
                try:
                    return ModelMetadata.from_dict(raw)
                except (ValueError, TypeError):
                    pass
        return None
