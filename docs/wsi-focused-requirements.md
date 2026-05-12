# WSI 方向功能补强需求规格

## 总目标

当前项目不再优先扩展通用软件功能，而是围绕 WSI 全尺寸病理切片分析形成可验证闭环：

```text
WSI 输入
  → 基于 MPP 的尺度一致性滑窗推理
  → 全局坐标映射
  → 全局 NMS 融合
  → 与医生 GeoJSON 标注对照
  → 输出定量评估、辅助检测报告、论文图像
```

本轮需求的重点是：

1. 建立 AI 检测结果与医生标注之间的评估闭环。
2. 支持批量 WSI 实验，输出论文可用表格。
3. 强化报告中的 WSI、MPP、模型、推理参数可追溯信息。
4. 统一医学表述，避免将系统结果表述为最终诊断。
5. 自动导出论文插图和误检漏检样例。

---

# 需求 1：新增 evaluation 模块，实现检测结果与医生标注对照评估

## 1.1 目标

新增独立评估模块，将系统 AI 检测框与医生 GeoJSON 标注框进行匹配，输出：

```text
TP
FP
FN
Precision
Recall
F1
AP50
mAP@0.5
按切片统计结果
按目标统计结果
误检样例
漏检样例
```

这一步是当前最重要的功能。医学目标检测论文必须给出 Precision、Recall、F1、mAP 等指标。病理 WSI 目标检测研究中也常以 IoU≥0.5 判断 TP，并据此计算 Precision、Recall、AP/mAP。

## 1.2 新增文件

```text
wsi_analyzer/domain/evaluation/
├── __init__.py
├── entities.py
├── matching.py
├── metrics.py
└── converters.py

wsi_analyzer/application/evaluation/
├── __init__.py
└── evaluation_service.py

tests/domain/evaluation/
├── test_iou.py
├── test_matching.py
└── test_metrics.py
```

## 1.3 `entities.py`

新增数据结构。

```python
from dataclasses import dataclass, field
from typing import Optional, Literal


@dataclass(frozen=True)
class EvalBox:
    box_id: str
    slide_id: str
    x1: float
    y1: float
    x2: float
    y2: float
    class_id: int = 0
    class_name: str = "micropapillary"
    confidence: Optional[float] = None
    source: Literal["prediction", "ground_truth"] = "prediction"


@dataclass(frozen=True)
class MatchRecord:
    prediction: Optional[EvalBox]
    ground_truth: Optional[EvalBox]
    iou: float
    status: Literal["TP", "FP", "FN"]


@dataclass(frozen=True)
class EvaluationMetrics:
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float
    ap50: Optional[float] = None


@dataclass(frozen=True)
class EvaluationResult:
    slide_id: str
    iou_threshold: float
    metrics: EvaluationMetrics
    matches: list[MatchRecord] = field(default_factory=list)
```

## 1.4 `matching.py`

实现 IoU 和一对一匹配。

### 必须提供函数

```python
def box_iou(a: EvalBox, b: EvalBox) -> float:
    ...
```

```python
def match_predictions_to_ground_truth(
    predictions: list[EvalBox],
    ground_truths: list[EvalBox],
    iou_threshold: float = 0.5,
    class_aware: bool = True,
) -> list[MatchRecord]:
    ...
```

### 匹配规则

1. 按 `confidence` 从高到低处理预测框。
2. 每个预测框最多匹配一个 GT。
3. 每个 GT 最多被一个预测框匹配。
4. IoU ≥ `iou_threshold` 判定为 TP。
5. 没有匹配到 GT 的预测框判定为 FP。
6. 没有被匹配的 GT 判定为 FN。
7. 默认 `class_aware=True`，不同类别不匹配。
8. 当前项目只有微乳头一个类别时，`class_id=0` 即可。

## 1.5 `metrics.py`

实现指标计算。

### 必须提供函数

