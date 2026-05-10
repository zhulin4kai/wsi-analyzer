# UI 架构说明

本文档描述 PySide6 界面的组织结构: 初始化顺序、各 Controller 职责、图层系统、信号流。

---

## 1. MainWindow 初始化顺序

`MainWindow.__init__()` 按照严格的依赖顺序装配组件。
后续组件可用前面已初始化的属性, 不可反向引用。

```
1. View + Layers (无依赖)
   ├── WSIView (QGraphicsView, 中央部件)
   └── LayerManager
         ├── HeatmapLayer (热力图, Z=500)
         ├── DetectionLayer (AI 检测框, Z=600)
         └── AnnotationLayer (导入标注, Z=610)

2. Dock Widgets (需要 viewer)
   ├── ImageListPanel (左侧, 切片列表)
   └── LesionGallery (右侧, 病灶画廊)

3. Toolbar Widgets (无控制器信号)
   ├── MagnificationWidget
   ├── 按钮: 选择模型 / 全片检测 / ROI 分析
   ├── 勾选: 预测框 / 热力图
   └── 导出按钮

4. Controllers (通过构造函数接收 window + viewer + widgets 引用)
   ├── MinimapController
   ├── SlideController
   ├── AnalysisResultController
   ├── AnalysisController
   └── ModelController

5. Signal Connections (控制器已存在)
   ├── toolbar buttons → controller methods
   └── dock widgets → controller methods

6. HUD + Heatmap (需要 toolbar 的 mag_widget)
   ├── HudController → ScaleBarOverlay + InfoBarOverlay
   └── HeatmapController → chk_show_heatmap

7. Menu (需要所有控制器和 widget 引用)
   └── MainMenuBuilder

8. View Signals (viewer 发射的信号 → controller 槽函数)
   ├── interaction_started → AnalysisResultController.on_interaction_start
   ├── interaction_finished → AnalysisResultController.on_interaction_finish
   ├── roi_drawn → AnalysisController.start_roi_analysis
   └── wsi_loaded → MainWindow._on_wsi_loaded
```

---

## 2. Controller 层

每个 Controller 通过构造函数接收它需要的对象引用 (`window`, `viewer`, `layers`, 特定 widget)。
Controller 之间通过 `self._window.xxx_controller.method()` 互相调用, 不通过信号。

### 2.1 AnalysisController

```
ui/controllers/
├── analysis_controller.py         AnalysisController (全片/ROI 分析启停)
    __init__(window, viewer, slide_controller, result_controller)
    start_ai_analysis()            → 检查模型和切片, 创建 QProgressDialog, 启动 AIAnalysisWorker
    start_roi_analysis(roi_coords) → 同上, 限定 ROI 范围
    toggle_roi_mode(checked)       → viewer.toggle_roi_mode()
    cancel_ai_analysis()           → 确认后 worker.cancel()
    handle_ai_error(err_msg)       → close progress, 弹出错误对话框
    _on_roi_finished(result)       → 接收 AnalysisResult, 调用 result_controller.merge_and_commit()
    close_progress_dialog()        → 安全关闭进度框
```

关键信号连接 (`start_ai_analysis()` 中):
```
worker.progress_updated → progress_dialog.setValue      (百分比 0-100)
worker.status_updated   → statusBar().showMessage       (阶段文字)
worker.analysis_finished → result_controller.render_ai_results   (结果渲染)
worker.error_occurred   → handle_ai_error               (错误提示)
worker.finished         → btn_analyze.setEnabled(True)  (恢复按钮)
```

### 2.2 AnalysisResultController

```
analysis_result_controller.py     AnalysisResultController
    __init__(window, viewer, layers, gallery, btn_export, chk_show_ai)
    render_ai_results(result)      → 接收 AnalysisResult, 调用 _commit_results
    _commit_results(result)        → 绘制框 + 保存 DB + 加载画廊
    merge_and_commit(new, existing, total, processed) → 调用 fuse_results + _commit_results
    _draw_ai_boxes(results)        → layers.detection.render(results)
    import_annotations()           → 文件对话框 → layers.annotation.render()
    clear_ai_results()             → layers.clear_ai_items() + gallery 清空
    toggle_ai_visibility(checked)  → layers.set_ai_visible(checked)
```

