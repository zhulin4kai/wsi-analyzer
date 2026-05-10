# WSIAnalyzer 架构概览

本文档面向接手项目的开发者，提供项目整体结构的快速导航。
阅读顺序建议：先读本文档了解"谁在哪"，再读 `inference-pipeline.md` 理解核心业务链路。

---

## 1. 分层依赖方向

```
app/            --> application/, infrastructure/
application/    --> domain/, infrastructure/
infrastructure/ --> domain/
domain/         --> (无外部依赖 -- 纯 numpy/cv2/dataclasses)
workers/        --> app/ (for DI), application/
ui/             --> app/ (for DI), workers/
```

规则：内层不知道外层的存在。`application/` 不得 import `app/` 或 `ui/`。`domain/` 不得 import 任何项目内模块。

---

## 2. 各层角色

```
wsi_analyzer/
├── app/                 入口 + 依赖注入
│   ├── main.py                  多进程入口 (Tkinter splash → Qt)
│   ├── bootstrap.py             QApplication 生命周期, app.exec() 后 shutdown
│   ├── dependency_container.py  全局 DI 单例 (database / image_server / factory)
│   └── launcher/                启动画面 (Tkinter, 与 Qt 进程分离)
│
├── domain/              纯算法 + 数据类 (0 外部依赖)
│   ├── slide/                   坐标 (Level0Box/Point/PatchCoordinate), SlideReadPort 抽象
│   ├── detection/               检测实体 (Detection), NMS, 结果融合, 热力图计算
│   └── analysis/                分析结果 (AnalysisResult), PatchPlanner, ROIPlanner
│
├── application/         业务编排 (调用 domain + infrastructure, 不涉及 Qt)
│   └── analysis/                全片分析服务, 工厂, 配置解析, 坐标服务, auto-tune
│
├── infrastructure/      外部系统适配 (OpenSlide, YOLO, SQLite, pynvml)
│   ├── imaging/                 ImageServer, OpenSlideEngine, SlidePool, PatchReader
│   ├── inference/               BatchInferencer, ModelAdapter, YOLOAdapter, ModelInspector
│   ├── persistence/             DatabaseManager (含 3 门面: SettingsStore/AnalysisCache/ProfileStore)
│   ├── hardware/                HardwareProfiler, IO 测速
│   └── logging/                 统一日志系统
│
├── ui/                  PySide6 界面
│   ├── main_window.py           主窗口 (纯装配, 不包含业务逻辑)
│   ├── controllers/             各 Controller (Analysis/Slide/Result/Model/Heatmap/HUD/Minimap)
│   ├── layers/                  图层 (Detection/Annotation/Heatmap + LayerManager)
│   ├── widgets/                 视图组件 (WSIView, MinMapView, InfoBar, ScaleBar 等)
│   ├── rendering/               瓦片渲染 (TileGrid, TileRenderController)
│   ├── dialogs/                 设置对话框
│   └── main_menu.py             菜单栏建造器
│
├── workers/             QThread 适配器 (仅信号桥接, 无配置决策)
│   ├── ai_worker.py             45 行, 调 factory.create() + service.run()
│   ├── render_worker.py         瓦片渲染
│   ├── gallery_worker.py        病灶缩略图截取
│   ├── profile_worker.py        硬件画像探测
│   └── preload_task.py          引擎预热
│
├── config/              运行时配置常量 (config.py)
└── shared/              跨层工具 (WSI 文件后缀检测, 拖拽 MIME 解析)
```

---

## 3. DependencyContainer 设计

文件: `wsi_analyzer/app/dependency_container.py`

```python
class DependencyContainer:
    def __init__(self):
        self.database = DatabaseManager()          # SQLite 统一入口
        self.image_server = ImageServer.instance() # OpenSlide 引擎池单例
        self.analysis_service_factory = AnalysisServiceFactory(
            database=self.database,
            image_server=self.image_server,
        )

container = DependencyContainer()  # 模块级单例
```

全局唯一入口: `from wsi_analyzer.app.dependency_container import container`。

`container.analysis_service_factory.create(svs_path, model_path)` 内部调用 `AnalysisConfigResolver.resolve()` 完成：
- 数据库配置读取 (patch_size, stride, conf_thresh ...)
- 硬件探测 (VRAM, I/O 速度)
- auto-tune 参数计算
- 边界值 clamping

---

## 4. AnalysisResult 数据流

`AnalysisResult` 是贯穿全链路的领域对象 (`domain/analysis/result.py`)，
含 `detections: List[Detection]`, `status`, `total_patches`, `raw_boxes` 等字段。

```
FullSlideAnalysisService.run()
    │ 返回 AnalysisResult
    ▼
AIAnalysisWorker.run()
    │ 通过 Signal(object) 发射到主线程
    ▼
AnalysisResultController
    ├── _draw_ai_boxes(result)          → DetectionLayer.render()
    ├── _commit_results(result)          → SQLite (调用 result.to_dict())
    └── heatmap_controller.update_heatmap_layer()  → HeatmapLayer.render()
```

转换规则：
- 内部传递永远是 `AnalysisResult` 对象
- `to_dict()` 仅在两个边界调用：(1) 存入 SQLite 时；(2) 传递给 `fuse_results()` 进行 NMS 合并时（后者需要 `[{"bbox": [...], "confidence": ...}, ...]` 格式）
- 缓存回放通过 `AnalysisResult.from_cache(cache_data)` 重新构造对象

---

## 5. 关键文件快速索引

| 文件 | 用途 |
|---|---|
| `main.py` | 多进程入口 (Tkinter splash -- Qt main process) |
| `app/bootstrap.py` | Qt event loop 生命周期, `app.exec()` 后调用 `image_server.shutdown()` |
| `app/dependency_container.py` | 全局 DI 容器 (7 行 module-level singleton) |
| `domain/analysis/result.py` | `AnalysisResult` -- 全链路传递的结果类型 |
| `domain/slide/coordinates.py` | `Level0Box`, `Level0Point`, `PatchCoordinate` |
| `application/analysis/analysis_service.py` | `FullSlideAnalysisService.run()` -- 推理主编排 |
| `application/analysis/analysis_service_factory.py` | `AnalysisServiceFactory.create()` -- 组装所有依赖 |
| `workers/ai_worker.py` | 45 行 Qt 信号桥接, 不包含配置逻辑 |

---

## 6. 开发约定

**公开导出**: 每个非空 `__init__.py` 都有 `__all__`。外部 import 应从包级别导入 (`from wsi_analyzer.domain.detection import Detection`)，不要直接引用内部模块文件。

**Protected 成员**: 以 `_` 开头的方法不应跨类边界调用。对外暴露的方法必须去除前缀 `_`。

**Import 方向检查**: `application/` 中不应出现 `from wsi_analyzer.app`；`domain/` 中不应出现任何项目内部 import (除标准库)。

**测试**: 38 个 domain 单元测试 (`tests/domain/`), 纯 Mock 依赖, 运行命令:
```
$env:PYTHONPATH = "."; python -m pytest tests/domain/ -q
```