```python
def compute_detection_metrics(matches: list[MatchRecord]) -> EvaluationMetrics:
    ...
```

计算公式：

```text
Precision = TP / (TP + FP)
Recall    = TP / (TP + FN)
F1        = 2 * Precision * Recall / (Precision + Recall)
```

边界情况：

```text
TP + FP = 0 时 Precision = 0
TP + FN = 0 时 Recall = 0
Precision + Recall = 0 时 F1 = 0
```

### AP50

```python
def compute_ap50(
    predictions: list[EvalBox],
    ground_truths: list[EvalBox],
    iou_threshold: float = 0.5,
) -> float:
    ...
```

要求：

1. 按置信度从高到低排序预测框。
2. 逐个阈值累计 TP / FP。
3. 生成 Precision-Recall 曲线。
4. 使用 101-point interpolation 或梯形积分均可。
5. 文档中注明所用 AP 计算方法。

## 1.6 `converters.py`

负责把项目现有检测结果和 GeoJSON 标注转为 `EvalBox`。

### 必须提供函数

```python
def detections_to_eval_boxes(
    detections,
    slide_id: str,
) -> list[EvalBox]:
    ...
```

兼容输入：

```text
Detection 对象
AnalysisResult.detections
results_json 中的字典结构
```

```python
def geojson_annotations_to_eval_boxes(
    geojson_path: str,
    slide_id: str,
) -> list[EvalBox]:
    ...
```

规则：

1. 支持 `Polygon`。
2. 支持 `MultiPolygon`。
3. Polygon 转 bbox 时取所有点的最小外接矩形。
4. 坐标必须保持 Level-0 WSI 坐标。
5. 医生标注 `confidence=None`，`source="ground_truth"`。
6. 如果 GeoJSON 内已有类别字段，尽量解析；否则默认微乳头。

## 1.7 `evaluation_service.py`

新增应用层服务。

```python
class EvaluationService:
    def evaluate_slide(
        self,
        slide_id: str,
        predictions: list[EvalBox],
        ground_truths: list[EvalBox],
        iou_threshold: float = 0.5,
    ) -> EvaluationResult:
        ...

    def evaluate_from_files(
        self,
        slide_id: str,
        prediction_json_path: str,
        ground_truth_geojson_path: str,
        iou_threshold: float = 0.5,
    ) -> EvaluationResult:
        ...
```

## 1.8 单元测试要求

### `test_iou.py`

覆盖：

```text
完全重叠 IoU = 1
完全不重叠 IoU = 0
部分重叠 IoU 正确
边界接触 IoU = 0
非法框 x2 < x1 时抛出异常或标准化
```

### `test_matching.py`

覆盖：

```text
一个预测框匹配一个 GT → TP
一个预测框无匹配 → FP
一个 GT 无匹配 → FN
多个预测框抢同一个 GT → 最高置信度为 TP，其余 FP
IoU 低于阈值 → FP + FN
```

### `test_metrics.py`

覆盖：

```text
TP=8 FP=2 FN=2 → Precision=0.8 Recall=0.8 F1=0.8
无预测框
无 GT
全部误检
全部漏检
```

---

# 需求 2：新增批量 WSI 实验脚本，输出论文实验表

## 2.1 目标

新增命令行脚本，对多个 WSI 自动执行：

```text
读取 WSI
执行全片推理
读取对应 GeoJSON 标注
计算评估指标
统计推理耗时和 patch 数
输出 CSV / JSON
```

论文第 5 章需要批量实验结果，而不是只展示一个病例截图。任务书中也要求在测试集上验证识别精度、推理速度和鲁棒性，不能只停留在 UI 展示。

## 2.2 新增文件

```text
scripts/evaluate_wsi_batch.py

wsi_analyzer/application/evaluation/
└── batch_evaluation_service.py

tests/application/evaluation/
└── test_batch_evaluation_service.py
```

## 2.3 命令行接口