### 2.3 其余 Controller 速览

```
slide_controller.py         SlideController     -- 打开/切换切片, 缓存回放
model_controller.py         ModelController     -- 选择模型权重, auto-tune 触发
heatmap_controller.py       HeatmapController   -- 热力图工具栏 + LOD 透明度 + minimap 同步
minimap_controller.py       MinimapController   -- 鹰眼图尺寸 + 可见性控制
hud_controller.py           HudController       -- 比例尺 + 信息栏 + 放大倍率
```

---

## 3. Layer 系统

### 3.1 文件关系

```
ui/layers/
├── _base.py                 make_rect_item(data, color, width, tooltip)  共享函数
├── detection_layer.py       DetectionLayer      -- AI 检测框 (蓝色)
├── annotation_layer.py      AnnotationLayer     -- 导入标注框 (其他颜色)
├── heatmap_layer.py         HeatmapLayer        -- 热力图 QPixmap
├── layer_manager.py         LayerManager        -- 组合三者 + Z-index 管理
└── __init__.py              公开导出
```

### 3.2 Design

每个 Layer 封装一个 `QGraphicsItemGroup` (或 `QGraphicsPixmapItem`):

```python
class DetectionLayer:
    def __init__(self, group, scene):
        self._group = group    # QGraphicsItemGroup (scene 已 addItem)
        self._scene = scene

    def render(self, results):  # results = [{"bbox": [...], "confidence": ..., "class_id": ...}, ...]
        self.clear()
        for data in results:
            rect = make_rect_item(data, AI_PEN_COLOR, AI_PEN_WIDTH, tooltip)
            self._group.addToGroup(rect)

    def clear(self):
        for item in self._group.childItems():
            self._group.removeFromGroup(item)
            self._scene.removeItem(item)

    def set_visible(self, visible):
        self._group.setVisible(visible)
```

`LayerManager` 组合三个 Layer 并管理 Z-index:

```python
class LayerManager:
    def __init__(self, scene):
        self.heatmap    = HeatmapLayer(item)         # Z=500
        self.detection  = DetectionLayer(ai_group, scene)   # Z=600
        self.annotation = AnnotationLayer(imported_group, scene)  # Z=610

    def set_ai_visible(self, visible):   # 同时控制 detection + annotation
    def clear_ai_items(self):           # 同时清除 detection + annotation
```

热力图计算 (`compute_heatmap_grid` + `grid_to_rgba`) 已下沉到 `domain/detection/heatmap.py`。
`HeatmapLayer` 只负责将 `rgba` np.ndarray 转换为 `QPixmap` 并设置到场景上。

---

## 4. Widget 层

### 4.1 WSIView -- 核心视图

```
ui/widgets/wsi_view.py    WSIView (QGraphicsView)
    职责:
      - 加载/切换切片 (load_wsi)
      - 瓦片渲染调度 (TileRenderController)
      - ROI 框选 (InteractionController)
      - 拖拽支持 (set_drag_overlay)
    信号:
      wsi_loaded(metadata)
      zoom_changed(scale)
      interaction_started / interaction_finished
      roi_drawn(roi_coords)
    方法:
      navigate_to(cx, cy, scale)    -- 导航到指定 Level-0 坐标
      focus_on(cx, cy, target_scale) -- 聚焦并触发高清渲染
      request_render_now()           -- 立即触发一次瓦片渲染
```

### 4.2 其他 Widget 速览

```
image_list_panel.py         ImageListPanel   -- 左侧 Dock, 管理多个 WSI 文件
lesion_gallery.py           LesionGallery    -- 右侧 Dock, 展示 Top-K 病灶缩略图
interaction_controller.py   InteractionController -- 鼠标/滚轮/拖拽事件处理
minimap_view.py             MinMapView       -- 鹰眼图 (QGraphicsView 子类)
info_bar_overlay.py         InfoBarOverlay   -- 鼠标坐标 + RGB 像素采样
scale_bar_overlay.py        ScaleBarOverlay  -- 左下角比例尺 (um)
magnification_widget.py     MagnificationWidget -- 放大倍率显示 (可双击编辑)
roi_box_item.py             ROIBoxItem       -- ROI 矩形框图形项
report_exporter.py          ReportExporter   -- CSV/JSON/GeoJSON 导出
```

