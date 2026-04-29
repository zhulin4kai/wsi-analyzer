# 基于深度学习的微乳头型肺腺癌 WSI 辅助诊断系统
(WSI Auxiliary Diagnosis System for Micropapillary Lung Adenocarcinoma)

## 项目简介
本项目是一款面向数字化病理辅助诊断的桌面端系统软件。针对微乳头型肺腺癌（Micropapillary pattern）的临床诊断需求，系统依托深度学习目标检测模型，可在数字病理全尺寸切片（WSI, 如 `.svs` 等格式）中自动定位并标注微乳头细胞簇。系统原生支持 YOLO 架构 `.pt` 权重，通过全片自动化分析与 ROI 靶向分析协助病理医生提升阅片效率与诊断准确率。

## 核心工程特性

### 1. 瓦片级渲染引擎 (Tile-Based Rendering)
- **多线程并发调度**：`PriorityTileScheduler` + `RenderWorker` 基于优先级堆的瓦片化并发渲染。
- **双缓存架构**：`TileLRUCache`（视口缓存，切换切片清空）+ `TileDataCache`（跨切片像素缓存，跳过磁盘 I/O）。
- **跨层级渲染优化**：动态金字塔层级匹配与 Z-index 提升，防止缩放期间图层交错。

### 2. AI 推理管线 (AI Pipeline)
- **YOLO 模型适配**：`ModelAdapterFactory` → `YOLOAdapter`，支持 `.pt` 权重直接加载。
- **ROI 靶向分析**：基于用户框选的局部区域，自动切换密集滑动步长，合并全片推理数据。
- **异步推理**：`AIAnalysisWorker`（QThread）剥离推理与主界面；全局 NMS 去重重叠框。

### 3. 硬件自适应 (Hardware Auto-Tuning)
- **硬件探针**：`HardwareProfiler` 动态检测 CUDA/MPS/CPU、VRAM/RAM、磁盘 I/O。
- **启发式参数分配**：EMA 算法计算 `batch_size`、`stride`、`tile_cache_limit`。
- **OOM 回退**：CUDA OOM 时自动 batch-size 减半重试。

### 4. 数据持久化与架构
- **SQLite + WAL**：基于文件哈希的断点续传、历史诊断结果提取、容量自动淘汰。
- **ImageServer 单例**：SlidePool（LRU + 引用计数）、TileDataCache、元数据缓存统一入口。
- **多进程启动器**：`AppLauncher` 子进程加载 Qt/DB/AI，Tkinter 贴图毫秒级展示。
- **报告导出**：CSV、JSON、GeoJSON (QuPath)。

## 技术栈
- **UI 与并发**: PySide6, multiprocessing, Tkinter (Launcher)
- **图像处理**: OpenCV, NumPy, Pillow, OpenSlide
- **深度学习**: Ultralytics YOLOv8, PyTorch
- **数据持久化**: SQLite3 (WAL)

## 核心目录结构
```text
WSIAnalyzer/
├── main.py                 # 多进程入口（Tkinter 贴图 → Qt 子进程）
├── config.py               # 全局常量（AI / HUD / 热力图 / 硬件调优）
├── core/                   # 核心逻辑层
│   ├── ai_engine.py        # AI 推理主引擎（掩码、批量推理、NMS）
│   ├── image_server.py     # 进程级单例：SlidePool + TileDataCache + 元数据
│   ├── model_adapters.py   # YOLO .pt 模型适配器
│   ├── roi_manager.py      # ROI 坐标生成与结果融合（模块函数）
│   ├── slide_engine.py     # OpenSlide 底层封装
│   ├── tile_cache.py       # TileLRUCache + TileDataCache
│   └── launcher/           # 多进程启动器（AppLauncher + SplashUI）
├── gui/                    # 用户界面层
│   ├── main_window.py      # 主窗口（Mixin 组合）
│   ├── mixins/             # 功能解耦（分析/文件/工具栏/热力图/检测框）
│   ├── widgets/            # 自定义组件（视口、鹰眼、病灶画廊等）
│   └── dialogs/            # 设置对话框
├── workers/                # 并发任务调度层
│   ├── ai_worker.py        # AI 推理线程
│   ├── gallery_worker.py   # 病灶缩略图截取线程
│   ├── profile_worker.py   # I/O 测速与硬件画像线程
│   ├── render_worker.py    # 瓦片渲染协调器
│   ├── thumbnail_worker.py # 缩略图生成线程
│   └── tile_scheduler.py   # 优先级瓦片调度器 + PreloadTask
└── utils/                  # 基础工具
    ├── db_manager.py       # SQLite 单例管理器
    ├── db_schema.py        # DDL 表结构
    ├── hardware_profiler.py# 硬件探针与基准测试
    ├── logger.py           # 全局日志系统
    └── nms.py              # 非极大值抑制算法
```

## 运行说明
1. 确保 Python 3.9+，建议配置 CUDA 计算环境。
2. 安装依赖：
   ```bash
   pip install PySide6 openslide-python opencv-python numpy ultralytics torch
   ```
3. 运行：
   ```bash
   python main.py
   ```
4. 打开 `.svs`、`.tif` 或 `.ndpi` 切片文件进行分析。

## 打包
```bash
pyinstaller WSIAnalyzer.spec
```

---

*注：本项目相关医疗辅助诊断算法及其生成结论仅供科研与测试探讨，不应直接代替执业医师的临床诊断意见。*
