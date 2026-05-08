import os
import subprocess
import sys
import time

import psutil

import config
from wsi_analyzer.infrastructure.logging.logger import logger


class HardwareProfiler:

    @staticmethod
    def get_storage_key(file_path: str) -> str:
        abs_path = os.path.abspath(file_path)
        if sys.platform == "win32":
            return os.path.splitdrive(abs_path)[0] or "C:"
        parts = abs_path.strip("/").split("/")
        if len(parts) >= 2:
            return "/" + "/".join(parts[:2])
        return "/"

    @staticmethod
    def get_compute_device() -> str:
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return "mps"
        except ImportError:
            pass
        except Exception:
            pass
        return "cpu"

    @staticmethod
    def get_system_ram_info() -> tuple:
        vm = psutil.virtual_memory()
        total_ram_mb = vm.total / (1024 * 1024)
        available_ram_mb = vm.available / (1024 * 1024)
        return total_ram_mb, available_ram_mb

    @staticmethod
    def get_vram_info(device: str) -> tuple:
        if device == "cuda":
            try:
                import pynvml
                pynvml.nvmlInit()
                handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                info = pynvml.nvmlMemoryInfo(handle)
                total_mb = info.total / (1024 * 1024)
                free_mb = info.free / (1024 * 1024)
                pynvml.nvmlShutdown()
                return total_mb, free_mb
            except Exception:
                pass

            try:
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=memory.total,memory.free",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    parts = result.stdout.strip().split("\n")[0].split(",")
                    return float(parts[0].strip()), float(parts[1].strip())
            except Exception:
                pass

            return 0.0, 0.0

        elif device == "mps":
            total_ram_mb, available_ram_mb = HardwareProfiler.get_system_ram_info()
            return total_ram_mb, available_ram_mb * 0.7

        else:
            return HardwareProfiler.get_system_ram_info()

    @staticmethod
    def measure_io_speed(file_path: str, engine_init_func) -> float:
        try:
            start_time = time.perf_counter()
            thumbnail_bytes = engine_init_func(file_path)
            end_time = time.perf_counter()
            elapsed_sec = end_time - start_time
            if elapsed_sec <= 0:
                elapsed_sec = 0.001
            io_speed_mbps = (thumbnail_bytes / (1024 * 1024)) / elapsed_sec
            return io_speed_mbps
        except Exception as e:
            logger.warning(f"I/O 测速失败，使用默认值 20 MB/s: {e}")
            return 20.0

    @staticmethod
    def calculate_optimal_params(
        io_speed: float, free_vram: float, model_size: float, total_ram: float = 0.0
    ) -> dict:
        if total_ram == 0.0:
            total_ram, _ = HardwareProfiler.get_system_ram_info()

        safety_margin = config.SAFE_VRAM_MARGIN_MB
        model_overhead = model_size * config.MODEL_VRAM_OVERHEAD_MULTIPLIER
        vram_per_tile = config.VRAM_PER_TILE_MB

        usable_vram = free_vram - model_overhead - safety_margin
        if usable_vram <= 0:
            theoretical_batch_size = 1
        else:
            theoretical_batch_size = int(usable_vram / vram_per_tile)

        io_capped_batch_size = theoretical_batch_size
        if io_speed < config.IO_SPEED_NAS_USB2_MBPS:
            io_capped_batch_size = min(theoretical_batch_size, config.BATCH_SIZE_CAP_NAS_USB2)
        elif io_speed < config.IO_SPEED_SATA_SSD_MBPS:
            io_capped_batch_size = min(theoretical_batch_size, config.BATCH_SIZE_CAP_SATA_SSD)
        elif io_speed < config.IO_SPEED_NORMAL_SSD_MBPS:
            io_capped_batch_size = min(theoretical_batch_size, config.BATCH_SIZE_CAP_NORMAL_SSD)
        else:
            io_capped_batch_size = min(theoretical_batch_size, config.BATCH_SIZE_CAP_NVME_SSD)

        final_batch_size = max(1, io_capped_batch_size)

        if total_ram < config.RAM_THRESHOLD_SMALL_MB:
            tile_cache_limit = config.TILE_CACHE_LIMIT_SMALL
        elif total_ram < config.RAM_THRESHOLD_NORMAL_MB:
            tile_cache_limit = config.TILE_CACHE_LIMIT_NORMAL
        else:
            tile_cache_limit = config.TILE_CACHE_LIMIT_LARGE

        return {
            "batch_size": final_batch_size,
            "tile_cache_limit": tile_cache_limit,
            "device": HardwareProfiler.get_compute_device(),
            "io_rating": HardwareProfiler._rate_io_speed(io_speed),
        }

    @staticmethod
    def calculate_auto_tune_params(
        io_speed: float, patch_size: int, model_size: float
    ) -> dict:
        if io_speed < config.IO_SPEED_SATA_SSD_MBPS:
            stride = int(patch_size * config.AUTO_STRIDE_RATIO_LOW)
        elif io_speed < config.IO_SPEED_NORMAL_SSD_MBPS:
            stride = int(patch_size * config.AUTO_STRIDE_RATIO_MID)
        else:
            stride = int(patch_size * config.AUTO_STRIDE_RATIO_HIGH)

        if model_size > 100.0:
            conf_thresh = 0.5
        else:
            conf_thresh = 0.35

        return {"stride": stride, "conf_thresh": conf_thresh}

    @staticmethod
    def _rate_io_speed(io_speed: float) -> str:
        if io_speed < config.IO_SPEED_NAS_USB2_MBPS:
            return "低速 (HDD/NAS/USB2.0)"
        elif io_speed < config.IO_SPEED_SATA_SSD_MBPS:
            return "一般 (SATA SSD)"
        elif io_speed < config.IO_SPEED_NORMAL_SSD_MBPS:
            return "良好 (普通固态)"
        else:
            return "高速 (NVMe/PCIe SSD)"
