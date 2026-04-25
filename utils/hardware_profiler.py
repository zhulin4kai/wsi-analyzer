import time

import psutil
import torch

import config


class HardwareProfiler:
    """
    硬件探针与性能基准测试模块
    负责探测计算设备、获取内存/显存信息、并基于启发式算法动态计算最优推理参数。
    """

    @staticmethod
    def get_compute_device() -> str:
        """
        静态硬件侦测：识别计算引擎
        返回优先顺序：cuda -> mps -> cpu
        """
        if torch is None:
            return "cpu"
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    @staticmethod
    def get_system_ram_info() -> tuple:
        """
        获取系统物理总内存和当前可用内存
        :return: (total_ram_mb, available_ram_mb)
        """
        vm = psutil.virtual_memory()
        total_ram_mb = vm.total / (1024 * 1024)
        available_ram_mb = vm.available / (1024 * 1024)
        return total_ram_mb, available_ram_mb

    @staticmethod
    def get_vram_info(device: str) -> tuple:
        """
        显存探针：获取GPU的总显存和空闲显存
        :param device: "cuda", "mps", 或 "cpu"
        :return: (total_vram_mb, free_vram_mb)
        """
        if device == "cuda" and torch is not None:
            # 返回当前设备的显存信息：(free, total) 字节
            free_bytes, total_bytes = torch.cuda.mem_get_info()
            return total_bytes / (1024 * 1024), free_bytes / (1024 * 1024)

        elif device == "mps":
            # Apple Silicon 使用统一内存架构，显存即系统内存
            total_ram_mb, available_ram_mb = HardwareProfiler.get_system_ram_info()
            # 出于安全考虑，认为系统可用内存的 70% 可用作显存
            return total_ram_mb, available_ram_mb * 0.7

        else:
            # CPU 推理，返回系统内存作为虚拟显存参考
            return HardwareProfiler.get_system_ram_info()

    @staticmethod
    def measure_io_speed(file_path: str, engine_init_func) -> float:
        """
        隐形 I/O 测速 (Invisible Benchmark)
        记录加载 WSI 及提取宏观缩略图的时间差，反推 I/O 吞吐率。
        :param file_path: WSI 文件路径
        :param engine_init_func: 一个可调用对象，负责实例化引擎并获取 thumbnail，返回 (图像对象/大小, 像素体积_bytes)
        :return: I/O 速度 (MB/s)
        """
        try:
            start_time = time.perf_counter()
            # engine_init_func 需执行加载切片并获取第一张宏观缩略图的操作
            # 并返回所读取数据的估算字节数
            thumbnail_bytes = engine_init_func(file_path)
            end_time = time.perf_counter()

            elapsed_sec = end_time - start_time
            if elapsed_sec <= 0:
                elapsed_sec = 0.001

            io_speed_mbps = (thumbnail_bytes / (1024 * 1024)) / elapsed_sec
            return io_speed_mbps

        except Exception as _e:
            # 如果测速失败，返回一个保守的安全默认值 (20 MB/s)
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
        # 安全冗余预留: 为避免显存碎片或突发占用，保留 500MB
        safety_margin = config.SAFE_VRAM_MARGIN_MB
        # 模型底座开销估算 (经验值：模型加载和激活计算约占用其体积的 2.5 倍显存)
        model_overhead = model_size * config.MODEL_VRAM_OVERHEAD_MULTIPLIER
        # 单个 512x512 瓦片的显存占用 (假设为 float32 的张量，带上一定计算开销，约 8MB)
        vram_per_tile = config.VRAM_PER_TILE_MB

        usable_vram = free_vram - model_overhead - safety_margin

        if usable_vram <= 0:
            theoretical_batch_size = 1  # 显存极低时，采用最低兜底值
        else:
            theoretical_batch_size = int(usable_vram / vram_per_tile)

        # 2. I/O 瓶颈截断机制
        # 防止 GPU 过快处理完数据陷入长时间等待引发卡顿
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
            # NVMe 固态级别的高速盘
            io_capped_batch_size = min(
                theoretical_batch_size, config.BATCH_SIZE_CAP_NVME_SSD
            )

        # 兜底约束，保证 batch_size 最少为 1
        final_batch_size = max(1, io_capped_batch_size)

        # 3. 缓存自适应降级
        # 如果物理内存小于 8GB (约 8000 MB)，降低 TileLRUCache 的瓦片缓存上限
        if total_ram < config.RAM_THRESHOLD_SMALL_MB:
            tile_cache_limit = config.TILE_CACHE_LIMIT_SMALL  # 小内存保守设置
        elif total_ram < config.RAM_THRESHOLD_NORMAL_MB:
            tile_cache_limit = config.TILE_CACHE_LIMIT_NORMAL  # 正常内存设置
        else:
            tile_cache_limit = config.TILE_CACHE_LIMIT_LARGE  # 充足内存时激进缓存

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
        """根据进化后的综合测速，推算最佳滑动步长重叠率与置信度"""
        # 步长自适应
        if io_speed < config.IO_SPEED_SATA_SSD_MBPS:
            stride = int(patch_size * config.AUTO_STRIDE_RATIO_LOW)
        elif io_speed < config.IO_SPEED_NORMAL_SSD_MBPS:
            stride = int(patch_size * config.AUTO_STRIDE_RATIO_MID)
        else:
            stride = int(patch_size * config.AUTO_STRIDE_RATIO_HIGH)

        # 置信度自适应 (大于 100MB 视为大模型)
        if model_size > 100.0:
            conf_thresh = 0.5
        else:
            conf_thresh = 0.35

        return {"stride": stride, "conf_thresh": conf_thresh}

    @staticmethod
    def _rate_io_speed(io_speed: float) -> str:
        """评估 I/O 评级，用于 UI 展示"""
        if io_speed < config.IO_SPEED_NAS_USB2_MBPS:
            return "极慢 (HDD/NAS/USB2.0)"
        elif io_speed < config.IO_SPEED_SATA_SSD_MBPS:
            return "一般 (SATA SSD)"
        elif io_speed < config.IO_SPEED_NORMAL_SSD_MBPS:
            return "良好 (普通固态)"
        else:
            return "优秀 (NVMe/PCIe SSD)"
