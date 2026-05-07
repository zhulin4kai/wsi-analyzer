# OpenCode 重构任务清单：`main_window.py` 与 `wsi_view.py`

> 目标：把 `MainWindow` 和 `WSIView` 从“上帝类”重构为可维护、可扩展、职责清晰的企业级结构。  
> 原则：不追求临时修补，不做无意义格式化，不一次性重写全项目；按阶段拆分，每一阶段都必须保持功能可运行、行为可验证。

---

## 0. 当前问题概览

当前两个文件的主要问题不是“代码行数多”，而是职责边界混杂：

- `main_window.py` 同时负责主窗口装配、菜单创建、HUD 管理、鹰眼图管理、画廊导航、拖拽文件、图层初始化、报告导出、设置面板、ImageServer 生命周期关闭。
- `wsi_view.py` 同时负责 QGraphicsView 视图、交互事件、ROI 框选、拖拽遮罩、WSI 加载、缩略图加载、瓦片缓存、瓦片调度、后台渲染任务派发、QImage 到 QPixmapItem 的 scene 提交。
- `MainWindow` 直接调用 `WSIView` 的私有方法，例如 `_render_high_res_viewport()`、`_trigger_view_update()`，说明外部模块已经依赖了视图内部实现。
- `MainWindow._init_menu()` 依赖大量已初始化属性，例如 `image_list_panel`、`gallery`、`minimap`、`scale_bar`、`info_bar`、`mag_widget`、`btn_roi_analyze`、`chk_show_ai`、`chk_show_heatmap`，初始化顺序脆弱。
- `WSIView._request_high_res_render()` 过重，包含可见区域计算、level 选择、tile grid 计算、缓存查询、任务优先级计算、worker 派发等多个层次的逻辑。
- `WSIView.load_wsi()` 过重，包含切片切换准备、metadata 读取、scene 设置、缓存清理、thumbnail 加载、fit-to-window、状态激活、信号发射和高分辨率渲染触发。

重构后的方向：

- `MainWindow` 只做主窗口装配和顶层 signal wiring。
- `WSIView` 只做视图显示、视口状态暴露、交互入口和公开 API。
- 菜单、HUD、鹰眼图、拖拽、瓦片计算、瓦片渲染协调分别进入独立模块。
- 对外暴露稳定的公开方法，不允许外部继续调用 `_xxx` 私有方法。

---

## 1. 推荐目标结构

建议逐步演进到以下目录结构：

```text
src/
  gui/
    main_window.py
    main_menu.py

    controllers/
      hud_controller.py
      minimap_controller.py
      drag_drop_controller.py

    rendering/
      tile_grid.py
      tile_render_controller.py

    layers/
      layer_manager.py

    widgets/
      wsi_view.py
```

各模块职责如下：

```text
main_window.py
  只负责主窗口对象创建、核心组件装配、顶层信号连接、生命周期收尾。

main_menu.py
  只负责菜单栏、菜单 action、快捷键、菜单与 toolbar/dock/hud 控件的绑定。

controllers/hud_controller.py
  负责比例尺、坐标信息栏、放大倍率控件的创建、绑定、metadata 注入、resize 定位。

controllers/minimap_controller.py
  负责鹰眼图创建、大小档位、主视图联动、拖拽导航、菜单状态同步。

controllers/drag_drop_controller.py
  负责从 QMimeData 提取 WSI 路径、校验扩展名、处理拖拽状态。

rendering/tile_grid.py
  纯计算模块：根据 metadata、visible rect、scale 计算当前需要渲染的瓦片请求。
  不依赖 QGraphicsScene，不创建 QPixmap，不访问 worker。

rendering/tile_render_controller.py
  负责瓦片缓存查询、后台渲染任务派发、渲染版本控制。
  可在后续阶段引入，不建议第一步就做重。

layers/layer_manager.py
  负责 heatmap layer、AI prediction layer、imported annotation layer 的创建和可见性控制。
  注意：该模块会影响 AnalysisMixin / DetectionLayerMixin，建议放在后期。

widgets/wsi_view.py
  保留 QGraphicsView 视图职责，提供稳定公开 API，例如 load_wsi、navigate_to、focus_on、set_scale、reset_to_fit、request_render_now。
```

---

## 2. 重构原则

OpenCode 修改时必须遵守：

1. 每个阶段只做一个方向的重构，不混入无关优化。
2. 不做全项目格式化。
3. 不改变数据库 schema。
4. 不改变 AI 推理、检测框坐标、热力图逻辑，除非当前阶段明确要求。
5. 不改变现有公开行为：菜单、快捷键、拖拽、鹰眼图、HUD、WSI 加载、瓦片渲染必须保持可用。
6. 外部模块不得再调用 `WSIView` 的 `_xxx` 私有方法。
7. 能抽纯函数就优先抽纯函数，尤其是坐标计算和 tile grid 计算。
8. 每一阶段完成后都必须给出手动测试清单。

