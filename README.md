# 🔬 基于YOLOv8的微乳头型肺腺癌WSI辅助诊断系统
**(WSI Auxiliary Diagnosis System for Micropapillary Lung Adenocarcinoma based on YOLOv8)**

## 📖 项目简介
本项目是一款面向病理学数字化的桌面端计算机视觉辅助诊断软件。针对**微乳头型肺腺癌（Micropapillary pattern）**这一高侵袭性亚型的临床诊断痛点，系统依托 YOLOv8 深度学习模型，能够在几十GB的数字病理全尺寸切片（WSI, `.svs` 等格式）中，全自动、高精度地定位并标注游离于肺泡腔内的微乳头细胞簇，协助病理医生提升阅片效率与诊断准确率。

当前模型在测试集上表现优异：`mAP@0.5 = 0.956`，`mAP@0.5:0.95 = 0.868`。

## ✨ 核心工程特性

### 1. 🚀 高性能渲染引擎 (High-Performance Viewport Rendering)
- **按需动态加载**：彻底屏弃全图加载机制，根据用户当前视口的缩放比例与坐标，实时通过 `OpenSlide` 提取最佳金字塔层级 (Level) 的图像块。
- **宏观底图铺垫 (Global Base Map)**：底层常驻放大的极低分辨率缩略图，解决在网络/磁盘 I/O 期间画布边缘出现的“黑屏”断层问题。
- **交互级动态降级 (LOD & Debounce)**：引入 150ms 防抖机制与状态机。在用户连续拖拽或滚轮缩放时，自动隐藏沉重的 AI 预测框图层并暂停高清渲染，保证阅片时 60FPS 的满帧丝滑交互，停止操作后瞬间恢复。

### 2. 🧠 工业级 AI 推理管线 (Industrial AI Pipeline)
- **智能实心组织掩码生成 (Solid Tissue Mask)**：针对微乳头细胞“漂浮”在空腔中的病理特性，独创“轮廓提取+内部全填充”的形态学算法。动态计算相对面积阈值，有效过滤载玻片杂质，**完美保留组织内部有效空腔**。
- **动态坐标映射与批量推断 (Batch Inference)**：在掩码区域生成 512x512 切图矩阵（包含 400 步长重叠区），构建 Batch 批量送入 GPU 推理，大幅提升推断速度。
- **全局非极大值抑制 (Global NMS)**：将局部坐标还原为 WSI 全局绝对坐标，并利用 PyTorch 原生 NMS 算法无缝剔除切图边缘造成的重叠检测框。
- **异步非阻塞架构**：采用 `QThread` 将 AI 推理与主界面彻底剥离，配合信号槽 (Signal/Slot) 机制实时回传进度条状态，杜绝界面假死。

### 3. 💾 工程化缓存与交互 (Engineering Cache & UX)
- **静默特征哈希缓存 (Silent Local Cache)**：利用文件大小与修改时间戳生成极速哈希（非全图MD5），将长达数十分钟的推理结果静默存入 `.wsi_cache/`。二次打开同一张切片实现**“毫秒级渲染”**。
- **全景鹰眼导航 (Minimap)**：基于最小分辨率层级的双向同步导航窗，支持全局定位指示与点击快速跳转。
- **结构化诊断报告导出**：一键进行基础统计计算，并导出支持 Excel 的 `.csv` 或标准 `.json` 病灶坐标清单。

## 🛠️ 技术栈
- **UI 框架**: PySide6 (Qt for Python)
- **图像与矩阵处理**: OpenCV (`cv2`), NumPy, Pillow (`PIL`)
- **WSI 解析底层**: OpenSlide (`openslide-python`)
- **深度学习算法**: Ultralytics YOLOv8, PyTorch, TorchVision
- **打包部署**: PyInstaller (计划中)

## 📁 核心目录结构
```text
📦 WSI-Lung-Adenocarcinoma-Detector
WSIAnalyzer/
├── main.py                 # 软件唯一入口，负责组装各个模块
├── config.py               # 全局配置（Pen颜色、缩放比例、阈值、路径常量）
├── core/                   # 核心逻辑层（不涉及 GUI 绘制）
│   ├── __init__.py
│   ├── slide_engine.py     # OpenSlide 的二次封装（处理 IO、层级计算）
│   └── ai_engine.py        # 原 Analyzer.py，纯粹的 YOLO 推理逻辑
├── gui/                    # 界面层（负责绘图与交互）
│   ├── __init__.py
│   ├── main_window.py      # 主窗口布局、菜单、工具栏
│   ├── widgets/            # 自定义复杂组件
│   │   ├── wsi_view.py     # 原 BaseViewer.py 中的 WSIView
│   │   └── minimap_view.py # 原 Minimap.py
│   └── styles.py           # QSS 样式表或统一的 UI 配色
├── workers/                # 并发层（所有的 QThread）
│   ├── __init__.py
│   ├── render_worker.py    # 负责视口高清渲染的线程
│   └── ai_worker.py        # 负责执行 YOLO 的线程
└── utils/                  # 工具层
    ├── __init__.py
    ├── cache_manager.py    # 专门负责特征哈希计算与 .wsi_cache 读写
    ├── file_helper.py      # 处理 resource_path 和文件导出路径
    └── logger.py           # 统一日志管理
```

## 🗺️ 开发进度 (Roadmap)
- [x] **Phase 0:** 数据集构建、预处理及 YOLOv8 模型训练完成 (mAP50: 95.6%)。
- [x] **Phase 1:** 离线 AI 分析管线 `Analyzer` 编写完成，打通滑动切图与全局 NMS 逻辑。
- [x] **Phase 2:** 基于 `QGraphicsView` 的基础 WSI 阅片器搭建完成，攻克视口按需动态渲染。
- [x] **Phase 3:** QThread 异步 AI 引擎接入，实现坐标 1:1 映射画框与静默哈希缓存机制。
- [ ] **Phase 4:** 交互防抖调优、鹰眼图开发、诊断报告导出功能完善。
- [ ] **Phase 5:** 基于 `PyInstaller` 解决 OpenSlide 与 PyTorch 动态库依赖，打包独立发行版 `.exe`。

## 💡 运行说明
1. 确保已安装 Python 3.9+ 及 CUDA 支持（推荐）。
2. 安装核心依赖：`pip install PySide6 openslide-python opencv-python numpy ultralytics torch torchvision`
3. 运行程序：`python main.py`
4. 通过“文件”菜单打开 `.svs` 格式的病理切片即可开始分析。

---
*本项目为毕业设计作品，相关医疗辅助诊断结论仅供科研探讨，不可直接代替执业医师的临床诊断。*
