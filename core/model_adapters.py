import abc
import os
from typing import Any, List, Tuple

import numpy as np
from PIL import Image

from utils import logger

try:
    from ultralytics import YOLO as _YOLO

    _ULTRALYTICS_AVAILABLE = True
except ImportError:
    _YOLO = None
    _ULTRALYTICS_AVAILABLE = False


class BaseModelAdapter(abc.ABC):
    """
    视觉模型适配器基类。
    用于解耦 AI 引擎与底层推理框架，所有具体适配器均继承此类。
    """

    def __init__(self, model_path: str):
        self.model_path = model_path
        self.model = self._load_model(model_path)

    @abc.abstractmethod
    def _load_model(self, model_path: str) -> Any:
        """加载模型权重并返回模型对象。"""
        pass

    @abc.abstractmethod
    def predict(
        self, batch_imgs: List[Image.Image], device: str, conf_thresh: float
    ) -> List[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
        """
        执行批量推理。

        :param batch_imgs:  PIL Image 列表
        :param device:      推理设备（"cuda"、"mps"、"cpu"）
        :param conf_thresh: 置信度阈值
        :return: 列表，每个元素对应一张图片的预测结果，格式为
                 Tuple(boxes, scores, classes)：
                 - boxes:   np.ndarray  shape (N, 4)  [x1, y1, x2, y2]  像素坐标
                 - scores:  np.ndarray  shape (N,)
                 - classes: np.ndarray  shape (N,)
        """
        pass

    @abc.abstractmethod
    def get_default_patch_size(self) -> int:
        """从模型元信息中提取输入尺寸；无法提取时返回默认值 512。"""
        pass


class YOLOAdapter(BaseModelAdapter):
    """
    基于 ultralytics 库的 YOLO 系列模型适配器，用于加载 .pt 格式权重。
    需要安装 ultralytics；不可用时抛出 ImportError。
    """

    def _load_model(self, model_path: str) -> Any:
        if not _ULTRALYTICS_AVAILABLE or _YOLO is None:
            raise ImportError(
                f"加载 '{os.path.basename(model_path)}' 需要 ultralytics，"
                f"当前环境未安装。"
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

class ModelAdapterFactory:
    """模型适配器工厂"""

    @staticmethod
    def create_adapter(model_path: str) -> BaseModelAdapter:
        ext = os.path.splitext(model_path)[1].lower()

        if ext == ".pt":
            if not _ULTRALYTICS_AVAILABLE or _YOLO is None:
                raise ImportError(
                    f"加载 '{os.path.basename(model_path)}' 需要 ultralytics，"
                    f"当前环境未安装。"
                )
            return YOLOAdapter(model_path)

        raise ValueError(
            f"不支持的模型格式（后缀: '{ext}'）。"
            f"当前仅支持 .pt 格式。请使用 YOLO 训练导出的 .pt 权重文件。"
        )