```bash
python scripts/evaluate_wsi_batch.py \
  --wsi-dir data/test_wsi \
  --gt-dir data/geojson \
  --model runs/detect/best.pt \
  --out-dir results/eval_run_001 \
  --conf 0.25 \
  --iou 0.5 \
  --nms-iou 0.5 \
  --device cuda:0 \
  --resume
```

## 2.4 参数规格

| 参数                  | 必填 | 说明               |
| ------------------- | -: | ---------------- |
| `--wsi-dir`         |  是 | 测试 WSI 文件目录      |
| `--gt-dir`          |  是 | 医生 GeoJSON 标注目录  |
| `--model`           |  是 | YOLO `.pt` 模型路径  |
| `--out-dir`         |  是 | 输出目录             |
| `--conf`            |  否 | 置信度阈值，默认读取项目配置   |
| `--iou`             |  否 | 评估 IoU 阈值，默认 0.5 |
| `--nms-iou`         |  否 | 全局 NMS 阈值        |
| `--device`          |  否 | `cpu` / `cuda:0` |
| `--resume`          |  否 | 是否复用已有缓存结果       |
| `--limit`           |  否 | 调试时最多处理多少张 WSI   |
| `--skip-missing-gt` |  否 | 缺少标注时跳过，而不是中断    |

## 2.5 WSI 与 GeoJSON 匹配规则

默认按文件 stem 匹配：

```text
001.svs
001.geojson
```

允许大小写扩展名：

```text
.svs
.tif
.tiff
.ndpi
.mrxs
.geojson
.json
```

如果找不到对应标注：

```text
默认报错
传入 --skip-missing-gt 时记录到 failed_cases.csv
```

## 2.6 输出文件

```text
results/eval_run_001/
├── eval_summary.csv
├── eval_summary.json
├── eval_details.json
├── failed_cases.csv
├── config_snapshot.json
└── logs/
```

### `eval_summary.csv` 字段

```text
slide_id
wsi_path
gt_path
model_path
slide_width
slide_height
slide_mpp
target_mpp
model_input_size
level0_window_size
stride
total_patches
processed_patches
tissue_patches
detection_count
gt_count
tp
fp
fn
precision
recall
f1
ap50
analysis_seconds
patches_per_second
device
conf_threshold
eval_iou_threshold
nms_iou_threshold
status
error_message
```

### `eval_details.json`

每张切片保存：

```json
{
  "slide_id": "...",
  "metrics": {},
  "matches": [
    {
      "status": "TP",
      "iou": 0.72,
      "prediction": {},
      "ground_truth": {}
    }
  ],
  "false_positives": [],
  "false_negatives": []
}
```

## 2.7 与现有代码集成

优先复用已有全片分析服务，不重新写推理流程：

```text
wsi_analyzer/application/analysis/analysis_service.py
wsi_analyzer/application/analysis/analysis_config_resolver.py
wsi_analyzer/domain/analysis/inference_geometry.py
wsi_analyzer/infrastructure/inference/prediction_mapper.py
```

批处理脚本只做调度和汇总，不要绕过现有 WSI 推理链路。

## 2.8 验收标准

运行一条命令后，可以得到：

```text
每张 WSI 的 Precision / Recall / F1 / AP50
总体平均 Precision / Recall / F1 / AP50
总耗时
平均每张切片耗时
失败病例列表
```

---

# 需求 3：增强辅助检测报告，加入 WSI、MPP、模型、推理参数、评估结果

## 3.1 目标

当前报告不应只是检测框列表。报告必须能回答：

```text
这张 WSI 是什么？
它的物理尺度是多少？
模型按什么 target_mpp 推理？
实际裁剪窗口多大？
用了什么模型？
用了什么阈值？
检测结果能否与医生标注对照？
```

这与 WSI 病理任务强相关。因为 WSI 不能直接整图输入深度模型，主流做法是 patch 级处理再聚合；病理研究中也明确指出 WSI 尺寸巨大，必须在 patch 层级处理。