---

# Phase 1：建立 `WSIView` 公开导航 API，消除私有方法调用 ✅

## 目标

降低 `MainWindow` 对 `WSIView` 内部渲染实现的依赖。

当前 `MainWindow` 中存在类似调用：

```python
self.viewer._render_high_res_viewport()
self.viewer._trigger_view_update()
```

这类调用破坏封装。外部模块只应该表达“导航到某位置”“聚焦某病灶”“请求刷新视图”，而不应该知道 `WSIView` 内部如何触发高清渲染。

## 修改要求

在 `WSIView` 中新增公开方法：

```python
def request_render_now(self) -> None:
    """立即请求当前视口的高分辨率瓦片渲染。"""
    self._render_high_res_viewport()


def emit_view_rect_changed(self) -> None:
    """主动发射当前可见区域变化信号。"""
    self.view_rect_changed.emit(self.get_visible_rect())


def navigate_to(self, cx: float, cy: float, render: bool = True) -> None:
    """移动视图中心到指定 Level-0 坐标。"""
    if not self._current_path:
        return
    self.centerOn(cx, cy)
    if render:
        self.request_render_now()
    self.emit_view_rect_changed()


def focus_on(self, cx: float, cy: float, target_scale: float = 1.0) -> None:
    """聚焦到指定 Level-0 坐标，并切换到目标缩放倍率。"""
    if not self._current_path:
        return
    self.centerOn(cx, cy)
    self.set_scale(target_scale)
    self.request_render_now()
    self.emit_view_rect_changed()
```

然后替换 `main_window.py` 中对私有方法的调用。

## 示例替换

原来：

```python
def navigate_main_view(self, cx, cy):
    self.viewer.centerOn(cx, cy)
    self.viewer._render_high_res_viewport()
    self.viewer._trigger_view_update()
```

改为：

```python
def navigate_main_view(self, cx, cy):
    self.viewer.navigate_to(cx, cy, render=True)
```

原来：

```python
def _on_minimap_drag(self, cx, cy):
    self.viewer.centerOn(cx, cy)
    self.viewer._trigger_view_update()
```

改为：

```python
def _on_minimap_drag(self, cx, cy):
    self.viewer.navigate_to(cx, cy, render=False)
```

原来：

```python
def _navigate_to_lesion(self, cx, cy):
    self.viewer.centerOn(cx, cy)

    current_scale = self.viewer.transform().m11()
    target_scale = 1.0
    if current_scale < target_scale:
        factor = target_scale / current_scale
        self.viewer.scale(factor, factor)
    elif current_scale > target_scale:
        factor = target_scale / current_scale
        self.viewer.scale(factor, factor)

    if hasattr(self.viewer, "_render_high_res_viewport"):
        self.viewer._render_high_res_viewport()
    if hasattr(self.viewer, "_trigger_view_update"):
        self.viewer._trigger_view_update()
```

改为：

```python
def _navigate_to_lesion(self, cx, cy):
    self.viewer.focus_on(cx, cy, target_scale=1.0)
```

## 验证清单

- 打开 WSI 后，鹰眼图点击跳转正常。
- 鹰眼图拖拽时主视图跟随移动。
- 拖拽结束后高清瓦片正常加载。
- 点击病灶画廊条目后，主视图能定位到病灶中心。
- 不再有外部模块调用 `WSIView._render_high_res_viewport()` 或 `WSIView._trigger_view_update()`。

---

# Phase 2：抽离菜单构建逻辑到 `gui/main_menu.py` ✅

## 目标

把 `MainWindow._init_menu()` 从主窗口中移出。菜单构建是 UI 装配逻辑，不应该挤占主窗口主体。

## 修改要求

新增文件：

```text
gui/main_menu.py
```

新增类：

```python
from PySide6.QtGui import QAction, QActionGroup


class MainMenuBuilder:
    def __init__(self, window):
        self.window = window

    def build(self) -> None:
        self._build_file_menu()
        self._build_view_menu()
        self._build_analyze_menu()
        self._build_help_menu()

    def _build_file_menu(self) -> None:
        window = self.window
        file_menu = window.menuBar().addMenu("文件")

        open_action = file_menu.addAction("打开 WSI 文件")
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(window.open_file)

        add_action = file_menu.addAction("添加图像到列表")
        add_action.triggered.connect(window.add_images_to_list)

        # 后续把原 _init_menu() 中的文件菜单逻辑完整迁移到这里

    def _build_view_menu(self) -> None:
        window = self.window
        view_menu = window.menuBar().addMenu("视图")
        # 迁移视图菜单逻辑

    def _build_analyze_menu(self) -> None:
        window = self.window
        analyze_menu = window.menuBar().addMenu("分析")
        # 迁移分析菜单逻辑

    def _build_help_menu(self) -> None:
        window = self.window
        help_menu = window.menuBar().addMenu("帮助")
        # 迁移帮助菜单逻辑
```

