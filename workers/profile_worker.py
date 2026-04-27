import os

from PySide6.QtCore import QThread, Signal

from utils import logger


class ProfileWorker(QThread):
    """
    后台 I/O 测速与硬件画像更新线程。
    将耗时的测速操作移出主线程，避免切换切片时 UI 冻结。
    """

    # 信号：(状态栏消息, 瓦片缓存上限)
    profile_ready = Signal(str, int)

    def __init__(self, file_path: str, drive_prefix: str, existing_profile):
        """
        :param file_path: WSI 文件路径
        :param drive_prefix: 驱动器前缀，用于硬件画像键
        :param existing_profile: 已有硬件画像字典，可为 None
        """
        super().__init__()
        self.file_path = file_path
        self.drive_prefix = drive_prefix
        self.existing_profile = existing_profile
        self._cancelled = False

    def run(self):
        if self._cancelled:
            return
        try:
            import config
            from core.slide_engine import WSIDataEngine
            from utils import DatabaseManager
            from utils.hardware_profiler import HardwareProfiler

            db = DatabaseManager()

            def init_and_thumb(fp):
                engine = WSIDataEngine(fp)
                img, _ = engine.get_thumbnail()
                # 估算像素体积 (bytes)
                bytes_size = img.width * img.height * 3
                engine.close()
                return bytes_size

            new_io_speed = HardwareProfiler.measure_io_speed(
                self.file_path, init_and_thumb
            )

            if self._cancelled:
                return

            existing = self.existing_profile
            drive_prefix = self.drive_prefix

            if existing and "io_speed" in existing:
                # 使用 EMA (指数移动平均) 进化算法
                old_io_speed = existing["io_speed"]
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
            if existing and "batch_size" in existing and not db.get_auto_tune_enabled():
                optimal_params["batch_size"] = existing["batch_size"]

            db.save_system_profile(drive_prefix, optimal_params)

            if self._cancelled:
                return

            status_msg = (
                f"已加载: {os.path.basename(self.file_path)} | 综合解码性能: {io_speed:.2f} MB/s"
                f" (已基于 {evolution_count} 次使用进化) | Batch: {optimal_params['batch_size']}"
            )
            tile_cache_limit = optimal_params.get("tile_cache_limit", 300)

            self.profile_ready.emit(status_msg, tile_cache_limit)

        except Exception as e:
            logger.error(f"ProfileWorker 测速失败 [{self.file_path}]: {e}")

    def cancel(self):
        """中断测速任务"""
        self._cancelled = True