## 3.2 修改文件

```text
wsi_analyzer/ui/widgets/report_exporter.py
wsi_analyzer/domain/analysis/result.py
wsi_analyzer/domain/model/model_metadata.py
wsi_analyzer/application/analysis/analysis_config_resolver.py
```

可选新增：

```text
wsi_analyzer/application/reporting/
├── __init__.py
├── report_models.py
└── report_builder.py
```

## 3.3 报告名称统一修改

将所有：

```text
诊断报告
```

改为：

```text
AI辅助检测报告
```

或：

```text
病理图像辅助分析报告
```

禁止在报告中出现类似：

```text
最终诊断
确诊为
诊断结论
癌症判定
```

推荐表述：

```text
AI 疑似微乳头结构检测结果
辅助检测结果
供病理医生复核参考
不替代病理医生最终诊断
```

## 3.4 CSV 报告新增字段

在原有检测结果 CSV 前增加 summary 区域或另导出 `*_summary.csv`。

字段：

```text
report_type
slide_id
wsi_filename
wsi_width
wsi_height
slide_mpp_x
slide_mpp_y
objective_power
model_path
model_name
model_backend
model_task
model_input_size
target_mpp
trained_level
coordinate_system
class_names
conf_threshold
nms_iou_threshold
batch_size
device
level0_window_size
level0_stride
total_patches
processed_patches
tissue_patches
detection_count
average_confidence
max_confidence
high_conf_count
medium_conf_count
low_conf_count
evaluation_enabled
tp
fp
fn
precision
recall
f1
ap50
created_at
disclaimer
```

## 3.5 JSON 报告结构

```json
{
  "report_type": "AI辅助检测报告",
  "slide": {
    "id": "...",
    "filename": "...",
    "width": 0,
    "height": 0,
    "mpp_x": 0.0,
    "mpp_y": 0.0,
    "objective_power": "40x"
  },
  "model": {
    "path": "...",
    "name": "...",
    "backend": "ultralytics",
    "task": "detect",
    "input_size": 640,
    "target_mpp": 0.25,
    "classes": ["micropapillary"]
  },
  "inference": {
    "conf_threshold": 0.25,
    "nms_iou_threshold": 0.5,
    "batch_size": 8,
    "device": "cuda:0",
    "level0_window_size": 1024,
    "level0_stride": 768,
    "total_patches": 12345,
    "processed_patches": 12345
  },
  "detections": [],
  "evaluation": {
    "enabled": true,
    "iou_threshold": 0.5,
    "tp": 0,
    "fp": 0,
    "fn": 0,
    "precision": 0.0,
    "recall": 0.0,
    "f1": 0.0,
    "ap50": 0.0
  },
  "disclaimer": "本报告为AI辅助检测结果，仅供病理医生复核参考，不替代最终病理诊断。"
}
```

## 3.6 GeoJSON 导出属性增强

每个 Feature 的 `properties` 增加：

```json
{
  "source": "ai_prediction",
  "class_name": "micropapillary",
  "confidence": 0.83,
  "model_name": "...",
  "model_path": "...",
  "target_mpp": 0.25,
  "slide_mpp": 0.25,
  "coordinate_system": "level0",
  "report_type": "AI辅助检测结果"
}
```

## 3.7 验收标准

1. 导出的 CSV / JSON / GeoJSON 均不再使用“诊断报告”作为核心名称。
2. 报告中能看到 `slide_mpp`、`target_mpp`、`level0_window_size`。
3. 报告中能看到模型 metadata。
4. 如果执行了 evaluation，报告中能看到 TP / FP / FN / Precision / Recall / F1 / AP50。
5. 报告底部或 JSON 字段中有免责声明。

---

# 需求 4：自动导出论文插图包

## 4.1 目标

