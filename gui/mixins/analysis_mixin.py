from gui.mixins.detection_layer_mixin import DetectionLayerMixin
from gui.mixins.analysis_toolbar_mixin import AnalysisToolbarMixin
from gui.mixins.analysis_runner_mixin import AnalysisRunnerMixin


class AnalysisMixin(AnalysisToolbarMixin, DetectionLayerMixin, AnalysisRunnerMixin):
    """AI 分析功能组合器，聚合工具栏、渲染与分析执行三个子模块。

    主窗口只需继承此类，无需感知内部子模块的划分。

    MRO 解析顺序：AIToolbarMixin → AIRenderMixin → AIWorkerMixin
    - AIToolbarMixin : 工具栏构建、模型选择与自动调优
    - AIRenderMixin  : AI 预测框绘制、LOD 控制与图层可见性
    - AIWorkerMixin  : Worker 线程启动、ROI 分析、取消与错误处理
    """
