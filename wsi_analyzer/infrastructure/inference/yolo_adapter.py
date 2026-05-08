import os
from typing import Any, List, Tuple

import numpy as np
from PIL import Image

from wsi_analyzer.infrastructure.inference.model_adapter import (
    BaseModelAdapter,
    _ULTRALYTICS_AVAILABLE,
    _YOLO,
)
from wsi_analyzer.infrastructure.logging.logger import logger


class YOLOAdapter(BaseModelAdapter):
    def _load_model(self, model_path: str) -> Any:
        if not _ULTRALYTICS_AVAILABLE or _YOLO is None:
            raise ImportError(
                f"加载 '{os.path.basename(model_path)}' 需要 ultralytics，当前环境未安装。"
            )
        return _YOLO(model_path)

    def predict(
        self, batch_imgs: List[Image.Image], device: str, conf_thresh: float
    ) -> List[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
        results = self.model(batch_imgs, verbose=False, device=device, conf=conf_thresh)
        batch_results = []
        for result in results:
            if len(result.boxes) == 0:
                batch_results.append((np.array([]), np.array([]), np.array([])))
                continue
            boxes = result.boxes.xyxy.cpu().numpy()
            scores = result.boxes.conf.cpu().numpy()
            classes = result.boxes.cls.cpu().numpy()
            batch_results.append((boxes, scores, classes))
        return batch_results

    def get_default_patch_size(self) -> int:
        try:
            imgsz = self.model.model.args.get("imgsz")
            if isinstance(imgsz, int):
                return imgsz
            if isinstance(imgsz, (list, tuple)) and len(imgsz) > 0:
                return int(imgsz[0])
        except Exception as e:
            logger.warning(f"无法从 YOLO 模型提取 Patch Size: {e}")
        return 512
