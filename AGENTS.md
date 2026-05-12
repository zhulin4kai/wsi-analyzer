# AGENTS.md — WSIAnalyzer

Behavioral guidelines for LLM coding agents. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

---

## Architecture

### Layer dependency direction (strict)

```
app/            → application/, infrastructure/
application/    → domain/, infrastructure/
infrastructure/ → domain/
domain/         → (no external deps — pure numpy/cv2/dataclasses)
workers/        → app/ (for DI), application/
ui/             → app/ (for DI), workers/
```

### Layer roles

| Directory | Role |
|---|---|
| `domain/` | Pure dataclasses + algorithms: coordinates, entities, detection, analysis, NMS, heatmap, fusion |
| `application/` | Orchestration: `FullSlideAnalysisService`, `AnalysisServiceFactory`, `AnalysisConfigResolver` |
| `infrastructure/` | Adapt to external systems: `ImageServer`, `OpenSlideEngine`, `BatchInferencer`, `ModelInspector`, `HardwareProfiler`, `DatabaseManager` |
| `ui/` | PySide6 GUI: `main_window.py`, `controllers/`, `layers/`, `widgets/`, `dialogs/`, `rendering/` |
| `workers/` | QThread thin adapters: `AIAnalysisWorker` (45 lines), `RenderWorker`, `GalleryWorker`, `ProfileWorker`, `PreloadTask` |
| `app/` | Entry points: `main.py` → `bootstrap.py` → `MainWindow`, `DependencyContainer`, `launcher/` |
| `config/` | Runtime constants (`config.py`) |
| `shared/` | Cross-layer utilities (`wsi_file_utils`, `drag_drop_mime`) |

### Key conventions

- **DI singleton**: `from wsi_analyzer.app.dependency_container import container` — the only global instance. Provides `container.database`, `container.image_server`, `container.analysis_service_factory`.
- **Public exports**: Every non-empty `__init__.py` has `__all__`. Import from package, not internal file.
- **No app/ imports from application/ or domain/** — this is a layering violation.
- **`AnalysisResult`** is a dataclass in `domain/analysis/result.py` with `.to_dict()`. UI/DB call `.to_dict()` only at the boundary.
- **`AnalysisResultBuilder`** returns `AnalysisResult` objects, never dicts.
- **Heatmap computation** is in `domain/detection/heatmap.py` (pure numpy/cv2). UI `HeatmapLayer` only handles `rgba → QPixmap`.
- **Model introspection** goes through `infrastructure/inference/model_inspector.py` — UI never imports ultralytics directly.
- **Protected members** (`_xxx`) should not be called across class boundaries. Use public equivalents.
- **PySide6, not PyQt5**: All Qt enums must use the PySide6 namespaced form. `Qt.AlignCenter` is wrong; `Qt.AlignmentFlag.AlignCenter` is correct. Every enum value lives under a named enum class. Before writing any Qt constant, verify the path with `python -c "from PySide6.QtCore import Qt; print(Qt.AlignmentFlag.AlignCenter)"`. If you are unsure, search the codebase for existing usages of the same enum.

### Critical files

| File | Purpose |
|---|---|
| `main.py` | Multiprocessing entry point (Tkinter splash → Qt main process) |
| `wsi_analyzer/app/bootstrap.py` | Qt event loop lifecycle, calls `container.image_server.shutdown()` on exit |
| `wsi_analyzer/app/dependency_container.py` | Global DI container (7-line singleton) |
| `wsi_analyzer/domain/analysis/result.py` | `AnalysisResult` dataclass — the result type flowing through the full pipeline |
| `wsi_analyzer/application/analysis/analysis_service.py` | `FullSlideAnalysisService.run()` — main inference orchestration |
| `wsi_analyzer/application/analysis/analysis_service_factory.py` | `AnalysisServiceFactory.create()` — assembles all dependencies |
| `wsi_analyzer/workers/ai_worker.py` | Thin Qt adapter (45 lines) — no configuration logic |
| `wsi_analyzer/ui/main_window.py` | Assembly only: creates widgets, controllers, docks, menu, signals |

## Tests

```
# Run all domain tests (38 tests, ~0.2s)
$env:PYTHONPATH = "."; python -m pytest tests/domain/ -q

# Compile check all files
python -m py_compile (list of changed .py files)
```

## graphify

Knowledge graph at `graphify-out/`. Rules:
- Before answering architecture questions, read `graphify-out/GRAPH_REPORT.md` for god nodes and community structure
- For cross-module queries: `graphify query "<question>"`, `graphify path "<A>" "<B>"`, `graphify explain "<concept>"`
- After modifying code files in a session, run `graphify update .` (AST-only, no API cost)
- Full pipeline: `/graphify .` (re-extracts AST + semantic, rebuilds HTML + report)

## Windows notes

- Shell: PowerShell 5.1. No `&&` chaining — use `; if ($?) { ... }` for sequential deps.
- Path quoting: always quote paths with spaces.
- UTF-8: use `$env:PYTHONUTF8 = "1"` before Python commands.
- Python: `D:/DevTools/Miniconda3/python.exe` (deduce from `graphify-out/.graphify_python` if exists, otherwise use the system default).
