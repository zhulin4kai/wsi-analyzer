import os

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from utils import DatabaseManager


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
        """执行切片加载的核心逻辑（立即显示缩略图，后台完成 I/O 测速与画像更新）。"""
        # 切换切片前，清空 AI 预测框与热力图
        for item in self.ai_layer_group.childItems():
            self.ai_layer_group.removeFromGroup(item)
            self.viewer.scene_canvas.removeItem(item)
        self.current_ai_results = []
        if hasattr(self, "_clear_heatmap"):
            self._clear_heatmap()
        if hasattr(self, "btn_export"):
            self.btn_export.setEnabled(False)

        if hasattr(self, "gallery"):
            self.gallery.clear_gallery()

        self.current_wsi_path = file_path
        self.viewer.load_wsi(file_path)
        self.statusBar().showMessage(f"正在加载: {os.path.basename(file_path)}...")

        # 强制立即刷新，使低分辨率缩略图第一时间上屏
        QApplication.processEvents()

        if hasattr(self.viewer, "slide_engine") and self.viewer.slide_engine:
            self.minimap.load_minimap(self.viewer.slide_engine)

        # 本地数据库缓存读取（快速查询，保留在主线程）
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

        # 在图像列表中高亮当前已加载的项
        if hasattr(self, "image_list_panel"):
            self.image_list_panel.highlight(file_path)

        # 后台 I/O 测速与硬件画像更新（耗时操作，不阻塞主线程）
        drive_prefix = os.path.splitdrive(os.path.abspath(file_path))[0]
        existing_profile = db.get_system_profile(drive_prefix)

        # 取消并替换旧的测速 Worker（断开信号防止旧结果污染当前状态）
        if hasattr(self, "_profile_worker") and self._profile_worker.isRunning():
            try:
                self._profile_worker.profile_ready.disconnect()
            except RuntimeError:
                pass
            self._profile_worker.cancel()

        from workers.profile_worker import ProfileWorker

        self._profile_worker = ProfileWorker(file_path, drive_prefix, existing_profile)
        self._profile_worker.profile_ready.connect(self._on_profile_ready)
        self._profile_worker.start()

    def _on_profile_ready(self, status_msg: str, tile_cache_limit: int):
        """接收后台测速结果，更新状态栏与瓦片缓存上限。"""
        self.statusBar().showMessage(status_msg)
        if hasattr(self.viewer, "tile_cache"):
            self.viewer.tile_cache.max_capacity = tile_cache_limit
