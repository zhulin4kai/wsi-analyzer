# AGENTS.md — WSIAnalyzer

## Run & build

```bash
python main.py              # run the app
python export_onnx.py       # convert .pt → .onnx (one-off, before packaging)
pyinstaller WSIAnalyzer.spec   # build distributable
```

There is **no** test framework, no linter config, and no typecheck step in this repo.

## Multi-process architecture (critical)

`main.py` runs a **Tkinter splash screen** in the main process, then spawns a **Qt subprocess** via `core/launcher/AppLauncher`. The subprocess loads PySide6, DB, and AI models. Communication is via `multiprocessing.Event` (ready signal) and `multiprocessing.Queue` (progress messages).

Do **not** call `sys.exit()` in the subprocess before `ready_event.set()` — the launcher will hang waiting.
`multiprocessing.freeze_support()` is required for Windows PyInstaller builds.

## Model inference path

- **Production (runtime)**: ONNX only. `torch`/`ultralytics`/`torchvision` are **excluded** from the PyInstaller build (see `.spec` `excludes`).
- **Development**: YOLO .pt via `ultralytics` works if installed, but the shipped app always uses ONNX.
- `ModelAdapterFactory` in `core/model_adapters.py` auto-selects the adapter by file extension.
- NMS is **not** baked into the ONNX graph (`nms=False` at export); `ai_engine.py` runs global NMS post-inference via `utils/nms.py`.

## Configuration

All settings live in `config.py` at the repo root. There are no `.env`, `.ini`, or YAML config files. Constants are grouped by subsystem (AI, HUD, heatmap, H/W tuning, etc.).

## Key architecture

| Directory | Role |
|---|---|
| `core/` | AI engine, model adapters, slide I/O, ROI logic, tile cache, launcher |
| `gui/` | PySide6 UI: `main_window.py` + `mixins/` + `widgets/` + `dialogs/` |
| `workers/` | QThread/QRunnable tasks: AI, gallery thumbnails, rendering, profiling |
| `utils/` | DB, hardware profiler, NMS, logging, schema DDL |

### MainWindow mixin pattern

`MainWindow` in `gui/main_window.py` uses **multiple inheritance** with mixins from `gui/mixins/`:
```python
class MainWindow(AnalysisMixin, FileHandlingMixin, QMainWindow):
```
Each mixin injects a functional area (file open/save, AI analysis trigger, heatmap, detection layer, toolbar). New features should follow this pattern.

### ImageServer / engine lifecycle

`core/image_server.py` provides `ImageServer` — a global singleton with an LRU `SlidePool`. External code must use:
```python
engine = server.acquire(path)   # refcount++
try: ... finally: server.release(engine)
```
Do **not** instantiate `WSIDataEngine` directly.

### Dual tile cache

- `TileLRUCache` (`core/tile_cache.py:8`) — stores `QGraphicsPixmapItem`, cleared on slide switch.
- `TileDataCache` (`core/tile_cache.py:67`) — stores decoded `QImage`, survives across slide switches to skip disk I/O.

### Database

SQLite at `data/wsi_data.db`, managed by `DatabaseManager` (singleton, `utils/db_manager.py`). WAL mode is enabled. Schema DDL is in `utils/db_schema.py`.

## PyInstaller quirks

- `sys.stdout`/`sys.stderr` can be `None` when running as a `console=False` EXE — `main.py:9-16` replaces them with `StringIO` to prevent `multiprocessing` crashes.
- `openslide_bin` DLLs are collected via `collect_all("openslide_bin")` in the `.spec`.
- `gui/mixins/*` and `gui/widgets/*` are listed as `hiddenimports` (dynamic import by name).

## File formats

Supported WSI formats: `.svs`, `.tif`, `.ndpi` (via OpenSlide).
Model formats: `.pt` (dev only), `.onnx` (runtime).
Export formats: CSV, JSON, GeoJSON.

## Input image conventions

- AI patch size defaults to 512×512 px at level 0. Patches are extracted as RGB PIL Images.
- Global NMS uses absolute physical coordinates (level-0 pixel space).
- Tissue mask is computed at `AI_MASK_TARGET_LEVEL` (default level 3) to skip background regions.

## Hardware auto-tuning

`HardwareProfiler` (`utils/hardware_profiler.py`) probes CUDA/MPS/CPU availability, VRAM, RAM, and disk I/O speed. It uses EMA-based heuristics to set `batch_size` and `stride` dynamically. CUDA OOM at runtime triggers automatic batch-size halving and retry.