`MainWindow.__init__()` 中改为：

```python
from gui.main_menu import MainMenuBuilder

...

self.menu_builder = MainMenuBuilder(self)
self.menu_builder.build()
```

## 注意事项

- 这一阶段只迁移菜单代码，不改变菜单行为。
- 所有 action 名称、快捷键、checkable 状态、signal 连接必须保持一致。
- `MainMenuBuilder` 可以暂时访问 `window` 的现有属性，例如 `window.minimap`、`window.gallery`、`window.btn_roi_analyze`。这是可接受的，因为本阶段目标是拆文件，而不是彻底解耦所有 UI 依赖。
- 不要在这个阶段修改 AI、WSI 加载、瓦片渲染逻辑。

## 验证清单

- 文件 → 打开 WSI 文件。
- 文件 → 添加图像到列表。
- 文件 → 导出 CSV / JSON / GeoJSON。
- 文件 → 导入标注。
- 文件 → 系统设置。
- 视图 → 放大、缩小、重置视图。
- 视图 → 面板 → 图像列表、病灶画廊。
- 视图 → 面板 → 鹰眼图显示/隐藏、大小切换。
- 视图 → 信息显示 → 比例尺、坐标信息、放大倍率。
- 分析 → 开始全片检测、ROI 分析、取消分析、清除结果、选择模型、显示预测框、显示热力图。
- 帮助 → 快捷键参考、关于系统。

---

# Phase 3：拆分 HUD 控制逻辑到 `HudController` ✅

## 目标

把比例尺、坐标信息栏、倍率控件的创建、绑定、metadata 注入和 resize 定位从 `MainWindow` 中移出。

## 新增文件

```text
gui/controllers/hud_controller.py
```

## 示例代码

```python
from config import HUD_MARGIN
from gui.widgets import InfoBarOverlay, ScaleBarOverlay


class HudController:
    def __init__(self, viewer, mag_widget):
        self.viewer = viewer
        self.mag_widget = mag_widget
        self.scale_bar = ScaleBarOverlay(viewer)
        self.info_bar = InfoBarOverlay(viewer)

    def bind(self) -> None:
        self.viewer.zoom_changed.connect(self.scale_bar.on_zoom_changed)
        self.viewer.mouse_scene_pos_changed.connect(self.info_bar.on_mouse_moved)
        self.viewer.zoom_changed.connect(self.mag_widget.on_zoom_changed)
        self.mag_widget.zoom_to_scale.connect(self.viewer.set_scale)

    def on_wsi_loaded(self, metadata) -> None:
        mpp = metadata.mpp
        mpp_x = mpp[0] if mpp else None
        mpp_y = mpp[1] if mpp else None

        self.scale_bar.load(mpp_x, mpp_y)
        self.info_bar.load(metadata)
        self.mag_widget.load(metadata.objective_power)

        current_scale = self.viewer.transform().m11()
        self.scale_bar.on_zoom_changed(current_scale)
        self.mag_widget.on_zoom_changed(current_scale)

        self.reposition()

    def reposition(self) -> None:
        vw = self.viewer.width()
        vh = self.viewer.height()
        margin = HUD_MARGIN

        self.scale_bar.move(margin, vh - self.scale_bar.height() - margin)
        self.info_bar.move(vw - self.info_bar.width() - margin, vh - self.info_bar.height() - margin)

    def set_scale_bar_visible(self, visible: bool) -> None:
        self.scale_bar.setVisible(visible)

    def set_info_bar_visible(self, visible: bool) -> None:
        self.info_bar.setVisible(visible)

    def set_magnification_visible(self, visible: bool) -> None:
        self.mag_widget.setVisible(visible)
```

`MainWindow` 中使用：

```python
from gui.controllers.hud_controller import HudController

...

self.hud = HudController(self.viewer, self.mag_widget)
self.hud.bind()
self.viewer.wsi_loaded.connect(self.hud.on_wsi_loaded)
```

`resizeEvent()` 改为：

```python
def resizeEvent(self, event):
    super().resizeEvent(event)
    if hasattr(self, "hud"):
        self.hud.reposition()
```

菜单中原来：

