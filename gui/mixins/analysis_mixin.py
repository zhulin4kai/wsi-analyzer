from gui.mixins.analysis_runner_mixin import AnalysisRunnerMixin
from gui.mixins.analysis_toolbar_mixin import AnalysisToolbarMixin
from gui.mixins.detection_layer_mixin import DetectionLayerMixin
from gui.mixins.heatmap_mixin import HeatmapMixin


class AnalysisMixin(
    AnalysisRunnerMixin, AnalysisToolbarMixin, DetectionLayerMixin, HeatmapMixin
):
    """聚合所有 AI 分析相关 Mixin 的组合类。

    继承关系：
        AnalysisRunnerMixin  —— AIAnalysisWorker 线程启动、进度对话框、取消/错误处理
        AnalysisToolbarMixin —— 顶部工具栏构建、模型选择、智能调优
        DetectionLayerMixin  —— 预测框绘制、结果持久化、图层可见性控制
        HeatmapMixin         —— 热力图生成、LOD 动态渲染、小地图同步

    供 MainWindow 单点继承，避免主窗口直接依赖各子 Mixin 的内部实现细节。
    """

    pass
