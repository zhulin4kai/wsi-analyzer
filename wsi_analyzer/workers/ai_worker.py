from PySide6.QtCore import QThread, Signal

from wsi_analyzer.application.analysis.analysis_service_factory import AnalysisServiceFactory


class AIAnalysisWorker(QThread):
    progress_updated = Signal(int)
    status_updated = Signal(str)
    analysis_finished = Signal(dict)
    error_occurred = Signal(str)

    def __init__(
        self, svs_path, model_path, resume_data=None, roi_bbox=None, parent=None
    ):
        super().__init__(parent)
        self.svs_path = svs_path
        self.model_path = model_path
        self.resume_data = resume_data
        self.roi_bbox = roi_bbox
        self.analysis_handle = None

    def cancel(self):
        if self.analysis_handle:
            self.analysis_handle.cancel()

    def run(self):
        try:
            self.status_updated.emit("正在初始化 AI 模型与计算设备")

            self.analysis_handle = AnalysisServiceFactory.create(
                svs_path=self.svs_path,
                model_path=self.model_path,
            )

            results_dict = self.analysis_handle.service.run(
                resume_data=self.resume_data,
                progress_callback=lambda p: self.progress_updated.emit(p),
                status_callback=lambda s: self.status_updated.emit(s),
                roi_bbox=self.roi_bbox,
            )

            if results_dict is None:
                self.error_occurred.emit("AI 引擎返回空结果")
            elif results_dict.get("status") == "error":
                self.error_occurred.emit(results_dict.get("message", "分析异常终止，请检查参数配置"))
            else:
                self.analysis_finished.emit(results_dict)

        except RuntimeError as re:
            self.error_occurred.emit(f"运行时错误: {str(re)}")
        except Exception as e:
            self.error_occurred.emit(f"AI 引擎异常: {str(e)}")
        finally:
            if self.analysis_handle is not None:
                self.analysis_handle.close()