```python
scalebar_action.toggled.connect(self.scale_bar.setVisible)
infobar_action.toggled.connect(self.info_bar.setVisible)
mag_action.toggled.connect(self.mag_widget.setVisible)
```

改为：

```python
scalebar_action.toggled.connect(window.hud.set_scale_bar_visible)
infobar_action.toggled.connect(window.hud.set_info_bar_visible)
mag_action.toggled.connect(window.hud.set_magnification_visible)
```

## 验证清单

- WSI 加载后比例尺显示正确。
- 鼠标移动时坐标信息更新。
- 缩放时比例尺和倍率控件同步更新。
- 窗口 resize 后 HUD 仍在正确位置。
- 菜单开关可控制比例尺、坐标信息、放大倍率显示隐藏。

---

# Phase 4：拆分鹰眼图逻辑到 `MinimapController` ✅

## 目标

把鹰眼图创建、阴影、布局、导航、拖拽、大小切换从 `MainWindow` 中移出。

## 新增文件

```text
gui/controllers/minimap_controller.py
```

## 示例代码

```python
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QVBoxLayout

from gui.widgets import MinimapView


class MinimapController:
    SIZE_PRESETS = [
        (0.50, "小 50%"),
        (0.75, "中 75%"),
        (1.00, "大 100%"),
        (1.50, "特大 150%"),
    ]

    def __init__(self, viewer, parent=None):
        self.viewer = viewer
        self.parent = parent or viewer
        self.minimap = MinimapView(viewer)
        self._size_actions = []

    def setup(self) -> None:
        shadow = QGraphicsDropShadowEffect(self.parent)
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 100))
        shadow.setOffset(2, 2)
        self.minimap.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self.viewer)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.minimap, alignment=Qt.AlignTop | Qt.AlignRight)

        self.viewer.view_rect_changed.connect(self.minimap.update_indicator)
        self.minimap.navigate_requested.connect(self._navigate_main_view)
        self.minimap.navigate_drag_requested.connect(self._navigate_main_view_light)
        self.minimap.size_scale_changed.connect(self._sync_size_actions)

    def _navigate_main_view(self, cx, cy) -> None:
        self.viewer.navigate_to(cx, cy, render=True)

    def _navigate_main_view_light(self, cx, cy) -> None:
        self.viewer.navigate_to(cx, cy, render=False)

    def set_visible(self, visible: bool) -> None:
        self.minimap.setVisible(visible)

    def is_visible(self) -> bool:
        return self.minimap.isVisible()

    def set_size_scale(self, scale: float) -> None:
        self.minimap.set_size_scale(scale)

    def register_size_actions(self, actions) -> None:
        self._size_actions = list(actions)

    def _sync_size_actions(self, scale: float) -> None:
        for action in self._size_actions:
            value = action.data()
            if value is not None:
                action.setChecked(abs(float(value) - scale) < 1e-6)
```

菜单构建中使用：

```python
show_action.toggled.connect(window.minimap_controller.set_visible)

for scale, label in window.minimap_controller.SIZE_PRESETS:
    action = QAction(label, size_group)
    action.setCheckable(True)
    action.setData(scale)
    action.setChecked(scale == 1.0)
    action.triggered.connect(lambda checked, s=scale: window.minimap_controller.set_size_scale(s))
    size_menu.addAction(action)
    size_actions.append(action)

window.minimap_controller.register_size_actions(size_actions)
```

`MainWindow` 中：

```python
self.minimap_controller = MinimapController(self.viewer, self)
self.minimap_controller.setup()
```

## 验证清单

- 鹰眼图显示/隐藏正常。
- 鹰眼图点击导航正常。
- 鹰眼图拖拽导航不卡顿。
- 鹰眼图大小菜单 50% / 75% / 100% / 150% 正常。
- 菜单勾选状态与实际大小同步。

---

# Phase 5：抽离拖拽文件解析逻辑 ✅

## 目标

统一 WSI 文件路径解析，避免 `MainWindow` 和 `WSIView` 各自处理拖拽细节。

## 推荐结构

新增：

```text
gui/controllers/drag_drop_controller.py
```

或者更轻量：

```text
utils/wsi_file_utils.py
```

## 示例代码

```python
import os

WSI_EXTENSIONS = {".svs", ".tif", ".ndpi", ".ome.tif"}


def is_wsi_path(path: str) -> bool:
    full_lower = path.lower()
    return os.path.exists(path) and any(full_lower.endswith(ext) for ext in WSI_EXTENSIONS)


def extract_wsi_paths_from_mime(mime_data) -> list[str]:
    if not mime_data.hasUrls():
        return []

    paths = []
    for url in mime_data.urls():
        if not url.isLocalFile():
            continue
        path = url.toLocalFile()
        if is_wsi_path(path):
            paths.append(path)
    return paths
```

