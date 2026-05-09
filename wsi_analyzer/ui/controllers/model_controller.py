import os

from PySide6.QtWidgets import QFileDialog

from wsi_analyzer.app.dependency_container import container
from wsi_analyzer.infrastructure.hardware import HardwareProfiler


class ModelController:
    def __init__(self, window):
        self._window = window

    def select_model(self):
        w = self._window
        file_path, _ = QFileDialog.getOpenFileName(
            w, "选择 AI 模型", "", "Model Files (*.pt *.pth)"
        )
        if not file_path:
            return

        w.current_model_path = file_path
        w.btn_sel_model.setText(f"模型: {os.path.basename(file_path)}")

        db = container.database
        if db.get_auto_tune_enabled() and file_path.endswith(".pt"):
            self._auto_tune_from_yolo(file_path, db)
        if w.current_wsi_path:
            self._update_profile_for_model(file_path, db)

    def _auto_tune_from_yolo(self, file_path: str, db):
        w = self._window
        try:
            from ultralytics import YOLO
            model = YOLO(file_path)
            imgsz = model.model.args.get("imgsz")
            if isinstance(imgsz, int):
                db.set_setting("ai_patch_size", imgsz)
                w.statusBar().showMessage(
                    f"智能调优: 已根据 YOLO 模型设置 Patch Size = {imgsz}"
                )
        except ImportError:
            w.statusBar().showMessage(
                "提示: 当前环境未安装 ultralytics，无法从 .pt 文件读取模型参数。"
            )
        except Exception:
            pass

    def _update_profile_for_model(self, file_path: str, db):
        w = self._window
        drive_prefix = HardwareProfiler.get_storage_key(w.current_wsi_path)
        profile = db.get_system_profile(drive_prefix)
        if not (profile and "io_speed" in profile):
            return

        model_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        device = profile.get("device", HardwareProfiler.get_compute_device())
        _, free_vram = HardwareProfiler.get_vram_info(device)
        new_params = HardwareProfiler.calculate_optimal_params(
            profile["io_speed"], free_vram, model_size_mb
        )
        profile["batch_size"] = new_params["batch_size"]
        profile["tile_cache_limit"] = new_params["tile_cache_limit"]
        db.save_system_profile(drive_prefix, profile)

        w.statusBar().showMessage(
            f"模型已切换: {os.path.basename(file_path)} | "
            f"模型大小: {model_size_mb:.1f}MB | "
            f"自动调整 Batch Size 至: {new_params['batch_size']}"
        )
