from PySide6.QtCore import QThread, Signal

import config
from core import WSIAnalyzer
from utils.db_manager import DatabaseManager


class AIAnalysisWorker(QThread):
    """驱动真实 YOLO 引擎的后台线程"""

    progress_updated = Signal(int)
    status_updated = Signal(str)  # 用于向状态栏汇报文字状态
    analysis_finished = Signal(dict)
    error_occurred = Signal(str)

    def __init__(self, svs_path, model_path, resume_data=None, parent=None):
        super().__init__(parent)
        self.svs_path = svs_path
        self.model_path = model_path
        self.resume_data = resume_data
        self.analyzer = None

    def cancel(self):
        if self.analyzer:
            self.analyzer.cancel()

    def run(self):
        try:
            self.status_updated.emit(
                "正在初始化 AI 模型与计算设备 (耗时较长，请稍候)..."
            )

            # 1. 实例化真实的分析器
            # (在此处实例化，意味着模型加载在后台线程发生，完全不会卡死主界面)
            db = DatabaseManager()
            patch_size = db.get_setting("ai_patch_size", config.AI_PATCH_SIZE)
            stride = db.get_setting("ai_stride", config.AI_STRIDE)
            nms_iou_thresh = db.get_setting(
                "ai_nms_iou_thresh", config.AI_NMS_IOU_THRESH
            )
            conf_thresh = db.get_setting("ai_conf_thresh", config.AI_CONF_THRESH)

            if db.get_auto_tune_enabled():
                import os

                from utils.hardware_profiler import HardwareProfiler

                drive_prefix = os.path.splitdrive(os.path.abspath(self.svs_path))[0]
                profile = db.get_system_profile(drive_prefix)
                io_speed = profile.get("io_speed", 50.0) if profile else 50.0
                model_size_mb = os.path.getsize(self.model_path) / (1024 * 1024)

                auto_params = HardwareProfiler.calculate_auto_tune_params(
                    io_speed, patch_size, model_size_mb
                )
                stride = auto_params["stride"]
                conf_thresh = auto_params["conf_thresh"]

            self.analyzer = WSIAnalyzer(
                svs_path=self.svs_path,
                model_path=self.model_path,
                patch_size=patch_size,
                stride=stride,
                nms_iou_thresh=nms_iou_thresh,
                conf_thresh=conf_thresh,
            )

            # 2. 触发核心管线，并注入 Lambda 回调函数进行 UI 信号中转
            results_dict = self.analyzer.process(
                resume_data=self.resume_data,
                progress_callback=lambda p: self.progress_updated.emit(p),
                status_callback=lambda s: self.status_updated.emit(s),
            )

            if results_dict is None or (
                len(results_dict.get("valid_coords", [])) == 0
                and results_dict.get("status") != "completed"
            ):
                self.error_occurred.emit("未提取到有效组织区域，分析终止。")
            else:
                self.analysis_finished.emit(results_dict)

        except RuntimeError as re:
            if "CUDA out of memory" in str(re):
                self.error_occurred.emit(
                    "显存不足 (CUDA OOM)！请在代码中调小 batch_size。"
                )
            else:
                self.error_occurred.emit(f"运行时错误: {str(re)}")
        except Exception as e:
            self.error_occurred.emit(f"AI 引擎异常: {str(e)}")
        finally:
            if self.analyzer is not None:
                self.analyzer.close()
