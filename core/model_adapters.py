import abc
import os
from typing import Any, List, Tuple

import numpy as np
import onnxruntime as ort
from PIL import Image

from utils import logger

try:
    from ultralytics import YOLO as _YOLO  # type: ignore[import-untyped]

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
                f"当前环境未安装。\n"
                f"可执行 export_onnx.py 将 .pt 转换为 .onnx 格式后使用。"
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


class ONNXObjectDetectionAdapter(BaseModelAdapter):
    """
    通用 ONNX 目标检测模型适配器。

    适配 ultralytics YOLO 系列检测模型以 nms=False 导出的 ONNX 格式：
    - 输入:  float32[batch, 3, H, W]，归一化至 [0, 1]
    - 输出:  float32[batch, 4+num_classes, num_anchors]
             前 4 维为 [cx, cy, w, h]（像素坐标，相对于输入尺寸），
             其余维度为各类别置信度。

    predict() 会自动检测输出张量的排列方式，同时支持
    (B, 4+C, N) 和 (B, N, 4+C) 两种布局，后处理不依赖具体模型版本。
    """

    def _load_model(self, model_path: str) -> ort.InferenceSession:
        available = ort.get_available_providers()
        preferred = []
        if "CUDAExecutionProvider" in available:
            preferred.append("CUDAExecutionProvider")
        if "CoreMLExecutionProvider" in available:
            preferred.append("CoreMLExecutionProvider")
        preferred.append("CPUExecutionProvider")

        try:
            session = ort.InferenceSession(model_path, providers=preferred)
            logger.info(f"ONNX 模型已加载，活跃执行引擎: {session.get_providers()[0]}")
            return session
        except Exception as e:
            logger.error(f"ONNX 模型加载失败: {e}")
            raise

    def predict(
        self, batch_imgs: List[Image.Image], device: str, conf_thresh: float
    ) -> List[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
        """
        执行 ONNX 批量推理并完成后处理。

        :param device: 对 ONNX 适配器无效，推理设备由 _load_model 中的 Provider 决定。
        """
        inp_meta = self.model.get_inputs()[0]
        input_name = inp_meta.name
        input_shape = inp_meta.shape  # [batch, 3, H, W]

        target_h = (
            input_shape[2] if isinstance(input_shape[2], int) else batch_imgs[0].height
        )
        target_w = (
            input_shape[3] if isinstance(input_shape[3], int) else batch_imgs[0].width
        )

        # 预处理：resize → 归一化 [0,1] → HWC to CHW
        # 提前记录每张图的原始尺寸，用于后续将检测框坐标还原到 patch 空间
        orig_sizes = [(img.width, img.height) for img in batch_imgs]
        _resample = getattr(getattr(Image, "Resampling", Image), "BILINEAR", 2)
        batch_tensor = []
        for img in batch_imgs:
            img_resized = img.resize((target_w, target_h), _resample)
            arr = np.array(img_resized, dtype=np.float32) / 255.0
            arr = np.transpose(arr, (2, 0, 1))
            batch_tensor.append(arr)
        input_data = np.stack(batch_tensor)  # (B, 3, H, W)

        raw_outputs = self.model.run(None, {input_name: input_data})
        raw = raw_outputs[0]

        # 输出布局归一化：
        # 当 shape[1] < shape[2] 时，张量排列为 (B, 4+C, N)，转置为 (B, N, 4+C)；
        # 否则已为 (B, N, 4+C)，无需转置。
        if raw.ndim == 3 and raw.shape[1] < raw.shape[2]:
            raw = np.transpose(raw, (0, 2, 1))

        batch_results = []
        for b in range(len(batch_imgs)):
            preds = raw[b]  # (N, 4+C)

            boxes_cxcywh = preds[:, :4]  # [cx, cy, w, h]，单位：像素
            class_scores = preds[:, 4:]  # 各类别置信度

            scores = class_scores.max(axis=1)
            class_ids = class_scores.argmax(axis=1)

            mask = scores >= conf_thresh
            if not np.any(mask):
                batch_results.append((np.array([]), np.array([]), np.array([])))
                continue

            boxes_f = boxes_cxcywh[mask]
            scores_f = scores[mask]
            class_ids_f = class_ids[mask]

            # cxcywh → xyxy
            cx, cy, w, h = boxes_f[:, 0], boxes_f[:, 1], boxes_f[:, 2], boxes_f[:, 3]
            boxes_xyxy = np.stack(
                [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1
            )

            # 若模型输入尺寸与原始 patch 尺寸不同，须将框坐标从模型输入空间
            # 缩放回原始 patch 像素空间，否则后续拼接全局偏移时坐标会偏移错误
            orig_w, orig_h = orig_sizes[b]
            if target_w != orig_w or target_h != orig_h:
                scale = np.array(
                    [
                        orig_w / target_w,
                        orig_h / target_h,
                        orig_w / target_w,
                        orig_h / target_h,
                    ],
                    dtype=np.float32,
                )
                boxes_xyxy = boxes_xyxy * scale

            batch_results.append((boxes_xyxy, scores_f, class_ids_f))

        return batch_results

    def get_default_patch_size(self) -> int:
        """从 ONNX 输入形状 [batch, C, H, W] 中提取 H 作为 Patch Size。"""
        try:
            shape = self.model.get_inputs()[0].shape
            if len(shape) >= 4 and isinstance(shape[2], int) and shape[2] > 0:
                return shape[2]
        except Exception as e:
            logger.warning(f"无法从 ONNX 模型提取 Patch Size: {e}")
        return 512


class ModelAdapterFactory:
    """
    根据模型文件后缀选择并实例化对应的适配器：
      .onnx → ONNXObjectDetectionAdapter
      .pt   → YOLOAdapter（需要 ultralytics）
    """

    @staticmethod
    def create_adapter(model_path: str, model_type: str = "YOLO") -> BaseModelAdapter:
        model_type = model_type.upper()
        ext = os.path.splitext(model_path)[1].lower()

        if ext == ".onnx":
            return ONNXObjectDetectionAdapter(model_path)

        if ext == ".pt" or model_type == "YOLO":
            if not _ULTRALYTICS_AVAILABLE or _YOLO is None:
                raise ImportError(
                    f"加载 '{os.path.basename(model_path)}' 需要 ultralytics，"
                    f"当前环境未安装。\n"
                    f"可执行 export_onnx.py 将 .pt 转换为 .onnx 格式后使用。"
                )
            return YOLOAdapter(model_path)

        raise ValueError(
            f"不支持的模型格式（后缀: '{ext}'，model_type: '{model_type}'）。"
            f"支持格式：.onnx、.pt。"
        )
