import os

from wsi_analyzer.infrastructure.inference.model_adapter import (
    BaseModelAdapter,
    _ULTRALYTICS_AVAILABLE,
    _YOLO,
)
from wsi_analyzer.infrastructure.inference.yolo_adapter import YOLOAdapter


class ModelAdapterFactory:
    @staticmethod
    def create_adapter(model_path: str) -> BaseModelAdapter:
        ext = os.path.splitext(model_path)[1].lower()
        if ext == ".pt":
            if not _ULTRALYTICS_AVAILABLE or _YOLO is None:
                raise ImportError(
                    f"加载 '{os.path.basename(model_path)}' 需要 ultralytics，当前环境未安装。"
                )
            return YOLOAdapter(model_path)
        raise ValueError(
            f"不支持的模型格式（后缀: '{ext}'）。当前仅支持 .pt 格式。"
        )
