import abc
import os
from typing import Any, Dict, List, Tuple

import numpy as np
import torch
import torchvision.transforms as T
from PIL import Image

from utils import logger

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None


class BaseModelAdapter(abc.ABC):
    """
    视觉模型适配器基类 (Base Model Adapter)
    用于解耦底层 AI 引擎与具体的深度学习框架 (YOLO, ResNet, ViT 等)。
    """

    def __init__(self, model_path: str):
        self.model_path = model_path
        self.model = self._load_model(model_path)

    @abc.abstractmethod
    def _load_model(self, model_path: str) -> Any:
        """加载模型权重并返回模型对象"""
        pass

    @abc.abstractmethod
    def predict(
        self, batch_imgs: List[Image.Image], device: str, conf_thresh: float
    ) -> List[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
        """
        执行批量推理。

        :param batch_imgs: PIL Image 列表
        :param device: 推理设备 ("cuda", "mps", "cpu")
        :param conf_thresh: 置信度阈值
        :return: 返回一个列表，列表的每个元素对应一张输入图片的预测结果，
                 结果格式为 Tuple: (boxes, scores, classes)
                 - boxes: np.ndarray shape (N, 4) [x1, y1, x2, y2]
                 - scores: np.ndarray shape (N,)
                 - classes: np.ndarray shape (N,)
        """
        pass

    @abc.abstractmethod
    def get_default_patch_size(self) -> int:
        """尝试从模型中提取默认的输入尺寸 (Patch Size)，如果无法提取则返回默认值"""
        pass


class YOLOAdapter(BaseModelAdapter):
    """
    YOLO 系列模型适配器 (YOLOv8)
    """

    def _load_model(self, model_path: str) -> Any:
        if YOLO is None:
            raise ImportError("未安装 ultralytics 库，无法加载 YOLO 模型。")
        return YOLO(model_path)

    def predict(
        self, batch_imgs: List[Image.Image], device: str, conf_thresh: float
    ) -> List[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
        # YOLOv8 原生支持 PIL Image 列表输入
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
            # 尝试从 YOLO 权重中提取训练时的 imgsz
            imgsz = self.model.model.args.get("imgsz")
            if isinstance(imgsz, int):
                return imgsz
            elif isinstance(imgsz, list) and len(imgsz) > 0:
                return imgsz[0]
        except Exception as e:
            logger.warning(f"无法从 YOLO 模型提取 Patch Size: {e}")
        return 512


class ClassificationAdapter(BaseModelAdapter):
    """
    通用图像分类模型适配器 (如 ResNet, ViT 等)
    由于分类模型通常是对整个 Patch 输出一个类别，而不是输出 Bounding Box，
    适配器会将其包装成一个覆盖整个 Patch 的 Box 供下游 NMS 和渲染使用。
    """

    def __init__(self, model_path: str, patch_size: int = 224):
        self.patch_size = patch_size
        super().__init__(model_path)

        self.transform = T.Compose(
            [
                T.Resize((self.patch_size, self.patch_size)),
                T.ToTensor(),
                T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
            ]
        )

    def _load_model(self, model_path: str) -> Any:
        # 这里仅作通用 PyTorch 模型的加载示例
        try:
            model = torch.load(model_path, map_location="cpu")
            if isinstance(model, dict) and "state_dict" in model:
                # 如果只有 state_dict，通常需要用户提供模型结构代码
                raise ValueError(
                    "当前文件仅包含权重字典，缺少模型架构(Architecture)无法直接实例化 ResNet/ViT。"
                )
            model.eval()
            return model
        except Exception as e:
            logger.error(f"传统分类模型加载失败: {e}")
            raise

    def predict(
        self, batch_imgs: List[Image.Image], device: str, conf_thresh: float
    ) -> List[Tuple[np.ndarray, np.ndarray, np.ndarray]]:

        self.model.to(device)
        batch_results = []

        # 数据预处理
        tensor_imgs = torch.stack([self.transform(img) for img in batch_imgs]).to(
            device
        )

        with torch.no_grad():
            outputs = self.model(tensor_imgs)
            # 假设输出为 logits，计算 softmax 概率
            probs = torch.nn.functional.softmax(outputs, dim=1)
            max_probs, predicted_classes = torch.max(probs, dim=1)

            max_probs = max_probs.cpu().numpy()
            predicted_classes = predicted_classes.cpu().numpy()

        for i, img in enumerate(batch_imgs):
            score = max_probs[i]
            cls_id = predicted_classes[i]

            # 仅当置信度超过阈值时才输出，否则视为空
            if score >= conf_thresh:
                # 分类模型将整个图像块作为一个目标
                box = np.array([[0, 0, img.width, img.height]])
                score_arr = np.array([score])
                cls_arr = np.array([cls_id])
            else:
                box = np.array([])
                score_arr = np.array([])
                cls_arr = np.array([])

            batch_results.append((box, score_arr, cls_arr))

        return batch_results

    def get_default_patch_size(self) -> int:
        # 传统分类模型难以直接从权重推断尺寸，返回典型的 224
        return self.patch_size


class ModelAdapterFactory:
    """
    模型适配器工厂
    根据用户选择的模型类型或文件特征，实例化对应的模型适配器。
    """

    @staticmethod
    def create_adapter(
        model_path: str, model_type: str = "YOLO", patch_size: int = 512
    ) -> BaseModelAdapter:
        model_type = model_type.upper()

        if model_type == "YOLO":
            return YOLOAdapter(model_path)
        elif model_type in ["RESNET", "VIT", "CLASSIFIER"]:
            return ClassificationAdapter(model_path, patch_size=patch_size)
        else:
            # 尝试通过启发式规则自动猜测
            if "yolo" in os.path.basename(model_path).lower():
                return YOLOAdapter(model_path)
            else:
                raise ValueError(f"不支持的模型类型或无法识别架构: {model_type}")
