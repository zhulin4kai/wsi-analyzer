import os

from PySide6.QtWidgets import QFileDialog, QMessageBox

from core import ImageServer
from utils import DatabaseManager, HardwareProfiler


class FileHandlingMixin:
    """WSI 文件打开、I/O 测速及硬件画像持久化。"""

    def open_file(self):
        """打开文件对话框并加载选定的 WSI，同时将其加入图像列表。"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择病理切片", "", "WSI Files (*.svs *.tif *.ndpi)"
        )
        if file_path:
            self._load_wsi_at_path(file_path)
            if hasattr(self, "image_list_panel"):
                self.image_list_panel.add_image(file_path)

    def add_images_to_list(self):
        """打开多选文件对话框，将 WSI 批量加入图像列表（不自动加载）。"""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "批量添加图像", "", "WSI Files (*.svs *.tif *.ndpi)"
        )
        if paths and hasattr(self, "image_list_panel"):
            self.image_list_panel.add_images(paths)

    def _load_wsi_at_path(self, file_path):
        """执行切片加载的核心逻辑（立即显示缩略图，后台完成 I/O 测速与画像更新）。
        重入保护：若上一次加载尚未完成（例如因 processEvents 导致事件循环重入），
        则忽略本次调用，防止两个 load_wsi 并发执行引发 OpenSlide use-after-free 崩溃。
        """
        if getattr(self, "_is_loading_wsi", False):
            return
        self._is_loading_wsi = True

        try:
            self._do_load_wsi_at_path(file_path)
        finally:
            self._is_loading_wsi = False

    def _do_load_wsi_at_path(self, file_path):
        """_load_wsi_at_path 的实际执行体，由重入保护包装后调用。"""
        self._pre_switch_cleanup()
        self._activate_slide(file_path)
        self._post_switch_tasks(file_path)

    def _pre_switch_cleanup(self):
        """清空旧切片的 AI 结果、热力图和画廊（在 load_wsi 之前执行）。"""
        for item in self.ai_layer_group.childItems():
            self.ai_layer_group.removeFromGroup(item)
            self.viewer.scene_canvas.removeItem(item)
        self.current_ai_results = []
        self.current_imported_annotations = []
        if hasattr(self, "_clear_imported_layer"):
            self._clear_imported_layer()
        if hasattr(self, "_clear_heatmap"):
            self._clear_heatmap()
        if hasattr(self, "btn_export"):
            self.btn_export.setEnabled(False)
        if hasattr(self, "gallery"):
            self.gallery.clear_gallery()

    def _activate_slide(self, file_path):
        """加载切片数据并更新所有视图组件：viewer、minimap、状态栏。"""
        self.current_wsi_path = file_path
        self.viewer.load_wsi(file_path)
        self.statusBar().showMessage(f"正在加载: {os.path.basename(file_path)}...")

        if self.viewer.current_metadata is not None:
            thumb_img, downsample = ImageServer.instance().get_thumbnail(
                file_path, level_from_last=1
            )
            self.minimap.load_minimap(thumb_img, downsample)

        # 在图像列表中高亮当前已加载的项
        if hasattr(self, "image_list_panel"):
            self.image_list_panel.highlight(file_path)

    def _post_switch_tasks(self, file_path):
        """数据库缓存查询（含阻塞弹窗）+ 后台 I/O 测速启动。"""
        db = DatabaseManager()
        cache_data = db.get_analysis(file_path)
        if cache_data and cache_data.get("status") == "completed":
            results = cache_data.get("results", [])
            reply = QMessageBox.question(
                self,
                "发现分析缓存",
                "检测到该病理切片已有历史检测记录。\n是否直接加载本地缓存结果？",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self.render_ai_results({"results": results, "status": "completed"})
                self.statusBar().showMessage(
                    f"已从本地数据库加载 {len(results)} 个病灶。"
                )

        drive_prefix = HardwareProfiler.get_storage_key(file_path)
        existing_profile = db.get_system_profile(drive_prefix)

        if hasattr(self, "_profile_worker") and self._profile_worker.isRunning():
            try:
                self._profile_worker.profile_ready.disconnect()
            except RuntimeError:
                pass
            self._profile_worker.cancel()

        from workers import ProfileWorker

        self._profile_worker = ProfileWorker(file_path, drive_prefix, existing_profile)
        self._profile_worker.profile_ready.connect(self._on_profile_ready)
        self._profile_worker.start()

    def _on_profile_ready(self, status_msg: str, tile_cache_limit: int):
        """接收后台测速结果，更新状态栏与瓦片缓存上限。"""
        self.statusBar().showMessage(status_msg)
        self.viewer.set_tile_cache_capacity(tile_cache_limit)
