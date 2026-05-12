# WSI 算法流程说明

本文档面向论文写作和算法复现，描述 WSIAnalyzer 的核心算法链路。

---

## 1. WSI 金字塔读取

全切片图像（WSI）是一个多分辨率图像金字塔。Level-0 为原始分辨率，
后续层级为逐级降采样。系统通过 OpenSlide 库读取任意层级的任意区域。

```text
WSI 文件 (.svs / .tif / .ndpi)
  → openslide.OpenSlide(path)
  → level_0_dim (Level-0 宽度/高度)
  → level_downsamples (各层相对于 Level-0 的降采样因子)
  → read_region(location, level, size) 按需读取
```

## 2. 组织掩码与背景过滤

对 WSI 宏观缩略图（Level-3）使用大津法（Otsu）二值化，
将前景组织与白色背景分离，生成 `solid_mask`。

仅对掩码中心点落在前景上的窗口进行推理，避免对空白背景区域浪费算力。

## 3. MPP 尺度一致性

YOLO 模型在训练时对固定物理尺度（MPP, microns per pixel）敏感。
推理时必须匹配训练 MPP，否则模型感受野不对。

```text
target_mpp (模型训练 MPP): 由 model metadata sidecar 提供或用户设置
slide_mpp (WSI 原始 MPP): 读取 openslide.mpp-x

level0_window_size = round(model_input_size * target_mpp / slide_mpp)
read_level          = 最接近 target_mpp/slide_mpp 的金字塔层级
local_to_level0_scale = level0_window_size / model_input_size
```

当 WSI MPP 缺失时，从 `objective_power` 估算（10.0 / objective_power）。
两者均缺失时退化为 1:1 映射并记录 warning。

## 4. Patch 推理

每个推理窗口在 Level-0 上的覆盖范围为 `level0_window_size × level0_window_size`。
实际从 OpenSlide 读取时使用 `read_level`，读取尺寸为 `round(level0_window_size / read_downsample)`，
读取后 resize 到 `model_input_size × model_input_size` 送入 YOLO。

```text
PatchReader.read(coord):
  1. 从 (coord.x, coord.y) 读取 Level-0 区域
  2. 按 read_downsample 缩放到 read_size
  3. resize 到 model_input_size
  4. 转 RGB
```

## 5. 局部坐标到全局坐标映射

YOLO 输出的是相对于 512×512（或 768×768）局部图像的归一化坐标。
`PredictionMapper` 负责将其映射到 WSI Level-0 绝对坐标。

```text
level0_x = coord.x + local_x * local_to_level0_scale
level0_y = coord.y + local_y * local_to_level0_scale
```

## 6. 全局 NMS 融合

全片扫描产生大量重叠预测框。对映射到 Level-0 后的所有 raw_detections
执行全局 NMS（IoU-based），去重重叠框。

```python
nms_numpy(boxes, scores, iou_thresh) → keep_indices
```

NMS 后结果作为 final_detections 用于展示、导出和热力图。

## 7. 评估

系统支持与医生 GeoJSON 标注对照评估。流程：

1. 将医生标注的多边形转换为最小外接矩形（bounding box）。
2. 将 AI 检测框与医生标注框按置信度排序后进行一对一 IoU 匹配。
3. IoU >= 0.5 判定为 TP。
4. 计算 Precision、Recall、F1、AP50（11-point interpolation）。

详见 `docs/evaluation_protocol.md`。

## 8. 关键文件索引

| 环节 | 文件 |
|------|------|
| 金字塔读取 | `infrastructure/imaging/openslide_engine.py` |
| MPP 计算 | `domain/analysis/inference_geometry.py` |
| 坐标生成 | `domain/analysis/patch_plan.py` |
| 图像读取 | `infrastructure/imaging/patch_reader.py` |
| 模型推理 | `infrastructure/inference/batch_inferencer.py` |
| 坐标映射 | `infrastructure/inference/prediction_mapper.py` |
| NMS | `domain/detection/nms.py` |
| 服务编排 | `application/analysis/analysis_service.py` |
| 评估 | `domain/evaluation/matching.py`, `metrics.py` |