`MainWindow` 中使用：

```python
from utils.wsi_file_utils import extract_wsi_paths_from_mime


def _extract_wsi_paths(self, event) -> list[str]:
    return extract_wsi_paths_from_mime(event.mimeData())
```

## 后续优化方向

更彻底的企业级方案是：

- `WSIView` 不再把拖拽事件转发给 parent。
- `WSIView` 自己解析拖拽状态，但不加载文件。
- `WSIView` 只发信号：

```python
files_dropped = Signal(list)
drag_overlay_changed = Signal(bool)
```

然后 `MainWindow` 监听：

```python
self.viewer.files_dropped.connect(self._on_wsi_files_dropped)
self.viewer.drag_overlay_changed.connect(self.viewer.set_drag_overlay)
```

这个方向更干净，但涉及 `InteractionController` 的拖拽事件处理，建议放在后续阶段，不要和当前工具函数抽离混做。

## 验证清单

- 拖拽 `.svs` 文件到窗口可以加载。
- 拖拽 `.tif` / `.ndpi` / `.ome.tif` 可识别。
- 拖拽非 WSI 文件会被忽略。
- 多文件拖拽时可以加入图像列表并加载第一个。
- 拖拽悬停遮罩仍正常显示和隐藏。

---

# Phase 6：把 tile grid 计算抽成纯模块 ✅

## 目标

将 `WSIView._request_high_res_render()` 中的核心坐标计算抽成纯函数，方便测试和维护。

这是 `WSIView` 最关键的重构阶段之一。WSI 系统中最危险的问题是坐标错位，tile grid 计算必须可测试、可审查。

## 新增文件

```text
gui/rendering/tile_grid.py
```

## 示例代码

```python
import math
from dataclasses import dataclass
from PySide6.QtCore import QRectF


@dataclass(frozen=True)
class TileRequest:
    level: int
    col: int
    row: int
    x: int
    y: int
    width: int
    height: int
    scale: float
    priority: float


def compute_visible_tile_requests(
    metadata,
    visible_scene_rect: QRectF,
    scene_rect: QRectF,
    current_scale: float,
    tile_size: int = 512,
) -> list[TileRequest]:
    intersected_rect = visible_scene_rect.intersected(scene_rect)
    if intersected_rect.isEmpty() or current_scale <= 0:
        return []

    target_downsample = 1.0 / current_scale
    best_level = metadata.get_best_level_for_downsample(target_downsample)
    level_downsample = metadata.level_downsamples[best_level]
    level_dim = metadata.level_dimensions[best_level]

    start_col = int((intersected_rect.left() / level_downsample) // tile_size) - 1
    end_col = int((intersected_rect.right() / level_downsample) // tile_size) + 1
    start_row = int((intersected_rect.top() / level_downsample) // tile_size) - 1
    end_row = int((intersected_rect.bottom() / level_downsample) // tile_size) + 1

    max_col = (level_dim[0] - 1) // tile_size
    max_row = (level_dim[1] - 1) // tile_size

    start_col = max(0, min(start_col, max_col))
    end_col = max(0, min(end_col, max_col))
    start_row = max(0, min(start_row, max_row))
    end_row = max(0, min(end_row, max_row))

    viewport_center = visible_scene_rect.center()
    requests: list[TileRequest] = []

    for row in range(start_row, end_row + 1):
        for col in range(start_col, end_col + 1):
            abs_x = col * tile_size * level_downsample
            abs_y = row * tile_size * level_downsample

            tile_w = level_dim[0] - col * tile_size if col == max_col else tile_size
            tile_h = level_dim[1] - row * tile_size if row == max_row else tile_size

            tile_center_x = abs_x + tile_w * level_downsample * 0.5
            tile_center_y = abs_y + tile_h * level_downsample * 0.5
            dist = math.hypot(
                tile_center_x - viewport_center.x(),
                tile_center_y - viewport_center.y(),
            )
            priority = dist / max(level_downsample, 1e-6)

            requests.append(
                TileRequest(
                    level=best_level,
                    col=col,
                    row=row,
                    x=int(abs_x),
                    y=int(abs_y),
                    width=int(tile_w),
                    height=int(tile_h),
                    scale=level_downsample,
                    priority=priority,
                )
            )

    return requests
```

`WSIView._request_high_res_render()` 改成：

