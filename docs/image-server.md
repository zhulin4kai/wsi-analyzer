# ImageServer 架构说明

本文档描述 WSI 数据的统一访问层。重构后将原本散落在 UI、Worker 中的 OpenSlide 调用
全部收敛到 `infrastructure/imaging/` 目录下。

---

## 1. 问题背景

重构前, OpenSlide 引擎的职责分散在多个组件中:

| 职责 | 原位置 | 问题 |
|------|--------|------|
| 引擎生命周期 | `WSIView.load_wsi()` | UI 持有引擎, 切换切片时立即 close(), 后台 TileRenderTask 仍在 read_region(), 导致 use-after-free SEGFAULT |
| 瓦片渲染 | `RenderWorker` / `TileRenderTask` | 直接持有 WSIDataEngine 引用, 生命周期不受控 |
| 瓦片缓存 | `TileLRUCache` (WSIView 内) | 随切片切换清空, 切回旧切片需重新 I/O |
| 缩略图 | `ThumbnailWorker` | 在 SlidePool 外独立打开文件句柄 |
| RGB 采样 | `InfoBarOverlay._slide_engine` | HUD 组件直接持有引擎引用 |
| 元数据 | WSIView 各方法散落 | 每次切换重新读 C 层 |

---

## 2. 架构设计

```
infrastructure/imaging/
├── image_server.py              ImageServer (单例) -- 对外唯一入口
├── openslide_engine.py          OpenSlideEngine -- 封装一个 .svs 文件的所有操作
├── slide_pool.py                SlidePool -- 引用计数池, 防止 use-after-free
├── openslide_read_adapter.py    OpenSlideReadAdapter -- 实现 SlideReadPort 协议
├── tile_data_cache.py           TileDataCache -- 跨切片像素 LRU 缓存
├── patch_reader.py              PatchReader -- 按 PatchCoordinate 读图像块
├── thumbnail_worker.py          ThumbnailWorker -- 后台缩略图生成
└── __init__.py                  公开导出: ImageServer, PatchReader, OpenSlideReadAdapter

domain/slide/
├── coordinates.py               Level0Box, Level0Point, PatchCoordinate
├── metadata.py                  SlideMetadata (不可变元数据快照)
└── slide_read_port.py           SlideReadPort (抽象协议: read_region, level_0_dim, ...)
```

**调用关系:**

```
UI / Worker 层
    │
    ▼
container.image_server         (ImageServer 单例)
    ├── .acquire_engine(path)   → SlidePool 增加引用计数, 返回 OpenSlideEngine
    ├── .release_engine(path)   → SlidePool 减少引用计数, 归零后 LRU 驱逐
    ├── .get_metadata(path)     → 返回 SlideMetadata
    ├── .get_thumbnail(path)    → ThumbnailWorker 生成宏观缩略图
    ├── .get_tile(path, level, x, y) → TileDataCache 路由 + OpenSlideEngine.read_region()
    └── .sample_pixel(path, x, y)    → OpenSlideEngine 单像素采样
```

---

## 3. ImageServer 单例 + 生命周期

`ImageServer` 是项目级单例, 通过 `ImageServer.instance()` 获取 (也注册在 `container.image_server`)。
生命周期由 `app/bootstrap.py` 管理: 在 `app.exec()` 退出后调用 `container.image_server.shutdown()`,
遍历 `SlidePool` 中所有活跃引擎执行 `close()`, 确保文件句柄释放。

```python
# app/bootstrap.py 中唯一的 shutdown 调用点
exit_code = app.exec()
container.image_server.shutdown()  # 释放所有 OpenSlide 引擎
sys.exit(exit_code)
```

UI 层 (`MainWindow`) 不负责关闭 ImageServer。

---

## 4. SlidePool 引用计数驱逐机制

每个 WSI 文件在 `SlidePool` 中对应一个 `OpenSlideEngine` 实例。

```
引用计数规则:
  acquire_engine(path)  → refcount += 1
  release_engine(path)  → refcount -= 1
  当 refcount == 0 时, 引擎进入 "待关闭" 集合 (_pending_close)
  驱逐策略: LRU, 超过池容量上限时关闭最久未用的引擎
```

这确保了:
- 分析进行中 (AIAnalysisWorker 持有引擎引用, refcount >= 1) 时, 池不会驱逐该引擎
- 切换切片时, 旧引擎不会立即 close() (可能仍有后台渲染任务引用)
- 只有 refcount 归零且 LRU 超限时才真正 close()

---

## 5. OpenSlideEngine

封装单个 `.svs` 文件的所有读操作:

