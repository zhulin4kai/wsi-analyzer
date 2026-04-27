from gui.mixins.analysis_runner_mixin import AnalysisRunnerMixin
from gui.mixins.analysis_toolbar_mixin import AnalysisToolbarMixin
from gui.mixins.detection_layer_mixin import DetectionLayerMixin
from gui.mixins.heatmap_mixin import HeatmapMixin


class AnalysisMixin(
    AnalysisToolbarMixin, DetectionLayerMixin, AnalysisRunnerMixin, HeatmapMixin
):
    """AI 分析功能组合器，聚合工具栏、渲染、分析执行与热力图四个子模块。

    主窗口只需继承此类，无需感知内部子模块的划分。

    MRO 解析顺序：AnalysisToolbarMixin → DetectionLayerMixin → AnalysisRunnerMixin → HeatmapMixin
    - AnalysisToolbarMixin : 工具栏构建、模型选择与自动调优
    - DetectionLayerMixin  : AI 预测框绘制、LOD 控制与图层可见性
    - AnalysisRunnerMixin  : Worker 线程启动、ROI 分析、取消与错误处理
    - HeatmapMixin         : 检测结果空间密度热力图计算、渲染与生命周期管理
    """