```python
from gui.rendering.tile_grid import compute_visible_tile_requests


def _request_high_res_render(self):
    def finish_interaction_early():
        self._interaction.mark_idle()

    if not self._current_path or not self._metadata:
        finish_interaction_early()
        return

    viewport_rect = self.viewport().rect()
    visible_scene_rect = self.mapToScene(viewport_rect).boundingRect()
    scene_rect = self.scene_canvas.sceneRect()

    requests = compute_visible_tile_requests(
        metadata=self._metadata,
        visible_scene_rect=visible_scene_rect,
        scene_rect=scene_rect,
        current_scale=self.transform().m11(),
        tile_size=TILE_SIZE,
    )

    if not requests:
        finish_interaction_early()
        return

    best_level = requests[0].level

    for key, item in self.tile_cache._cache.items():
        cached_level = key[0]
        item.setVisible(cached_level >= best_level)

    self.render_version += 1

    for req in requests:
        key = (req.level, req.col, req.row)

        cached_item = self.tile_cache.get(key)
        if cached_item:
            if not cached_item.scene():
                self.scene_canvas.addItem(cached_item)
            cached_item.setVisible(True)
            continue

        cached_qimg = ImageServer.instance().get_tile(
            self._current_path,
            req.level,
            req.col,
            req.row,
        )
        if cached_qimg is not None:
            self._add_tile_to_scene(
                cached_qimg,
                req.level,
                req.col,
                req.row,
                req.x,
                req.y,
                req.scale,
            )
            continue

        self.render_worker.request_render(
            self._current_path,
            req.level,
            req.col,
            req.row,
            req.x,
            req.y,
            req.width,
            req.height,
            req.scale,
            self.render_version,
            priority=req.priority,
        )

    finish_interaction_early()
```

## 单元测试建议

新增测试时可以使用 fake metadata：

```python
class FakeMetadata:
    level_downsamples = [1.0, 4.0, 16.0]
    level_dimensions = [(10000, 8000), (2500, 2000), (625, 500)]

    def get_best_level_for_downsample(self, target):
        if target < 4:
            return 0
        if target < 16:
            return 1
        return 2
```

测试点：

```python
def test_tile_requests_do_not_exceed_bounds():
    metadata = FakeMetadata()
    visible = QRectF(0, 0, 1000, 1000)
    scene = QRectF(0, 0, 10000, 8000)
    requests = compute_visible_tile_requests(metadata, visible, scene, current_scale=1.0)

    assert requests
    assert all(req.col >= 0 and req.row >= 0 for req in requests)
    assert all(req.width > 0 and req.height > 0 for req in requests)
```

## 验证清单

- 打开 WSI 后瓦片正常加载。
- 缩放时 level 切换正常。
- 拖拽视图时不会出现大片空白。
- 切片边缘瓦片不会越界。
- 快速缩放/拖拽时没有错图。
- 单元测试通过。

---

# Phase 7：函数级拆分 `WSIView.load_wsi()`

## 目标

不改变行为，只把 `load_wsi()` 拆成多个小函数，提高可读性和可维护性。

## 示例结构

```python
def load_wsi(self, file_path: str) -> None:
    self._prepare_for_slide_switch()

    metadata = self._load_slide_metadata(file_path)
    if metadata is None:
        return

    self._setup_scene_for_metadata(metadata)
    self._clear_tile_items()
    self._load_background_thumbnail(file_path)
    self._fit_slide_to_view(metadata)
    self._activate_slide(file_path, metadata)
```

对应私有方法：

```python
def _prepare_for_slide_switch(self) -> None:
    self.render_timer.stop()
    self.render_version += 1000
    self.render_worker.set_version(self.render_version)
    self.render_worker.stop()

    self._current_path = None
    self._metadata = None
    self._update_placeholder_visibility()


def _load_slide_metadata(self, file_path: str):
    try:
        return ImageServer.instance().get_metadata(file_path)
    except Exception as e:
        QMessageBox.critical(self, "错误", f"无法打开文件:\n{e}")
        return None


def _setup_scene_for_metadata(self, metadata) -> None:
    w, h = metadata.level_0_dim
    self.scene_canvas.setSceneRect(0, 0, w, h)
    self.resetTransform()


def _clear_tile_items(self) -> None:
    old_items = self.tile_cache.clear()
    for item in old_items:
        if item.scene():
            self.scene_canvas.removeItem(item)


def _load_background_thumbnail(self, file_path: str) -> None:
    try:
        thumb_img, downsample_factor = ImageServer.instance().get_thumbnail(
            file_path,
            level_from_last=2,
        )
        self.bg_layer_item.setPixmap(QPixmap.fromImage(ImageQt(thumb_img)))
        self.bg_layer_item.setScale(downsample_factor)
    except Exception as e:
        logger.error(f"宏观底图加载失败: {e}")


def _fit_slide_to_view(self, metadata) -> None:
    w, h = metadata.level_0_dim
    view_rect = self.viewport().rect()
    scale_w = view_rect.width() / w
    scale_h = view_rect.height() / h
    initial_scale = min(scale_w, scale_h) * 0.95
    self.scale(initial_scale, initial_scale)


def _activate_slide(self, file_path: str, metadata) -> None:
    self._current_path = file_path
    self._metadata = metadata
    self._update_placeholder_visibility()

    self.zoom_changed.emit(self.transform().m11())
    self.request_render_now()
    self.wsi_loaded.emit(metadata)
```

