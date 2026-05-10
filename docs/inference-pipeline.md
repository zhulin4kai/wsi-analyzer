# 推理全链路 (Inference Pipeline)

本文档描述 WSIAnalyzer 从加载一张 WSI 切片到输出诊断结果的完整流程。

---

## 1. 全链路概览

```
WSI 文件 (.svs/.tif/.ndpi)
    │
    ▼
┌──────────────────────────────────────────────────────────┐
│ 阶段 1: 坐标生成                                          │
│   TissueMaskGenerator → 组织掩码 (np.ndarray)              │
│   PatchPlanner        → [PatchCoordinate, PatchCoordinate, ...] │
│   ROIPlanner          → 同上, 限制在 ROI 框内              │
└──────────────────────┬───────────────────────────────────┘
                       │ 坐标列表
                       ▼
┌──────────────────────────────────────────────────────────┐
│ 阶段 2: 图像读取                                          │
│   PatchReader.read(coord) → PIL.Image (单块)              │
│   ThreadPoolExecutor 并发读取, 与推理异步                  │
└──────────────────────┬───────────────────────────────────┘
                       │ 批次图像 (batch_size 个/批)
                       ▼
┌──────────────────────────────────────────────────────────┐
│ 阶段 3: 批量推理                                          │
│   YOLOAdapter.predict(batch) → [boxes, scores, classes]   │
│   PredictionMapper.to_level0_batch() → Level-0 坐标映射   │
│   OOMRetryPolicy → 触发 OOM 时自动缩减 batch_size         │
└──────────────────────┬───────────────────────────────────┘
                       │ 原始检测框 (global_boxes/scores/classes)
                       ▼
┌──────────────────────────────────────────────────────────┐
│ 阶段 4: NMS 去重 + 结果构建                               │
│   nms_numpy(boxes, scores, iou_thresh) → keep_indices    │
│   AnalysisResultBuilder.completed() → AnalysisResult     │
└──────────────────────┬───────────────────────────────────┘
                       │ AnalysisResult
                       ▼
┌──────────────────────────────────────────────────────────┐
│ 阶段 5: 持久化 + 可视化                                    │
│   AnalysisResult.to_dict()      → SQLite (wsi_analysis 表)│
│   compute_heatmap_grid()        → 热力图 rgba             │
│   DetectionLayer.render()       → QGraphicsRectItem 绘制  │
└──────────────────────────────────────────────────────────┘
```

---

## 2. 阶段 1: 坐标生成

### 2.1 文件关系

```
domain/analysis/
  tissue_mask.py    TissueMaskGenerator      -- 生成组织掩码
  patch_plan.py     PatchPlanner             -- 掩码 → PatchCoordinate 列表
  roi_planner.py    ROIPlanner + generate_roi_coordinates() -- ROI 区域内的坐标

application/analysis/
  coordinate_service.py  AnalysisCoordinateService  -- 组合掩码生成 + 坐标规划
  analysis_config.py     AnalysisConfig             -- 推理参数 (patch_size, stride, ...)
```

### 2.2 流程详解

**第一步: 组织掩码生成**

`TissueMaskGenerator` 接收 OpenSlide 读取的宏观缩略图, 转为灰度后二值化,
产出一张 `solid_mask` (np.ndarray, shape=(H, W), 值 0 或 255):

```python
# 伪代码示例
generator = TissueMaskGenerator(min_area_ratio=0.001)
thumb_img, downsample = image_server.get_thumbnail(svs_path)
solid_mask = generator.generate(thumb_img)
# solid_mask[my, mx] == 255 表示该像素上有组织
```

`min_area_ratio=0.001` 表示掩码连通域面积小于总面积的 0.1% 时丢弃 (过滤噪点)。

**第二步: 滑动窗口规划**

`PatchPlanner` 在 Level-0 物理像素空间内按步长滑动, 检查每个窗口的中心点是否落在前景掩码上:

```python
# 伪代码示例
planner = PatchPlanner(patch_size=512, stride=400)
coords = planner.plan(solid_mask, level_0_dim=(w, h), downsample_factor=thumb_downsample)
# 返回: [PatchCoordinate(x=0, y=0, size=512, level=0), PatchCoordinate(x=400, y=0, ...), ...]
```

步长 (`stride`) 小于 patch_size 时产生重叠, 密集采样可降低漏检率。
步长等于 patch_size 时无重叠, 加速推理。

**第三步: ROI 模式**

当用户在界面框选 ROI 后, `ROIPlanner.plan()` 执行相同的模板操作,
但 `x_range` 和 `y_range` 被限制在 ROI 边界内:

```python
planner = ROIPlanner(patch_size=512, stride=200)  # ROI 模式默认 stride 更密集
coords = planner.plan(roi_bbox=(x_min, y_min, x_max, y_max), level_0_dim=(w, h))
```

---

## 3. 阶段 2: 图像读取

### 3.1 文件关系

