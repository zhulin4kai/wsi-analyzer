from gui.mixins.ai_render_mixin import AIRenderMixin
from gui.mixins.ai_toolbar_mixin import AIToolbarMixin
from gui.mixins.ai_worker_mixin import AIWorkerMixin


class AIAnalysisMixin(AIToolbarMixin, AIRenderMixin, AIWorkerMixin):
    """AI 分析功能组合器，聚合工具栏、渲染与分析执行三个子模块。

    主窗口只需继承此类，无需感知内部子模块的划分。

    MRO 解析顺序：AIToolbarMixin → AIRenderMixin → AIWorkerMixin
    - AIToolbarMixin : 工具栏构建、模型选择与自动调优
    - AIRenderMixin  : AI 预测框绘制、LOD 控制与图层可见性
    - AIWorkerMixin  : Worker 线程启动、ROI 分析、取消与错误处理
    """
