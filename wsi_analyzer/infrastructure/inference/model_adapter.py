import abc
import os
from typing import Any, List, Tuple

import numpy as np
from PIL import Image

from wsi_analyzer.infrastructure.logging.logger import logger

try:
    from ultralytics import YOLO as _YOLO
    _ULTRALYTICS_AVAILABLE = True
except ImportError:
    _YOLO = None
    _ULTRALYTICS_AVAILABLE = False


class BaseModelAdapter(abc.ABC):
    def __init__(self, model_path: str):
        self.model_path = model_path
        self.model = self._load_model(model_path)

    @abc.abstractmethod
    def _load_model(self, model_path: str) -> Any:
        pass

    @abc.abstractmethod
    def predict(
        self, batch_imgs: List[Image.Image], device: str, conf_thresh: float
    ) -> List[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
        pass

    @abc.abstractmethod
    def get_default_patch_size(self) -> int:
        pass
