import subprocess
import time

import psutil

import config


class HardwareProfiler:
    @staticmethod
    def get_compute_device() -> str:
        """
        检测可用的计算设备。
        返回优先顺序：cuda -> mps -> cpu
        """
        try:
            import onnxruntime as ort

            providers = ort.get_available_providers()
            if "CUDAExecutionProvider" in providers:
                return "cuda"
            if (
                "CoreMLExecutionProvider" in providers
                or "MPSExecutionProvider" in providers
            ):
                return "mps"
        except Exception:
            pass
        return "cpu"

    @staticmethod
    def get_system_ram_info() -> tuple:
        """
        获取系统物理总内存和当前可用内存。
        :return: (total_ram_mb, available_ram_mb)
        """
        vm = psutil.virtual_memory()
        total_ram_mb = vm.total / (1024 * 1024)
        available_ram_mb = vm.available / (1024 * 1024)
        return total_ram_mb, available_ram_mb

    @staticmethod
    def get_vram_info(device: str) -> tuple:
        """
        获取 GPU 的总显存和空闲显存。
        :param device: "cuda"、"mps" 或 "cpu"
        :return: (total_vram_mb, free_vram_mb)
        """
        if device == "cuda":
            # 优先通过 pynvml 精确读取
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

            # 次选通过 nvidia-smi 命令行读取
            try:
                result = subprocess.run(
                    [
                        "nvidia-smi",
                        "--query-gpu=memory.total,memory.free",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    parts = result.stdout.strip().split("\n")[0].split(",")
                    return float(parts[0].strip()), float(parts[1].strip())
            except Exception:
                pass

            # 两种方式均失败时返回 (0, 0)，由调用方退化为最小 batch_size
            return 0.0, 0.0

        elif device == "mps":
            # Apple Silicon 统一内存架构，以系统可用内存的 70% 作为可用显存估算值
            total_ram_mb, available_ram_mb = HardwareProfiler.get_system_ram_info()
            return total_ram_mb, available_ram_mb * 0.7

        else:
            return HardwareProfiler.get_system_ram_info()

    @staticmethod
    def measure_io_speed(file_path: str, engine_init_func) -> float:
        """
        I/O 测速 (I/O Benchmark)
        记录加载 WSI 及提取缩略图的时间差，计算 I/O 吞吐率。
        :param file_path: WSI 文件路径
        :param engine_init_func: 一个可调用对象，负责实例化引擎并获取 thumbnail，返回 (图像对象/大小, 像素体积_bytes)
        :return: I/O 速度 (MB/s)
        """
        try:
            start_time = time.perf_counter()
            thumbnail_bytes = engine_init_func(file_path)
            end_time = time.perf_counter()

            elapsed_sec = end_time - start_time
            if elapsed_sec <= 0:
                elapsed_sec = 0.001

            io_speed_mbps = (thumbnail_bytes / (1024 * 1024)) / elapsed_sec
            return io_speed_mbps

        except Exception as _e:
            return 20

    @staticmethod
    def calculate_optimal_params(
        io_speed: float, free_vram: float, model_size: float, total_ram: float = 0.0
    ) -> dict:
        """
        第二阶段：启发式参数计算引擎 (Heuristic Engine)
        基于当前硬件状况与介质读写速度，计算最优的 batch_size 和缓存上限。

        :param io_speed: I/O 读取速度 (MB/s)
        :param free_vram: 可用显存 (MB)
        :param model_size: 模型文件物理大小 (MB)
        :param total_ram: 系统物理总内存 (MB)，若为 0.0 则自动获取
        :return: dict 包含 'batch_size' 和 'tile_cache_limit'
        """
        if total_ram == 0.0:
            total_ram, _ = HardwareProfiler.get_system_ram_info()

        # 1. 计算理论显存上限
        safety_margin = config.SAFE_VRAM_MARGIN_MB
        model_overhead = model_size * config.MODEL_VRAM_OVERHEAD_MULTIPLIER
        vram_per_tile = config.VRAM_PER_TILE_MB

        usable_vram = free_vram - model_overhead - safety_margin

        if usable_vram <= 0:
            theoretical_batch_size = 1
        else:
            theoretical_batch_size = int(usable_vram / vram_per_tile)

        # 2. I/O 瓶颈截断机制
        io_capped_batch_size = theoretical_batch_size
        if io_speed < config.IO_SPEED_NAS_USB2_MBPS:
            io_capped_batch_size = min(
                theoretical_batch_size, config.BATCH_SIZE_CAP_NAS_USB2
            )
        elif io_speed < config.IO_SPEED_SATA_SSD_MBPS:
            io_capped_batch_size = min(
                theoretical_batch_size, config.BATCH_SIZE_CAP_SATA_SSD
            )
        elif io_speed < config.IO_SPEED_NORMAL_SSD_MBPS:
            io_capped_batch_size = min(
                theoretical_batch_size, config.BATCH_SIZE_CAP_NORMAL_SSD
            )
        else:
            io_capped_batch_size = min(
                theoretical_batch_size, config.BATCH_SIZE_CAP_NVME_SSD
            )

        final_batch_size = max(1, io_capped_batch_size)

        # 3. 缓存自适应降级
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
        """根据综合测速，计算滑动步长重叠率与置信度"""
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
        """评估 I/O 评级，用于 UI 展示"""
        if io_speed < config.IO_SPEED_NAS_USB2_MBPS:
            return "低速 (HDD/NAS/USB2.0)"
        elif io_speed < config.IO_SPEED_SATA_SSD_MBPS:
            return "一般 (SATA SSD)"
        elif io_speed < config.IO_SPEED_NORMAL_SSD_MBPS:
            return "良好 (普通固态)"
        else:
            return "高速 (NVMe/PCIe SSD)"