新增脚本自动导出论文和答辩使用的固定图像，不依赖手动截图。

输出内容包括：

```text
原始组织缩略图
AI 检测叠加图
热力图
医生标注 vs AI 检测对照图
高置信度病灶样例
误检样例
漏检样例
```

病理 WSI 研究常用整片可视化、热图、标注对照来展示模型结果；肺腺癌组织学模式研究中也通过 WSI 可视化对比病理医生标注和模型检测区域。

## 4.2 新增文件

```text
scripts/export_paper_figures.py

wsi_analyzer/application/visualization/
├── __init__.py
├── paper_figure_exporter.py
└── overlay_renderer.py

tests/application/visualization/
└── test_paper_figure_exporter.py
```

## 4.3 命令行接口

```bash
python scripts/export_paper_figures.py \
  --wsi data/test_wsi/001.svs \
  --prediction results/eval_run_001/details/001_predictions.json \
  --gt data/geojson/001.geojson \
  --eval results/eval_run_001/eval_details.json \
  --out-dir results/figures/001 \
  --max-examples 12
```

## 4.4 输出文件

```text
results/figures/001/
├── 01_original_thumbnail.png
├── 02_prediction_overlay.png
├── 03_heatmap.png
├── 04_gt_vs_pred_overlay.png
├── 05_top_confidence_lesions/
│   ├── lesion_001_conf_0.94.png
│   └── lesion_002_conf_0.91.png
├── 06_false_positive_examples/
│   ├── fp_001_conf_0.88.png
│   └── fp_002_conf_0.81.png
└── 07_false_negative_examples/
    ├── fn_001.png
    └── fn_002.png
```

## 4.5 图像规格

### `01_original_thumbnail.png`

要求：

```text
显示 WSI 低倍缩略图
保留组织整体形状
不画检测框
最长边默认 2048 px
```

### `02_prediction_overlay.png`

要求：

```text
在缩略图上绘制 AI 检测框
框大小按 Level-0 坐标缩放
标注 confidence
支持只显示 conf >= 指定阈值
```

### `03_heatmap.png`

要求：

```text
根据检测框中心点或框面积生成密度热力图
映射到 WSI 缩略图坐标
输出透明叠加版本
```

### `04_gt_vs_pred_overlay.png`

要求：

```text
医生 GT 与 AI prediction 同图显示
GT 使用一种样式
Prediction 使用另一种样式
TP / FP / FN 可区分
必须带图例
```

### FP / FN 样例

裁剪规则：

```text
以 FP 或 FN 框中心为中心
从 Level-0 读取上下文 patch
默认导出 512×512 或 1024×1024
保持原始病理纹理，不做强增强
文件名包含 confidence 或 iou
```

## 4.6 验收标准

1. 输入一张 WSI + 预测 + GT + 评估结果，自动生成完整图像目录。
2. 图像坐标与 WSI Level-0 坐标对应正确。
3. FP / FN 样例能直接放入论文“误检漏检分析”。
4. 不需要打开 UI 手动截图。

---

# 需求 5：UI 层增加 MPP 风险提示，但不扩展复杂功能

## 5.1 目标

在 UI 中只增加与 WSI 推理可靠性强相关的提示，不做新的复杂页面。

重点提示：

```text
slide_mpp 缺失
slide_mpp 与 target_mpp 差异过大
模型 metadata 缺失
当前推理窗口由默认参数推导
当前结果可能存在尺度偏差
```

MPP 是 WSI 检测的关键工程变量。微乳头等病理结构具有真实物理尺度，不能只靠固定像素窗口解释。任务书中也要求掌握 WSI 预处理、降采样、滑窗切割和全局坐标映射。

## 5.2 修改文件

根据当前 UI 实际结构选择：

```text
wsi_analyzer/ui/main_window.py
wsi_analyzer/ui/widgets/wsi_view.py
wsi_analyzer/ui/widgets/analysis_panel.py
wsi_analyzer/ui/widgets/model_panel.py
```

