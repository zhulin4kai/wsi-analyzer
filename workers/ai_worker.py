from PySide6.QtCore import QThread, Signal
from core import WSIAnalyzer

class AIAnalysisWorker(QThread):
    """驱动真实 YOLO 引擎的后台线程"""
    progress_updated = Signal(int)
    status_updated = Signal(str)  # 用于向状态栏汇报文字状态
    analysis_finished = Signal(list)
    error_occurred = Signal(str)

    def __init__(self, svs_path, model_path, parent=None):
        super().__init__(parent)
        self.svs_path = svs_path
        self.model_path = model_path

    def run(self):
        try:
            self.status_updated.emit("正在初始化 AI 模型与计算设备 (耗时较长，请稍候)...")

            # 1. 实例化真实的分析器
            # (在此处实例化，意味着模型加载在后台线程发生，完全不会卡死主界面)
            analyzer = WSIAnalyzer(
                svs_path=self.svs_path,
                model_path=self.model_path,
                patch_size=512,
                stride=400,
                batch_size=16,  # 如果你的 GPU 显存 >= 8G，建议可以改成 32 或 64
                nms_iou_thresh=0.25
            )

            # 2. 触发核心管线，并注入 Lambda 回调函数进行 UI 信号中转
            results = analyzer.process(
                output_json="current_wsi_analysis.json",
                progress_callback=lambda p: self.progress_updated.emit(p),
                status_callback=lambda s: self.status_updated.emit(s)
            )

            if results is None:
                self.error_occurred.emit("未提取到有效组织区域，分析终止。")
            else:
                self.analysis_finished.emit(results)

        except RuntimeError as re:
            if "CUDA out of memory" in str(re):
                self.error_occurred.emit("显存不足 (CUDA OOM)！请在代码中调小 batch_size。")
            else:
                self.error_occurred.emit(f"运行时错误: {str(re)}")
        except Exception as e:
            self.error_occurred.emit(f"AI 引擎异常: {str(e)}")
        finally:
            if analyzer is not None:
                analyzer.close()