```
infrastructure/imaging/
  patch_reader.py           PatchReader            -- 按 PatchCoordinate 读图像块
  openslide_read_adapter.py OpenSlideReadAdapter   -- 实现 SlideReadPort
  openslide_engine.py       OpenSlideEngine        -- OpenSlide 封装

domain/slide/
  coordinates.py            PatchCoordinate         -- (x, y, size, level, downsample)
  slide_read_port.py        SlideReadPort (协议)    -- read_region() 抽象
```

### 3.2 流程

`PatchReader` 封装了 "从 WSI Level-0 坐标读取图像块并缩放到目标尺寸" 的逻辑:

```python
# 伪代码示例
reader = PatchReader(engine, target_level=0, target_downsample=1.0, patch_size=512)
patch_img = reader.read(PatchCoordinate(x=1024, y=2048, size=512, level=0, downsample=1.0))
# patch_img: PIL.Image, 512x512 RGB
```

`BatchInferencer` 使用 `ThreadPoolExecutor(max_workers=4)` 并发调用 `reader.read()`，
与 GPU 推理流水线重叠执行，减少 GPU 空等。

---

## 4. 阶段 3: 批量推理

### 4.1 文件关系

```
infrastructure/inference/
  batch_inferencer.py   BatchInferencer    -- 批次推理引擎
  model_adapter.py      BaseModelAdapter   -- 模型适配器抽象
  yolo_adapter.py       YOLOAdapter        -- YOLO 实现
  model_factory.py      ModelAdapterFactory -- 工厂
  prediction_mapper.py  PredictionMapper   -- 从 patch 坐标映射到 Level-0
  oom_policy.py         OOMRetryPolicy     -- 显存溢出降级
  model_inspector.py    ModelInspector     -- 从 .pt 文件读取 imgsz
```

### 4.2 YOLOAdapter

`ModelAdapterFactory.create_adapter(model_path)` 根据文件后缀创建适配器。
当前支持 `.pt/.pth` (ultralytics YOLO):

```python
class YOLOAdapter(BaseModelAdapter):
    def load_model(self, model_path):  # 从文件加载 YOLO 模型到指定 device
    def predict(self, images, device, conf_thresh):  # 返回 [(boxes, scores, classes), ...]
    def get_default_patch_size(self):  # 尝试从 model.model.args 读取 imgsz
```

### 4.3 BatchInferencer

```python
class BatchInferencer:
    def infer(self, coords, progress_callback, cancel_check):
        # 1. 分批: 每次取 batch_size 个坐标
        # 2. 并发读取: ThreadPoolExecutor.map(PatchReader.read, batch_coords)
        # 3. GPU 推理: YOLOAdapter.predict(batch_images)
        # 4. OOM 重试: 如果 RuntimeError 且为 OOM, 减半 batch_size 重试
        # 5. 坐标映射: PredictionMapper.to_level0_batch() 将检测框从 patch 到 Level-0
        # 返回 (global_boxes, global_scores, global_classes, processed_count)
```

### 4.4 坐标映射 (PredictionMapper)

YOLO 输出的是相对于 512x512 patch 的相对坐标 `[0, 1]`。
`PredictionMapper.to_level0_batch()` 将其映射为 Level-0 绝对坐标:

```
Level-0 box = (patch_x + rel_x * patch_size, patch_y + rel_y * patch_size,
               patch_x + rel_w * patch_size, patch_y + rel_h * patch_size)
```

---

## 5. 阶段 4: NMS 去重 + 结果构建

### 5.1 文件关系

```
domain/detection/
  nms.py        nms_numpy()           -- NumPy 实现的标准 NMS
  fusion.py     fuse_results()        -- 合并已有结果与新结果 + NMS
  entities.py   Detection             -- dataclass: bbox(Level0Box), confidence, class_id

domain/analysis/
  result.py     AnalysisResult        -- 全链路结果 dataclass

application/analysis/
  result_builder.py  AnalysisResultBuilder  -- 从 raw boxes 构建 AnalysisResult
```

### 5.2 NMS

`nms_numpy(boxes, scores, iou_thresh)` 是注册在 `domain/detection/` 的纯算法:

```python
def nms_numpy(boxes: np.ndarray, scores: np.ndarray, iou_thresh: float) -> list[int]:
    """返回保留的索引列表，时间复杂度 O(N^2)。"""
```

在 `FullSlideAnalysisService` 中, NMS 先应用于全部 `global_boxes`,
再传给 `AnalysisResultBuilder` 生成 `AnalysisResult`。

### 5.3 结果融合 (ROI 模式)

`fuse_results()` 用于将 ROI 分析结果与已有全片结果合并:
```python
fused = fuse_results(existing_results, new_results, nms_iou_thresh)
# 内部: combined = existing + new, 然后对整个 combined 做 NMS
```

---

## 6. 阶段 5: 持久化 + 可视化

### 6.1 持久化

`analysis_repository.py` 中的 `AnalysisCache.save_analysis()` 将分析结果写入 SQLite:

