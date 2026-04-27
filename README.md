# 基于深度学习的微乳头型肺腺癌 WSI 辅助诊断系统
(WSI Auxiliary Diagnosis System for Micropapillary Lung Adenocarcinoma)

## 项目简介
本项目是一款面向数字化病理辅助诊断的桌面端系统软件。针对微乳头型肺腺癌（Micropapillary pattern）的临床诊断需求，系统依托深度学习目标检测模型，可在数字病理全尺寸切片（WSI, 如 `.svs` 等格式）中自动定位并标注微乳头细胞簇。系统目前原生支持 YOLOv8 架构及通用的 ONNX 格式模型，通过提供全片自动化分析与局部感兴趣区域 (ROI) 靶向分析，旨在协助病理医生提升阅片效率与诊断准确率。

## 核心工程特性

### 1. 高性能瓦片级渲染引擎 (High-Performance Tile-Based Rendering)
- **多线程并发调度**：引入 `QThreadPool` 瓦片化并发渲染机制，替代传统的全图加载模式，实现视口区域按需加载。
- **LRU 内存缓存管理**：基于 OrderedDict 实现 `TileLRUCache` 瓦片缓存池，优化视口平移与缩放时的图块复用效率。
- **跨层级渲染优化**：应用动态金字塔层级 (Level) 匹配与 Z-index 提升机制，防止缩放期间高低分辨率图层交错引起的视觉异常。

### 2. 工业级 AI 推理管线 (Industrial AI Pipeline)
- **多模型架构兼容**：引入 `ModelAdapterFactory`，支持直接加载 PyTorch (`.pt`) 格式的 YOLO 模型或具备框架无关性的 `.onnx` 模型进行推断。
- **ROI 靶向分析**：支持基于用户框选的局部区域进行特定分析，自动切换至密集滑动步长进行高精度计算，并合并全片推理数据。
- **异步推理与全局去重**：将模型推理与主界面通过 `QThread` 剥离，并使用非极大值抑制 (NMS) 算法结合绝对物理坐标处理局部与全局预测框的重叠问题。

### 3. 硬件环境自适应与智能调优 (Hardware Auto-Tuning)
- **多维硬件探针**：利用 `HardwareProfiler` 动态侦测计算设备 (CUDA/MPS/CPU)、显存与内存容量，以及实际的磁盘 I/O 吞吐率。
- **启发式参数分配**：基于指数移动平均 (EMA) 算法计算硬件画像，动态分配当前环境的最优推断批次大小 (`batch_size`) 与滑动步长 (`stride`)。
- **运行时 OOM 回退机制**：自动捕获推断期间的显存溢出 (CUDA Out of Memory) 异常，并动态触发批处理降级（减半）与队列重试，保障系统稳定性。

### 4. 数据持久化与系统架构 (Storage & Architecture)
- **SQLite 数据底座**：采用开启预写式日志 (WAL) 模式的本地 SQLite 数据库，提供基于文件特征哈希的断点续传与历史诊断结果提取功能。
- **多进程应用启动器**：通过 `AppLauncher` 剥离重型框架加载任务至子进程，实现毫秒级的启动界面展示，避免启动无响应。
- **跨平台报告导出**：支持一键导出包含基础统计指标的 CSV 表格、标准 JSON 数据，以及兼容 QuPath 等数字病理软件的 GeoJSON 多边形标注格式。
- **高危病灶画廊**：后台异步截取包含上下文信息的病灶缩略图，根据置信度排序在侧边栏展示，支持点击实现靶向定位。

## 技术栈
- **UI 与并发控制**: PySide6 (Qt for Python), multiprocessing, Tkinter (Launcher)
- **图像底层与矩阵运算**: OpenCV (`cv2`), NumPy, Pillow (`PIL`), OpenSlide (`openslide-python`)
- **深度学习引擎**: Ultralytics YOLOv8, PyTorch, TorchVision, ONNXRuntime
- **数据持久化**: SQLite3

## 核心目录结构
```text
WSIAnalyzer/
├── main.py                 # 系统入口与多进程启动管理器
├── config.py               # 全局参数配置（常量、视觉设置、阈值界限等）
├── core/                   # 核心逻辑与算法层
│   ├── ai_engine.py        # AI 推理主引擎（组织掩码、批处理推断、NMS）
│   ├── model_adapters.py   # 模型适配层（YOLO / ONNX 接入封装）
│   ├── roi_manager.py      # 感兴趣区域 (ROI) 坐标生成与数据融合
│   ├── slide_engine.py     # OpenSlide 底层读写封装与金字塔层级计算
│   └── launcher/           # 独立的多进程启动器控制逻辑
├── gui/                    # 用户界面交互层
│   ├── main_window.py      # 主窗口 UI 容器与核心事件派发
│   ├── mixins/             # 界面逻辑解耦组件（渲染控制、分析集成、文件管理等）
│   ├── widgets/            # 自定义核心组件（如视口、鹰眼地图、缩略图画廊等）
│   └── dialogs/            # 设置选项与参数调整弹窗
├── workers/                # 并发任务调度层 (QThread / QRunnable)
│   ├── ai_worker.py        # 异步 AI 诊断执行线程
│   ├── gallery_worker.py   # 侧边栏病灶缩略图异步截取线程
│   ├── profile_worker.py   # 硬件与 I/O 后台静默测速线程
│   └── render_worker.py    # 高清瓦片并发请求与渲染调度
└── utils/                  # 基础工程工具
    ├── db_manager.py       # SQLite 数据库与系统设置管理器
    ├── hardware_profiler.py# 物理硬件系统探针与性能基准测试
    ├── db_schema.py        # 数据库 DDL 表结构定义
    └── logger.py           # 全局日志格式化与异常捕获系统
```


## 运行说明
1. 确保系统已安装 Python 3.9+，建议预先配置好 CUDA 计算环境。
2. 安装核心依赖包：
   ```bash
   pip install PySide6 openslide-python opencv-python numpy ultralytics torch torchvision onnxruntime
   ```
3. 运行程序：
   ```bash
   python main.py
   ```
4. 在主界面中通过菜单栏打开 `.svs`, `.tif` 或 `.ndpi` 格式的病理切片文件进行分析。

---
*注：本项目相关医疗辅助诊断算法及其生成结论仅供科研与测试探讨，不应直接代替执业医师的临床诊断意见。*