## 注意事项

- 保持 `render_version += 1000` 的逻辑不变。
- 保持 `render_worker.set_version()` 和 `render_worker.stop()` 语义不变。
- 保持切片切换时清理 `tile_cache` 的行为。
- 保持跨切片 `ImageServer` tile data cache 不清理的行为。
- 保持 `wsi_loaded.emit(metadata)` 的时机：必须在新切片状态激活并触发首轮渲染之后。

## 验证清单

- 打开正常 WSI 成功。
- 打开损坏/不存在 WSI 时有错误提示。
- 切换 WSI 时旧瓦片不会残留。
- thumbnail 底图正常显示。
- 初始 fit-to-window 正常。
- `wsi_loaded` 后 HUD、鹰眼图、相邻切片预热仍正常。

---

# Phase 8：引入 `LayerManager` 管理图层

## 目标

把 heatmap、AI prediction、imported annotation 三类图层从 `MainWindow` 中抽离出来。

这一阶段会影响 `AnalysisMixin`、`DetectionLayerMixin`、`HeatmapMixin` 等模块，因此建议放在后面做。

## 新增文件

```text
gui/layers/layer_manager.py
```

## 示例代码

```python
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGraphicsItemGroup, QGraphicsPixmapItem

from config import AI_LAYER_Z_VALUE, HEATMAP_Z_VALUE


class LayerManager:
    def __init__(self, scene):
        self.scene = scene

        self.heatmap_layer_item = QGraphicsPixmapItem()
        self.heatmap_layer_item.setZValue(HEATMAP_Z_VALUE)
        self.heatmap_layer_item.setTransformationMode(Qt.SmoothTransformation)
        self.scene.addItem(self.heatmap_layer_item)

        self.ai_layer_group = QGraphicsItemGroup()
        self.ai_layer_group.setZValue(AI_LAYER_Z_VALUE)
        self.scene.addItem(self.ai_layer_group)

        self.imported_layer_group = QGraphicsItemGroup()
        self.imported_layer_group.setZValue(AI_LAYER_Z_VALUE + 10)
        self.scene.addItem(self.imported_layer_group)

    def set_ai_visible(self, visible: bool) -> None:
        self.ai_layer_group.setVisible(visible)
        self.imported_layer_group.setVisible(visible)

    def set_heatmap_visible(self, visible: bool) -> None:
        self.heatmap_layer_item.setVisible(visible)

    def clear_ai_items(self) -> None:
        for item in list(self.ai_layer_group.childItems()):
            self.ai_layer_group.removeFromGroup(item)
            self.scene.removeItem(item)

    def clear_imported_items(self) -> None:
        for item in list(self.imported_layer_group.childItems()):
            self.imported_layer_group.removeFromGroup(item)
            self.scene.removeItem(item)

    def clear_heatmap(self) -> None:
        self.heatmap_layer_item.setPixmap(None)
```

为了兼容现有 mixin，第一步可以在 `MainWindow` 中保留旧属性引用：

```python
self.layers = LayerManager(self.viewer.scene_canvas)

# 兼容旧 mixin，后续再逐步替换为 self.layers.xxx
self.heatmap_layer_item = self.layers.heatmap_layer_item
self.ai_layer_group = self.layers.ai_layer_group
self.imported_layer_group = self.layers.imported_layer_group
```

## 验证清单

- 全片检测后预测框正常显示。
- 导入 GeoJSON 标注后标注层正常显示。
- 热力图显示/隐藏正常。
- 清除分析结果后图层清空。
- 重新打开 WSI 后旧图层不残留。

---

# Phase 9：后续可选：引入 `TileRenderController`

## 目标

当 `tile_grid.py` 稳定后，可以进一步把缓存查询、worker 派发、render_version 管理从 `WSIView` 中抽离到 `TileRenderController`。

但这一步风险高于 `tile_grid.py`，不建议过早执行。

## 推荐接口草案