```sql
-- wsi_analysis 表结构
CREATE TABLE IF NOT EXISTS wsi_analysis (
    wsi_hash TEXT PRIMARY KEY,
    file_path TEXT,
    model_path TEXT,
    status TEXT,           -- "completed" | "interrupted" | "error"
    total_patches INTEGER,
    processed_patches INTEGER,
    results_json TEXT,     -- NMS 过滤后的检测框 JSON
    valid_coords_json TEXT,-- 剩余待处理坐标 JSON (用于断点续扫)
    raw_detections_json TEXT,  -- 原始检测框 JSON
    updated_at TEXT
);
```

### 6.2 断点续扫

当用户取消分析后, 进度数据 (包括已处理的坐标 `valid_coords`, 已完成计数 `processed_patches`,
以及未经过 NMS 的原始检测框 `raw_boxes/raw_scores/raw_classes`) 被写入数据库。
下次加载同一切片时, `FullSlideAnalysisService.run()` 检测到 `resume_data` 存在,
跳过掩码生成, 从断点继续推理。

### 6.3 热力图

`domain/detection/heatmap.py` 中的 `compute_heatmap_grid()` 将每个检测框按其中心点
累加置信度到网格中, 经高斯模糊后归一化为 `[0, 1]` 浮点数组。
`grid_to_rgba()` 将其转为 RGBA 图像。UI 层 `HeatmapLayer` 负责将 RBGA numpy array 转换为 `QPixmap` 并叠加到 WSI 视图上。

```python
# 调用链
grid = compute_heatmap_grid(results, wsi_w, wsi_h, bin_size=512, blur_sigma=3.0)
rgba = grid_to_rgba(grid, alpha=180, alpha_gamma=0.5, colormap=cv2.COLORMAP_VIRIDIS)
# HeatmapLayer 将 rgba → QPixmap, setScale(bin_size) 对齐到 Level-0
```

---

## 7. 硬件自适应 (Auto-Tuning)

### 7.1 文件关系

```
infrastructure/hardware/
  profiler.py         HardwareProfiler   -- CUDA/MPS/CPU 检测, VRAM 查询, I/O 测速

application/analysis/
  auto_tune_service.py   AutoTuneService     -- 根据 io_speed + model_size 计算最优参数
  analysis_config_resolver.py  AnalysisConfigResolver  -- 综合 DB + HW + auto-tune
```

### 7.2 探测流程

1. `HardwareProfiler.get_compute_device()`: 尝试 `torch.cuda.is_available()` -- `mps` -- 降级为 `cpu`
2. `HardwareProfiler.get_vram_info(device)`: 通过 `pynvml` 或 `nvidia-smi` 获取显存
3. `HardwareProfiler.measure_io_speed(file_path, engine_init_func)`: 测量打开 WSI 文件到获取缩略图的时间, 反推 I/O 吞吐率 (MB/s)

### 7.3 参数计算

```python
# HardwareProfiler.calculate_optimal_params()
usable_vram = free_vram - model_overhead - safety_margin
theoretical_batch_size = int(usable_vram / vram_per_tile)

# 根据 I/O 速度分级限制
if io_speed < IO_SPEED_NAS_USB2:    capped = min(theoretical, CAP_NAS_USB2)
elif io_speed < IO_SPEED_SATA_SSD:  capped = min(theoretical, CAP_SATA_SSD)
elif io_speed < IO_SPEED_NORMAL_SSD: capped = min(theoretical, CAP_NORMAL_SSD)
else:                               capped = min(theoretical, CAP_NVME_SSD)

final_batch_size = max(1, capped)
```

---

## 8. MPP 对齐原理

训练数据使用的物理分辨率 (MPP, Microns Per Pixel) 决定了模型感受野。
推理时必须匹配训练时的 MPP, 否则模型看到的目标尺度会发生变化。

代码流程:
1. 读取 WSI 的 MPP 元数据: `engine.mpp = (mpp_x, mpp_y)`
2. 通过 `engine.get_best_level_for_mpp(target_mpp)` 选择最接近目标 MPP 的金字塔层级
3. 在该层级上以固定的 patch_size (如 512) 采样
4. 将检测结果通过 `downsample_factor` 映射回 Level-0

配置项 `AI_MODEL_TARGET_MPP` 在 `config.py` 中定义, 用户可在设置对话框中按模型倍率调整。

---

## 9. 相关文件索引

| 环节 | 核心文件 |
|------|---------|
| 入口 | `workers/ai_worker.py` (45 行, 仅信号桥接) |
| 编排 | `application/analysis/analysis_service.py` (`FullSlideAnalysisService.run()`) |
| 工厂 | `application/analysis/analysis_service_factory.py` |
| 配置 | `application/analysis/analysis_config_resolver.py` |
| 坐标 | `domain/analysis/patch_plan.py`, `domain/analysis/roi_planner.py` |
| 推理 | `infrastructure/inference/batch_inferencer.py`, `yolo_adapter.py` |
| NMS | `domain/detection/nms.py`, `domain/detection/fusion.py` |
| 结果 | `domain/analysis/result.py` (`AnalysisResult`) |
| 热力图 | `domain/detection/heatmap.py` |
| 持久化 | `infrastructure/persistence/analysis_repository.py` |