---

## 5. Rendering 子层

```
ui/rendering/
  tile_grid.py             compute_visible_tile_requests() -- 纯计算 (无 Qt 依赖)
  tile_render_controller.py  TileRenderController -- 渲染版本管理 + worker 调度
  tile_scene_cache.py        TileSceneCache -- QGraphicsPixmapItem 对象复用
```

**瓦片渲染流程:**

```
WSIView.paintEvent()
    │
    ▼
TileRenderController.render()
    │  1. 通过 compute_visible_tile_requests() 计算当前视口需要的瓦片列表
    │  2. 对比 render_version 判断是否需要重绘
    │  3. 分发到 RenderWorker (QThread) 异步渲染
    ▼
RenderWorker
    │  container.image_server.get_tile(path, level, x, y)
    ▼
TileSceneCache
    │  复用 QGraphicsPixmapItem 对象, 减少内存分配
    ▼
WSIView.scene_canvas.addItem(pixmap_item)
```

---

## 6. Worker 层

所有 Worker 都是 QThread 或 QRunnable 子类, 仅做信号桥接, 不包含配置决策逻辑:

```
workers/
  ai_worker.py          AIAnalysisWorker      -- factory.create() + service.run() (45 行)
  render_worker.py      RenderWorker          -- ImageServer 异步瓦片渲染
  gallery_worker.py     GalleryWorker         -- 病灶缩略图截取 + ImageQt 转换
  profile_worker.py     ProfileWorker         -- 硬件 I/O 测速
  preload_task.py       PreloadTask (QRunnable) -- 引擎预热
  thumbnail_worker.py   ThumbnailWorker       -- 宏观缩略图生成
```

---

## 7. 关键信号流

### 7.1 分析完成 → 结果显示

```
AIAnalysisWorker.analysis_finished (AnalysisResult)
    → AnalysisResultController.render_ai_results()
        → _commit_results()
            → _draw_ai_boxes()             # DetectionLayer.render()
            → heatmap_controller.update_heatmap_layer()  # HeatmapLayer.render()
            → gallery.load_results()       # 病灶缩略图
            → analysis_repository.save_analysis()  # SQLite 持久化
            → QMessageBox.information()    # 提示完成/中止
```

### 7.2 缩放 → 瓦片刷新 + LOD 热力图

```
WSIView.zoom_changed(scale)
    ├── TileRenderController.invalidate() → 版本号 +1 → 触发重绘
    ├── HeatmapController._on_zoom_changed_lod(scale) → 热力图透明度调整
    ├── MagnificationWidget.on_zoom_changed(scale) → 倍率显示更新
    └── ScaleBarOverlay.on_zoom_changed(scale) → 比例尺更新
```

### 7.3 切片加载 → 缓存检查

```
SlideController._do_load(file_path)
    ├── _pre_switch_cleanup()            # layers.clear_ai_items(), 清空结果
    ├── _activate_slide(file_path)       # viewer.load_wsi(), minimap.load_minimap()
    └── _post_switch_tasks(file_path)    # 检查 SQLite 缓存, 有则 AnalysisResult.from_cache()
        │
        └── (有缓存) → result_controller.render_ai_results(AnalysisResult)
```

---

## 8. 相关文件索引

| 文件 | 用途 |
|------|------|
| `ui/main_window.py` | 主窗口, 纯装配 (182 行) |
| `ui/controllers/` | 6 个 Controller |
| `ui/layers/layer_manager.py` | Layer 组合 + Z-index |
| `ui/layers/detection_layer.py` | AI 检测框绘制 |
| `ui/layers/heatmap_layer.py` | 热力图 QPixmap 渲染 (55 行) |
| `ui/widgets/wsi_view.py` | 核心 QGraphicsView |
| `ui/rendering/tile_render_controller.py` | 瓦片渲染调度 |
| `ui/main_menu.py` | MainMenuBuilder |
| `workers/ai_worker.py` | AI 推理 Qt 适配器 (45 行) |
