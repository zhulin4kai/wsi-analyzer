import os

from PySide6.QtWidgets import QFileDialog, QMessageBox

from wsi_analyzer.app.dependency_container import container
from wsi_analyzer.infrastructure.hardware import HardwareProfiler


class SlideController:
    def __init__(self, window, viewer, minimap, image_list_panel):
        self._window = window
        self._viewer = viewer
        self._minimap = minimap
        self._image_list_panel = image_list_panel
        self._is_loading_wsi = False
        self._profile_worker = None
        self.current_wsi_path = None

    # ── public ─────────────────────────────────────────────────────

    def open_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self._window, "选择病理切片", "", "WSI Files (*.svs *.tif *.ndpi)"
        )
        if file_path:
            self._load_wsi_at_path(file_path)
            if self._image_list_panel:
                self._image_list_panel.add_image(file_path)

    def add_images_to_list(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self._window, "批量添加图像", "", "WSI Files (*.svs *.tif *.ndpi)"
        )
        if paths and self._image_list_panel:
            self._image_list_panel.add_images(paths)

    def _load_wsi_at_path(self, file_path):
        if self._is_loading_wsi:
            return
        self._is_loading_wsi = True
        try:
            self._do_load(file_path)
        finally:
            self._is_loading_wsi = False

    # ── internal ───────────────────────────────────────────────────

    def _do_load(self, file_path):
        self._pre_switch_cleanup()
        self._activate_slide(file_path)
        self._post_switch_tasks(file_path)

    def _pre_switch_cleanup(self):
        w = self._window
        if hasattr(w, "layers"):
            w.layers.clear_ai_items()
        w.current_ai_results = []
        w.current_imported_annotations = []
        if hasattr(w, "layers"):
            w.layers.clear_imported_items()
        if hasattr(w, "heatmap_controller"):
            w.heatmap_controller._clear_heatmap()
        if hasattr(w, "btn_export"):
            w.btn_export.setEnabled(False)
        if hasattr(w, "gallery"):
            w.gallery.clear_gallery()

    def _activate_slide(self, file_path):
        self.current_wsi_path = file_path
        self._window.current_wsi_path = file_path
        self._viewer.load_wsi(file_path)
        self._window.statusBar().showMessage(
            f"正在加载: {os.path.basename(file_path)}..."
        )

        if self._viewer.current_metadata is not None:
            thumb_img, downsample = container.image_server.get_thumbnail(
                file_path, level_from_last=1
            )
            self._minimap.load_minimap(thumb_img, downsample)

        if self._image_list_panel:
            self._image_list_panel.highlight(file_path)

    def _post_switch_tasks(self, file_path):
        w = self._window
        db = container.database
        cache_data = db.get_analysis(file_path)
        if cache_data and cache_data.get("status") == "completed":
            results = cache_data.get("results", [])
            reply = QMessageBox.question(
                w, "发现分析缓存",
                "检测到该病理切片已有历史检测记录。\n是否直接加载本地缓存结果？",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                from wsi_analyzer.domain.analysis import AnalysisResult
                result = AnalysisResult.from_cache(cache_data)
                w.result_controller.render_ai_results(result)
                w.statusBar().showMessage(
                    f"已从本地数据库加载 {len(results)} 个病灶。"
                )

        drive_prefix = HardwareProfiler.get_storage_key(file_path)
        existing_profile = db.get_system_profile(drive_prefix)

        if self._profile_worker and self._profile_worker.isRunning():
            try:
                self._profile_worker.profile_ready.disconnect()
            except RuntimeError:
                pass
            self._profile_worker.cancel()

        from wsi_analyzer.workers import ProfileWorker

        self._profile_worker = ProfileWorker(file_path, drive_prefix, existing_profile)
        self._profile_worker.profile_ready.connect(self._on_profile_ready)
        self._profile_worker.start()

    def _on_profile_ready(self, status_msg: str, tile_cache_limit: int):
        self._window.statusBar().showMessage(status_msg)
        self._viewer.set_tile_cache_capacity(tile_cache_limit)
