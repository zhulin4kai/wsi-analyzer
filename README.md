# 基于深度学习的微乳头型肺腺癌 WSI 辅助诊断系统
(WSI Auxiliary Diagnosis System for Micropapillary Lung Adenocarcinoma)

## 项目简介
本项目是一款面向数字化病理辅助诊断的桌面端系统软件。针对微乳头型肺腺癌（Micropapillary pattern）的临床诊断需求，系统依托深度学习目标检测模型，可在数字病理全尺寸切片（WSI, 如 `.svs` 等格式）中自动定位并标注微乳头细胞簇。系统原生支持 YOLO 架构 `.pt` 权重，通过全片自动化分析与 ROI 靶向分析协助病理医生提升阅片效率与诊断准确率。

## 核心工程特性

### 1. 分层架构 (Layered Architecture)
- **严格依赖方向**：`app → application/infrastructure → domain`，domain 零外部依赖（纯 numpy/cv2/dataclasses）
- **领域模型驱动**：`InferenceGeometry` 统一尺度契约、`AnalysisResult` 强类型数据流、`ModelMetadata` sidecar 元数据
- **DI 单例容器**：7 行 `DependencyContainer`，全局唯一注入点

### 2. 瓦片级渲染引擎 (Tile-Based Rendering)
- **多线程并发调度**：`PriorityTileScheduler` + `RenderWorker` 基于优先级堆的瓦片化并发渲染
- **双缓存架构**：`TileLRUCache`（视口缓存）+ `TileDataCache`（跨切片像素缓存）
- **Layer 系统**：`DetectionLayer` / `AnnotationLayer` / `HeatmapLayer` 封装渲染，热力图计算下沉 `domain/detection/heatmap.py`

### 3. AI 推理管线 (AI Pipeline)
- **YOLO 模型适配**：`BatchInferencer` → `ModelInspector`，UI 不直接 import ultralytics
- **InferenceGeometry 尺度契约**：统一 `model_input_size`、`target_mpp`、`slide_mpp`、`read_level`、`read_downsample`
- **ROI 靶向分析**：基于用户框选的局部区域，合并全片推理数据；全局 NMS 去重
- **异步推理**：`AIAnalysisWorker`（45 行 QThread）剥离推理与主界面
- **断点续传**：缓存恢复时比对几何一致性，不匹配则拒绝 resume

### 4. 硬件自适应 (Hardware Auto-Tuning)
- **硬件探针**：`HardwareProfiler` 动态检测 CUDA/MPS/CPU、VRAM/RAM、磁盘 I/O
- **启发式参数分配**：`batch_size`、`stride`、`tile_cache_limit`
- **OOM 回退**：CUDA OOM 时自动 batch-size 减半重试
- **MPP 风险警告**：推理启动时检测 slide_mpp 缺失或偏差 >25%

### 5. 评估与可视化 (Evaluation & Visualization)
- **评估模块**：`domain/evaluation/` 实现 Precision / Recall / F1 / AP50（11-point interpolation），支持 polygon→bbox 评估
- **报告导出**：CSV、JSON、GeoJSON (QuPath)，统一"AI辅助检测报告" + 免责声明
- **论文插图导出**：`scripts/export_paper_figures.py` 自动导出 01~07 共 7 类图像

### 6. 数据持久化
- **SQLite + WAL**：基于文件哈希的断点续传、历史诊断结果提取、容量自动淘汰
- **多进程启动器**：`app/launcher/` 子进程加载 Qt/DB/AI，Tkinter 贴图毫秒级展示

## 技术栈
- **UI 与并发**: PySide6, multiprocessing, Tkinter (Launcher)
- **图像处理**: OpenCV, NumPy, Pillow, OpenSlide
- **深度学习**: Ultralytics YOLO, PyTorch
- **数据持久化**: SQLite3 (WAL)

## 核心目录结构
```text
WSIAnalyzer/
├── main.py                                 # 多进程入口（Tkinter 贴图 → Qt 子进程）
├── wsi_analyzer/
│   ├── app/                                # 入口层（bootstrap, DependencyContainer, launcher）
│   ├── application/                        # 编排层（AnalysisService, EvaluationService, AnalysisServiceFactory）
│   ├── domain/                             # 领域层（entities, detection, analysis, evaluation, heatmap, fusion, NMS）
│   ├── infrastructure/                     # 基础设施层（ImageServer, BatchInferencer, ModelInspector, DatabaseManager）
│   ├── ui/                                 # PySide6 GUI（main_window, controllers, layers, widgets, dialogs, rendering）
│   ├── workers/                            # QThread 适配层（AIAnalysisWorker, RenderWorker, GalleryWorker）
│   ├── config/                             # 运行时常量（config.py）
│   └── shared/                             # 跨层工具（wsi_file_utils, drag_drop_mime）
├── scripts/                                # 辅助脚本（evaluate_wsi_batch, export_paper_figures, write_model_metadata）
├── tests/                                  # 测试（domain 38 测试, evaluation 22 测试）
└── docs/                                   # 架构文档（architecture-overview, inference-pipeline, image-server, ui-architecture, evaluation_protocol）
```

## 架构文档
详见 `docs/` 目录：
- [架构总览](docs/architecture-overview.md)
- [推理管线](docs/inference-pipeline.md)
- [ImageServer 设计](docs/image-server.md)
- [UI 架构](docs/ui-architecture.md)
- [WSI 算法管线全链路](docs/wsi_algorithm_pipeline.md)
- [评估协议](docs/evaluation_protocol.md)

## 测试
```bash
# 领域层测试（38 个，~0.2s）
$env:PYTHONPATH = "."; python -m pytest tests/domain/ -q

# 评估模块测试（22 个）
python -m pytest tests/domain/evaluation/ -q

# 编译检查
python -m py_compile <changed_files>
```

---

*注：本项目相关医疗辅助诊断算法及其生成结论仅供科研与测试探讨，不应直接代替执业医师的临床诊断意见。*
