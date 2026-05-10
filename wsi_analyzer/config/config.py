import os

# 渲染和交互时间配置(毫秒)
RENDER_DEBOUNCE_MS = 50
IDLE_THRESHOLD_MS = 100

# AI 预测框视觉配置
AI_PEN_COLOR = (0, 255, 0)
AI_PEN_WIDTH = 2

# 导入标注框视觉配置（与 AI 预测框区分）
IMPORTED_ANNOTATION_COLOR = (255, 200, 0)
IMPORTED_ANNOTATION_WIDTH = 2

# 硬件环境自适应与 AI 参数动态调优配置
SAFE_VRAM_MARGIN_MB = 500.0
MODEL_VRAM_OVERHEAD_MULTIPLIER = 2.5
VRAM_PER_TILE_MB = 8.0

IO_SPEED_NAS_USB2_MBPS = 10
IO_SPEED_SATA_SSD_MBPS = 30
IO_SPEED_NORMAL_SSD_MBPS = 80

# 硬件画像 EMA (指数移动平均) 进化系数
EMA_ALPHA_NEW = 0.3
EMA_ALPHA_OLD = 0.7

# 智能调优 (Auto-Tuning) 步长重叠率系数
AUTO_STRIDE_RATIO_HIGH = 0.5
AUTO_STRIDE_RATIO_MID = 0.75
AUTO_STRIDE_RATIO_LOW = 0.95

BATCH_SIZE_CAP_NAS_USB2 = 8
BATCH_SIZE_CAP_SATA_SSD = 16
BATCH_SIZE_CAP_NORMAL_SSD = 32
BATCH_SIZE_CAP_NVME_SSD = 64

RAM_THRESHOLD_SMALL_MB = 8192
RAM_THRESHOLD_NORMAL_MB = 16384

TILE_CACHE_LIMIT_SMALL = 100
TILE_CACHE_LIMIT_NORMAL = 300
TILE_CACHE_LIMIT_LARGE = 1000

# 数据库配置
DB_DIR = "../../data"
DB_FILE = os.path.join(DB_DIR, "wsi_data.db")
DB_DEFAULT_CAPACITY_MB = 150
DB_MIN_CAPACITY_MB = 50

# AI 推理与图像处理配置
AI_PATCH_SIZE = 512
AI_STRIDE = 400
AI_NMS_IOU_THRESH = 0.25
AI_CONF_THRESH = 0.5
AI_MASK_TARGET_LEVEL = 3
AI_MIN_AREA_RATIO = 0.001

# 模型训练时的目标物理分辨率（μm/px），用于自动匹配 WSI 金字塔层级
AI_MODEL_TARGET_MPP = 0.1725

# MPP ↔ 物镜倍率近似映射（μm/px），用于设置面板展示
AI_MAG_OPTIONS = {
    "1.25x": 8.0,
    "2.5x": 4.0,
    "5x": 2.0,
    "10x": 1.0,
    "20x": 0.5,
    "40x": 0.25,
    "自定义 (MPP)": None,
}

# AI 推理与图像处理安全边界配置
AI_PATCH_SIZE_MIN = 128
AI_PATCH_SIZE_MAX = 4096
AI_STRIDE_MIN = 64
AI_STRIDE_MAX = 4096
AI_NMS_IOU_THRESH_MIN = 0.01
AI_NMS_IOU_THRESH_MAX = 1.0
AI_CONF_THRESH_MIN = 0.01
AI_CONF_THRESH_MAX = 1.0
AI_MAX_PATCHES_LIMIT = 100000

# ROI 靶向分析专属配置
ROI_STRIDE_RATIO = 0.5

# HUD 叠加层视觉配置
# 颜色以 RGBA 元组存储，widget 文件中通过 QColor(*tuple) 构造
HUD_BG_COLOR = (20, 20, 20, 150)  # 半透明深色背景
HUD_FG_COLOR = (240, 240, 240, 255)  # 主要文字（亮白）
HUD_DIM_COLOR = (180, 180, 180, 255)  # 辅助文字（灰白）

# HUD 布局配置
HUD_PADDING = 10  # 控件内边距（像素）
HUD_MARGIN = 12  # 控件距视图边缘的外边距（像素）

# 比例尺（ScaleBarOverlay）配置
HUD_SCALE_BAR_TARGET_PX = 150  # 目标比例尺屏幕宽度（像素），取整后实际宽度会略有差异

# 坐标信息栏（InfoBarOverlay）配置
HUD_INFO_SWATCH_SIZE = 14  # RGB 预览色块边长（像素）
HUD_INFO_RGB_DEBOUNCE_MS = 150  # RGB 精确采样防抖延迟（毫秒）

# 工具栏放大倍率控件（MagnificationWidget）配置
HUD_MAG_MAX = 40.0  # 允许输入的最大放大倍率（×），对应 Level-0 原始分辨率
HUD_MAG_DEFAULT_OBJECTIVE = 40.0  # 切片无物镜元数据时使用的默认物镜倍率（×）
HUD_MAG_WIDGET_W = 100  # 控件宽度（像素）
HUD_MAG_WIDGET_H = 28  # 控件高度（像素）

# 图像列表（ImageListPanel）配置
IMAGE_LIST_THUMB_W = 80  # 列表项缩略图宽度（像素）
IMAGE_LIST_THUMB_H = 60  # 列表项缩略图高度（像素）

# 热力图叠加层视觉配置
HEATMAP_BIN_SIZE = 512  # 每个热力格子在 Level-0 的像素边长（建议与 AI_PATCH_SIZE 一致）
HEATMAP_ALPHA = 180  # 热力图最大不透明度（0-255），零值格子完全透明
HEATMAP_BLUR_SIGMA = (
    3.5  # 高斯模糊的 σ（格子单位），设为 0 可禁用模糊；检测稀疏时自动上调
)
HEATMAP_COLORMAP = (
    2  # cv2 伪彩色枚举值：2=JET(蓝→绿→黄→红), 11=HOT, 15=PLASMA, 16=VIRIDIS
)
HEATMAP_ALPHA_GAMMA = (
    2.0  # Alpha 幂函数指数：低值区骤降趋近 0，消除噪点底色；典型范围 1.5~2.5
)

HEATMAP_MINI_BLUR_SIGMA = (
    4.0  # 鹰眼图热力叠层 resize 后额外高斯扩散 σ（minimap 像素单位）
    # 使热点在缩略图上显示得更大；设为 0 可禁用；典型范围 2.0~6.0
)

# 热力图 LOD（缩放自适应）阈值——m11 即 viewer.transform().m11()
HEATMAP_LOD_MACRO_THRESH = 0.25  # 低于此值为宏观全片视野，热力图全不透明
HEATMAP_LOD_MID_THRESH = (
    0.5  # 低于此值为中等倍率，热力图半透明；高于此值为高倍率，热力图淡出
)

# 场景图层 Z-index 常量（由低到高：底图 → 瓦片 → 热力图 → 预测框 → ROI 框）
HEATMAP_Z_VALUE = 500  # 热力图层：叠于所有瓦片之上、预测框之下（瓦片最大 Z ≈ max_levels ≤ 15，取 500 留足余量）
AI_LAYER_Z_VALUE = (
    600  # ai_layer_group：修正原先 Z=0 被金字塔瓦片遮挡的问题（ROI 框仍在 1000）
)

# WSI 瓦片渲染配置
TILE_SIZE = 512  # 单个瓦片的像素尺寸（宽 = 高）