```python
class TileRenderController:
    def __init__(self, image_server, render_worker, tile_cache, tile_size=512):
        self.image_server = image_server
        self.render_worker = render_worker
        self.tile_cache = tile_cache
        self.tile_size = tile_size
        self.render_version = 0

    def invalidate(self) -> None:
        self.render_version += 1000
        self.render_worker.set_version(self.render_version)
        self.render_worker.stop()

    def request_tiles(self, path, metadata, visible_scene_rect, scene_rect, current_scale):
        ...
```

这个阶段需要非常谨慎，因为它涉及：

- render version 是否正确淘汰旧任务；
- 切片切换时 queued tasks 是否清理；
- late image_ready 是否被丢弃；
- tile cache 和 scene item 生命周期是否一致。

建议只有在 Phase 6 和 Phase 7 稳定之后再做。

---

# 推荐执行顺序

最终推荐顺序如下：

```text
Phase 1  公开 WSIView 导航 API，消除私有方法调用  ✅
Phase 2  抽离 MainMenuBuilder  ✅
Phase 3  抽离 HudController  ✅
Phase 4  抽离 MinimapController  ✅
Phase 5  抽离拖拽文件解析工具  ✅
Phase 6  抽离 tile_grid 纯计算模块  ✅
Phase 7  函数级拆分 WSIView.load_wsi  ✅
Phase 8  引入 LayerManager
Phase 9  可选：引入 TileRenderController
```

为什么是这个顺序：

- Phase 1 先建立公开 API，后续 controller 才能依赖稳定接口。
- Phase 2、3、4 都是 UI 结构拆分，风险较低，收益明显。
- Phase 5 解决拖拽逻辑分散问题，但避免过早改事件链。
- Phase 6 开始触碰 WSI 坐标和瓦片计算，需要前面先稳定外部结构。
- Phase 7 拆 `load_wsi()`，只改变函数结构，不改变行为。
- Phase 8 会影响 AI/Heatmap/Detection mixin，因此放后面。
- Phase 9 涉及渲染调度核心，只有在 tile grid 可测试后才建议执行。

---

# 给 OpenCode 的总提示词

可以把下面这段直接交给 OpenCode，要求它按阶段执行，不要一次完成所有阶段。

```text
请根据 opencode_wsi_mainwindow_refactor_plan.md 对 main_window.py 和 wsi_view.py 做企业级可维护性重构。

总体目标：
- MainWindow 只保留主窗口装配和顶层信号连接；
- WSIView 只保留视图职责和稳定公开 API；
- 菜单、HUD、鹰眼图、拖拽解析、瓦片计算、图层管理逐步拆分；
- 不做临时补丁，不做无关格式化，不一次性重写全项目。

执行规则：
1. 严格按文档 Phase 顺序执行。
2. 每次只执行一个 Phase。
3. 每个 Phase 修改前先给计划。
4. 修改后列出改动文件、行为是否改变、风险点和手动测试步骤。
5. 不修改 AI 推理、数据库 schema、YOLO 坐标逻辑，除非当前 Phase 明确要求。
6. 不允许外部模块继续调用 WSIView 的 _xxx 私有方法。
7. 如果发现某个 Phase 会影响 AnalysisMixin / DetectionLayerMixin / HeatmapMixin，先停止并说明影响范围，不要擅自大改。

请先执行 Phase 1。
```

---

# 每个阶段完成后的统一检查项

每个阶段结束后都要至少检查：

```text
1. 应用能否启动。
2. 能否打开一张 WSI。
3. 初始缩放是否 fit-to-window。
4. 鼠标缩放、拖拽是否正常。
5. 瓦片是否正常加载。
6. 鹰眼图是否正常联动。
7. HUD 是否正常更新。
8. ROI 模式是否还能启用。
9. 已有 AI 分析按钮是否还能触发。
10. 控制台是否出现新的异常或 Qt warning。
```

---

# 最终验收标准

重构完成后，应满足：

- `main_window.py` 不再包含大段菜单构建代码。
- `main_window.py` 不再直接管理 HUD 内部细节。
- `main_window.py` 不再直接管理鹰眼图内部导航细节。
- `main_window.py` 不再调用 `WSIView._xxx` 私有方法。
- `wsi_view.py` 中 `load_wsi()` 被拆成清晰的小函数。
- `wsi_view.py` 中 tile grid 坐标计算被抽成可测试模块。
- WSIView 对外暴露稳定公开方法：`navigate_to()`、`focus_on()`、`request_render_now()`、`emit_view_rect_changed()`。
- 菜单、HUD、鹰眼图、拖拽、瓦片计算模块职责清晰。
- 行为保持一致：WSI 加载、缩放、拖拽、瓦片渲染、HUD、鹰眼图、ROI、AI 图层不应被破坏。
