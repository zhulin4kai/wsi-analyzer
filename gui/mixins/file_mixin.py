import os

from PySide6.QtWidgets import QFileDialog, QMessageBox

from utils import DatabaseManager


class FileHandlingMixin:
    """WSI 文件打开、I/O 测速及硬件画像持久化。"""

    def open_file(self):
        """打开文件并记录路径"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择病理切片", "", "WSI Files (*.svs *.tif *.ndpi)"
        )

        if file_path:
            # 切换切片前，清空 AI 预测框
            for item in self.ai_layer_group.childItems():
                self.ai_layer_group.removeFromGroup(item)
                self.viewer.scene_canvas.removeItem(item)
            self.current_ai_results = []
            if hasattr(self, "btn_export"):
                self.btn_export.setEnabled(False)

            if hasattr(self, "gallery"):
                self.gallery.clear_gallery()

            self.current_wsi_path = file_path
            self.viewer.load_wsi(file_path)
            self.statusBar().showMessage(f"已加载: {os.path.basename(file_path)}")

            drive_prefix = os.path.splitdrive(os.path.abspath(file_path))[0]
            db = DatabaseManager()
            existing_profile = db.get_system_profile(drive_prefix)

            # I/O 测速 (I/O Benchmark)
            import config
            from core.slide_engine import WSIDataEngine
            from utils.hardware_profiler import HardwareProfiler

            def init_and_thumb(fp):
                engine = WSIDataEngine(fp)
                img, _ = engine.get_thumbnail()
                # 估算像素体积 (bytes)
                bytes_size = img.width * img.height * 3
                engine.close()
                return bytes_size

            new_io_speed = HardwareProfiler.measure_io_speed(file_path, init_and_thumb)

            if existing_profile and "io_speed" in existing_profile:
                # 使用 EMA (指数移动平均) 进化算法
                old_io_speed = existing_profile["io_speed"]

                # 突变检测：如果最新测速显著偏离历史值，则重置 EMA
                if (
                    new_io_speed > old_io_speed * 3.0
                    or new_io_speed < old_io_speed * 0.2
                ):
                    io_speed = new_io_speed
                    evolution_count = 1
                    db.set_setting(f"evol_count_{drive_prefix}", 1)
                else:
                    io_speed = new_io_speed * getattr(
                        config, "EMA_ALPHA_NEW", 0.3
                    ) + old_io_speed * getattr(config, "EMA_ALPHA_OLD", 0.7)
                    evol_count_key = f"evol_count_{drive_prefix}"
                    evolution_count = int(db.get_setting(evol_count_key, 1)) + 1
                    db.set_setting(evol_count_key, evolution_count)
            else:
                io_speed = new_io_speed
                evolution_count = 1
                db.set_setting(f"evol_count_{drive_prefix}", 1)

            device = HardwareProfiler.get_compute_device()
            _, free_vram = HardwareProfiler.get_vram_info(device)

            # 默认模型大小 100MB，切换模型时重新计算
            optimal_params = HardwareProfiler.calculate_optimal_params(
                io_speed, free_vram, 100.0
            )
            optimal_params["io_speed"] = io_speed

            # 如果用户未开启智能调优且之前有手动设定的 batch_size，予以保留
            if (
                existing_profile
                and "batch_size" in existing_profile
                and not db.get_auto_tune_enabled()
            ):
                optimal_params["batch_size"] = existing_profile["batch_size"]

            db.save_system_profile(drive_prefix, optimal_params)

            if (
                hasattr(self.viewer, "tile_cache")
                and "tile_cache_limit" in optimal_params
            ):
                self.viewer.tile_cache.max_capacity = optimal_params["tile_cache_limit"]

            self.statusBar().showMessage(
                f"已加载: {os.path.basename(file_path)} | 综合解码性能: {io_speed:.2f} MB/s"
                f" (已基于 {evolution_count} 次使用进化) | Batch: {optimal_params['batch_size']}"
            )

            if hasattr(self.viewer, "slide_engine") and self.viewer.slide_engine:
                self.minimap.load_minimap(self.viewer.slide_engine)

            # 本地数据库静默读取
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