```python
class OpenSlideEngine:
    # 属性
    level_0_dim: tuple[int, int]      # Level-0 宽度和高度
    level_count: int                  # 金字塔层数
    level_dimensions: list[tuple]     # 每层的尺寸
    level_downsamples: list[float]    # 每层的下采样因子
    mpp: tuple[float, float] | None   # 微米/像素

    # 方法
    read_region(location, level, size)  # 读取任意层级任意区域
    get_best_level_for_mpp(target_mpp)  # 选择最接近目标 MPP 的层级
    get_best_level_for_downsample(ds)   # 选择最接近目标下采样因子的层级
    get_thumbnail(size)                 # 生成宏观缩略图
```

MPP 读取逻辑:
```python
mpp_x = float(slide.properties.get('openslide.mpp-x', 0))
mpp_y = float(slide.properties.get('openslide.mpp-y', 0))
if mpp_x > 0 and mpp_y > 0:
    return mpp_x, mpp_y
# 为 None 时, 依赖配置中的默认值 (如 2.0)
```

---

## 6. TileDataCache -- 跨切片像素缓存

与 `TileLRUCache` (视口缓存, 随切片切换清空) 不同, `TileDataCache` 是全局跨切片缓存:

```
TileDataCache:
  容量: 由 HardwareProfiler 根据系统 RAM 动态设定
  行为: 命中时直接返回 bytes, 无需二次 I/O
  驱逐: LRU
```

当用户频繁切换两个切片对比时, 第二次打开的切片无需重新从磁盘读取瓦片数据。

---

## 7. SlideReadPort 抽象 + OpenSlideReadAdapter

`SlideReadPort` (`domain/slide/slide_read_port.py`) 定义协议:

```python
class SlideReadPort(ABC):
    @abstractmethod
    def read_region(self, location, level, size): ...
    @abstractmethod
    def get_best_level_for_mpp(self, target_mpp): ...
    @property
    @abstractmethod
    def level_0_dim(self): ...
    @property
    @abstractmethod
    def level_downsamples(self): ...
```

`OpenSlideReadAdapter` (`infrastructure/imaging/openslide_read_adapter.py`) 实现该协议,
包装 `OpenSlideEngine`:

```python
class OpenSlideReadAdapter(SlideReadPort):
    def __init__(self, engine: OpenSlideEngine):
        self._engine = engine

    def read_region(self, location, level, size):
        return self._engine.read_region(location, level, size)

    @property
    def level_0_dim(self):
        return self._engine.level_0_dim
```

应用层 (`AnalysisCoordinateService`) 通过 `SlideReadPort` 接口访问, 不直接依赖 `OpenSlideEngine`。
这使得未来替换为 DICOM、TIFF 等后端时无需改动应用层。

---

## 8. PatchReader

`PatchReader` 将 `PatchCoordinate` 转换为具体的 `PIL.Image` 块:

```python
class PatchReader:
    def __init__(self, engine, target_level, target_downsample, patch_size):
        self._engine = engine
        self._target_level = target_level
        self._target_downsample = target_downsample
        self._patch_size = patch_size

    def read(self, coord: PatchCoordinate) -> Image.Image:
        # 1. 从引擎读取目标层级的 patch 区域
        region = self._engine.read_region(
            (coord.x, coord.y), coord.level, (self._patch_size, self._patch_size)
        )
        # 2. 如果层级不等于目标层级, 缩放至目标尺寸
        if coord.downsample != self._target_downsample:
            scale = coord.downsample / self._target_downsample
            new_size = int(self._patch_size * scale)
            region = region.resize((new_size, new_size), Image.Resampling.LANCZOS)
        # 3. 统一转 RGB
        return region.convert("RGB")
```

---

## 9. 相关文件索引

| 文件 | 职责 |
|------|------|
| `infrastructure/imaging/image_server.py` | 统一入口 + 生命周期管理 |
| `infrastructure/imaging/slide_pool.py` | 引用计数池 + LRU 驱逐 |
| `infrastructure/imaging/openslide_engine.py` | 单个 WSI 的全部只读操作 |
| `infrastructure/imaging/openslide_read_adapter.py` | SlideReadPort 实现 |
| `infrastructure/imaging/tile_data_cache.py` | 跨切片像素缓存 |
| `infrastructure/imaging/patch_reader.py` | PatchCoordinate → PIL.Image |
| `infrastructure/imaging/thumbnail_worker.py` | 后台缩略图 |
| `domain/slide/slide_read_port.py` | 抽象协议 |
| `domain/slide/metadata.py` | SlideMetadata 不可变快照 |
| `domain/slide/coordinates.py` | PatchCoordinate 坐标类型 |
| `app/bootstrap.py` | 唯一 shutdown 调用点 |