如果已有状态栏或日志面板，优先复用，不新增复杂窗口。

## 5.3 新增提示逻辑

新增一个轻量函数：

```python
def build_mpp_warning(
    slide_mpp: float | None,
    target_mpp: float | None,
    metadata_source: str | None,
) -> str | None:
    ...
```

规则：

```text
slide_mpp is None:
    "当前切片缺少 MPP 信息，系统将使用默认尺度参数，检测结果可能存在尺度偏差。"

target_mpp is None:
    "当前模型缺少 target_mpp 元数据，系统无法确认训练尺度，建议补充模型 metadata。"

abs(slide_mpp - target_mpp) / target_mpp > 0.25:
    "当前切片 MPP 与模型训练 MPP 差异较大，系统已进行尺度换算，请复核检测结果。"

metadata_source == "default":
    "当前模型 metadata 来自默认配置，建议使用 sidecar metadata 或 checkpoint metadata。"
```

## 5.4 UI 显示位置

优先级：

```text
1. 分析开始前弹出非阻塞 warning
2. 状态栏显示简短提示
3. 日志区写入完整提示
4. 报告中写入 warning 字段
```

## 5.5 验收标准

1. MPP 缺失时用户能看到明确提示。
2. metadata 缺失时用户能看到明确提示。
3. 不阻塞正常推理。
4. 不新增大规模 UI 复杂度。

---

# 风险点 1：论文重点偏软件工程，算法与 WSI 方法贡献不突出

## 风险描述

当前项目工程完成度较高，但如果论文主要写：

```text
菜单
按钮
数据库
线程
导出
UI 交互
```

会导致论文看起来像普通软件系统，而不是“基于 YOLOv8 的 WSI 辅助检测方法”。

本科算法设计类目录明确要求算法设计与改进、真实数据实验、实验结果分析与验证。
因此论文和代码验收都应突出 WSI 算法链路。

## 规避要求

论文和项目说明中主线应调整为：

```text
WSI 超大图处理
Patch 滑窗推理
背景过滤
MPP 尺度一致性
局部坐标到 Level-0 全局坐标映射
全局 NMS 融合
医生标注对照评估
```

## 对代码的要求

新增文档：

```text
docs/wsi_algorithm_pipeline.md
```

内容包括：

```text
1. WSI 金字塔读取
2. tissue mask / 背景过滤
3. target_mpp 与 slide_mpp 的换算
4. level0_window_size 的计算
5. patch 推理
6. prediction mapper 坐标映射
7. global NMS
8. evaluation
```

不要新增“用户管理、病例管理、权限、云端部署”之类与论文无关的功能。

---

# 风险点 2：报告命名和系统文案具有“诊断”风险

## 风险描述

项目可以叫辅助诊断系统，但报告和界面不能表现为系统直接下医学诊断结论。

风险词：

```text
诊断结果
最终诊断
确诊
癌症判定
病理结论
```

推荐词：

```text
AI辅助检测结果
疑似微乳头结构
辅助分析
供医生复核
不替代最终病理诊断
```

## 修改范围

全局搜索：

```bash
grep -R "诊断报告\|诊断结果\|最终诊断\|确诊\|病理结论" wsi_analyzer docs scripts
```

重点修改：

```text
wsi_analyzer/ui/widgets/report_exporter.py
wsi_analyzer/ui/main_window.py
README.md
docs/*.md
```

## 必加免责声明

报告、JSON、UI 关于页或导出文件中加入：

```text
本结果由 AI 模型自动生成，仅用于辅助检测和病理医生复核参考，不作为最终病理诊断依据。
```

---

# 风险点 3：GeoJSON Polygon 转 bbox 会损失标注形状信息，必须说明

## 风险描述

医生标注通常是 Polygon / MultiPolygon，而 YOLO 检测输出是矩形框。
如果直接把 polygon 转成 bbox 做 IoU 评估，必须在论文和报告里说明：

