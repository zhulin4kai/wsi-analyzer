# 评估协议说明

本文档描述 WSIAnalyzer 的 AI 检测结果与医生标注对照评估方法。

---

## 1. GT 来源

医生使用 QuPath 等病理标注软件在 WSI 全分辨率图像上绘制感兴趣区域。
标注导出为 GeoJSON 格式，坐标系统为 WSI Level-0 像素坐标。

## 2. 支持的几何类型

- `Polygon`：单多边形，取其外环坐标计算最小外接矩形（bounding box）。
- `MultiPolygon`：多多边形，将所有子多边形的外环坐标展平后计算最小外接矩形。

## 3. Polygon 转 Bounding Box 的约定

由于本项目采用目标检测框作为输出形式，医生多边形标注需转换为矩形框
用于与模型预测框进行 IoU 匹配。转换方式为取多边形所有顶点坐标的
(x_min, y_min) 和 (x_max, y_max) 作为矩形框的左上角和右下角。

> 注意事项：此转换会丢失多边形的形状信息。本评估仅反映矩形框级别的定位能力，
> 不代表精确分割评估。论文中已对此假设进行说明。

## 4. 坐标系统

- AI 检测框：已在 Level-0 坐标（由 `PredictionMapper` 从局部坐标映射）。
- 医生标注框：GeoJSON 直接使用 Level-0 坐标。
- IoU 计算在 Level-0 坐标系中进行。

## 5. IoU 匹配规则

1. AI 检测框按置信度从高到低排序。
2. 对每个检测框，在所有未匹配的同类 GT 中找到 IoU 最大的。
3. IoU >= `iou_threshold`（默认 0.5）时判定为匹配（TP）。
4. 每个检测框最多匹配一个 GT，每个 GT 最多被一个检测框匹配。
5. 未匹配的检测框为 FP。
6. 未被任何检测框匹配的 GT 为 FN。

## 6. 评估指标计算

```text
Precision = TP / (TP + FP)
Recall    = TP / (TP + FN)
F1        = 2 * Precision * Recall / (Precision + Recall)

边界情况：
  TP + FP = 0  → Precision = 0
  TP + FN = 0  → Recall = 0
  Precision + Recall = 0 → F1 = 0
```

## 7. AP50 计算

使用 11-point interpolation：

1. 按置信度降序排序所有预测框。
2. 以每个预测框为阈值，累积 TP/FP，计算该点的 Precision/Recall。
3. 对 {0.0, 0.1, ..., 1.0} 共 11 个 recall 水平，
   取所有 recall >= 该水平的预测点中的最大 Precision。
4. 11 个 Precision 求均值即为 AP50。

## 8. 局限性

- Bounding box 无法完全表达不规则组织边界，评估不反映分割精度。
- 当前仅支持单类别（微乳头结构）评估，多类别扩展需修改 `class_aware` 参数。
- 医生标注之间存在主观差异，标注一致性问题未纳入评估。
- AP50 使用 11-point interpolation，部分论文使用 AUC interpolation，
  二者结果略有差异但在可比范围内。
