import abc
import os
from typing import Any, Dict, List, Tuple

import numpy as np
import onnxruntime as ort
from PIL import Image
from ultralytics import YOLO

from utils import logger


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


class ONNXObjectDetectionAdapter(BaseModelAdapter):
    """
    通用 ONNX 目标检测模型适配器
    用于支持加载独立于框架的 ONNX 格式模型。
    """

    def _load_model(self, model_path: str) -> Any:
        if ort is None:
            raise ImportError(
                "未安装 onnxruntime 库，无法加载 ONNX 模型。请执行 `pip install onnxruntime` 或 `onnxruntime-gpu`。"
            )

        # 自动选择硬件执行提供者
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        try:
            session = ort.InferenceSession(model_path, providers=providers)
            logger.info(
                f"成功加载 ONNX 模型，使用执行引擎: {session.get_providers()[0]}"
            )
            return session
        except Exception as e:
            logger.error(f"ONNX 模型加载失败: {e}")
            raise

    def predict(
        self, batch_imgs: List[Image.Image], device: str, conf_thresh: float
    ) -> List[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
        # 获取输入层参数
        input_name = self.model.get_inputs()[0].name
        input_shape = self.model.get_inputs()[0].shape

        # 解析 ONNX 所需尺寸 (一般为 [batch, C, H, W])
        target_h = (
            input_shape[2] if isinstance(input_shape[2], int) else batch_imgs[0].height
        )
        target_w = (
            input_shape[3] if isinstance(input_shape[3], int) else batch_imgs[0].width
        )

        # 1. 预处理 (基于通用目标检测归一化，取消分类模型专用的 ImageNet Normalize)
        batch_tensor = []
        for img in batch_imgs:
            # 目标检测 ONNX 普遍需要 RGB float32 / 255.0
            img_resized = img.resize((target_w, target_h))
            img_arr = np.array(img_resized, dtype=np.float32) / 255.0
            img_arr = np.transpose(img_arr, (2, 0, 1))  # HWC -> CHW
            batch_tensor.append(img_arr)

        input_data = np.stack(batch_tensor)

        # 2. 推理
        outputs = self.model.run(None, {input_name: input_data})

        # 3. 后处理提示与对接
        # 接口预留：由于不同架构 (YOLO/Faster R-CNN) 导出的 ONNX 张量结构不同，
        # 建议在导出 ONNX 时将 NMS 和 Box 还原节点打包进计算图中。
        # 此处返回空以适配各种 ONNX 格式，实际使用时需在此补充 NumPy 维度的切片还原。
        logger.debug(f"ONNX 推理完成，原始输出维度: {[o.shape for o in outputs]}")

        batch_results = []
        for _ in range(len(batch_imgs)):
            batch_results.append((np.array([]), np.array([]), np.array([])))

        return batch_results

    def get_default_patch_size(self) -> int:
        try:
            # 提取 ONNX 静态计算图指定的 H 和 W
            input_shape = self.model.get_inputs()[0].shape
            if len(input_shape) >= 4 and isinstance(input_shape[2], int):
                return input_shape[2]
        except Exception as e:
            logger.warning(f"无法从 ONNX 模型提取计算图尺寸: {e}")
        return 512


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

        # 优先通过文件后缀判断
        if model_path.lower().endswith(".onnx"):
            return ONNXObjectDetectionAdapter(model_path)
        elif model_path.lower().endswith(".pt") or model_type == "YOLO":
            return YOLOAdapter(model_path)
        else:
            if "yolo" in os.path.basename(model_path).lower():
                return YOLOAdapter(model_path)
            else:
                raise ValueError(
                    f"不支持的模型格式 ({model_type})。当前目标检测支持 .onnx 或包含模型结构的 .pt 文件。"
                )