```text
由于本文采用目标检测框作为输出形式，因此将医生多边形标注转换为最小外接矩形，作为检测任务中的真值框，用于与模型预测框进行 IoU 匹配。
```

否则老师或医生可能会质疑：

```text
医生画的是多边形，为什么用矩形框评估？
```

## 修改文件

```text
wsi_analyzer/domain/evaluation/converters.py
wsi_analyzer/ui/widgets/report_exporter.py
docs/wsi_algorithm_pipeline.md
docs/evaluation_protocol.md
```

## 新增文档

```text
docs/evaluation_protocol.md
```

内容必须包括：

```text
1. GT 来源：医生 GeoJSON 标注
2. 支持 Polygon / MultiPolygon
3. Polygon → bbox 的转换方式
4. 坐标系统一到 WSI Level-0
5. IoU 阈值默认 0.5
6. TP / FP / FN 判定规则
7. Precision / Recall / F1 / AP50 计算方法
8. 局限性：bbox 无法完全表达不规则组织边界
```

## 验收标准

1. 评估代码中保留 polygon 原始信息或至少在转换结果中记录 `original_geometry_type`。
2. 报告中说明 GT bbox 的来源。
3. 文档中明确 polygon-to-bbox 的评估假设。
4. 不把 bbox 评估伪装成精确分割评估。

---

# 建议提交顺序

## 第 1 次提交：evaluation 核心闭环

```text
新增 domain/evaluation
新增 application/evaluation
新增 tests/domain/evaluation
实现 IoU、matching、Precision、Recall、F1、AP50
```

提交信息：

```text
feat(evaluation): add WSI detection evaluation metrics
```

## 第 2 次提交：GeoJSON 与检测结果转换

```text
实现 geojson_annotations_to_eval_boxes
实现 detections_to_eval_boxes
补充 polygon-to-bbox 文档说明
```

提交信息：

```text
feat(evaluation): support GeoJSON ground truth conversion
```

## 第 3 次提交：批量实验脚本

```text
新增 scripts/evaluate_wsi_batch.py
输出 eval_summary.csv/json
输出 eval_details.json
```

提交信息：

```text
feat(batch): add batch WSI evaluation script
```

## 第 4 次提交：报告增强与医学表述修正

```text
增强 report_exporter
加入 WSI / MPP / model metadata / inference config / evaluation
替换诊断报告相关表述
加入免责声明
```

提交信息：

```text
feat(report): add traceable AI-assisted detection report
```

## 第 5 次提交：论文图像导出

```text
新增 export_paper_figures.py
新增 overlay_renderer
导出 prediction overlay / heatmap / gt-vs-pred / FP / FN
```

提交信息：

```text
feat(visualization): export paper-ready WSI figures
```

## 第 6 次提交：MPP 风险提示

```text
新增 build_mpp_warning
UI 状态栏或日志区提示
报告记录 warnings
```

提交信息：

```text
feat(ui): add MPP consistency warnings
```

---

# 最终验收清单

```text
[ ] 单张 WSI 可与医生 GeoJSON 标注计算 TP / FP / FN
[ ] 单张 WSI 可输出 Precision / Recall / F1 / AP50
[ ] 多张 WSI 可批量输出 eval_summary.csv
[ ] eval_summary.csv 可直接放入论文实验结果表
[ ] JSON 报告包含 WSI、MPP、模型、推理参数和评估结果
[ ] 报告命名统一为 AI辅助检测报告 / 病理图像辅助分析报告
[ ] 报告包含“不替代最终病理诊断”的免责声明
[ ] GeoJSON Polygon 转 bbox 的假设已写入文档
[ ] 可自动导出论文插图包
[ ] 可导出 FP / FN 样例用于误检漏检分析
[ ] MPP 或 metadata 缺失时 UI 和报告均有 warning
```