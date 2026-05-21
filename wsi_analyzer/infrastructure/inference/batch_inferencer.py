import concurrent.futures
import os
import statistics
import threading
import time
from collections import defaultdict, deque
from typing import Tuple

from tqdm import tqdm

from wsi_analyzer.infrastructure.inference.oom_policy import OOMRetryPolicy
from wsi_analyzer.infrastructure.inference.prediction_mapper import PredictionMapper
from wsi_analyzer.infrastructure.logging import logger


class BatchInferencer:
    def __init__(self, model_adapter, patch_reader, device: str, batch_size: int,
                 conf_thresh: float, model_input_size: int):
        self._adapter = model_adapter
        self._reader = patch_reader
        self._device = device
        self._batch_size = batch_size
        self._conf_thresh = conf_thresh
        self._model_input_size = model_input_size

    @property
    def batch_size(self) -> int:
        return self._batch_size

    @batch_size.setter
    def batch_size(self, value: int):
        self._batch_size = value

    def infer(
        self,
        coords,
        progress_callback=None,
        cancel_check=None,
    ) -> Tuple[list, list, list, int]:
        global_boxes = []
        global_scores = []
        global_classes = []
        processed = 0
        next_index = 0
        total_start = time.perf_counter()
        read_wait_seconds = 0.0
        read_seconds = 0.0
        infer_seconds = 0.0
        map_seconds = 0.0
        max_queue_depth = 0
        batch_durations = []
        batch_sizes = []
        batch_detection_counts = []
        worker_stats = defaultdict(lambda: {
            "patches": 0,
            "total_seconds": 0.0,
            "max_seconds": 0.0,
        })

        pbar = tqdm(total=len(coords), desc="模型推理", unit="patch", colour="cyan")
        io_workers = self._resolve_io_workers()
        prefetch_batches = self._resolve_prefetch_batches()
        cpu_sampler = _CpuSampler()
        cpu_sampler.start()
        _log_runtime_header(
            device=self._device,
            patch_count=len(coords),
            batch_size=self._batch_size,
            io_workers=io_workers,
            prefetch_batches=prefetch_batches,
            model_input_size=self._model_input_size,
        )

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=io_workers,
            thread_name_prefix="patch-read",
        ) as executor:
            pending_batches = deque()

            def refill_queue():
                nonlocal next_index, max_queue_depth
                while len(pending_batches) < prefetch_batches and next_index < len(coords):
                    if cancel_check and cancel_check():
                        break
                    batch = self._submit_batch(executor, coords, next_index)
                    if batch is None:
                        break
                    pending_batches.append(batch)
                    next_index = batch[3]
                    max_queue_depth = max(max_queue_depth, len(pending_batches))

            refill_queue()

            while pending_batches:
                if cancel_check and cancel_check():
                    break

                batch_start, batch_coords, futures, _ = pending_batches.popleft()
                refill_queue()

                read_start = time.perf_counter()
                timed_imgs = [future.result() for future in futures]
                read_wait_seconds += time.perf_counter() - read_start
                batch_imgs = [img for img, _elapsed, _worker in timed_imgs]
                read_seconds += sum(elapsed for _img, elapsed, _worker in timed_imgs)
                for _img, elapsed, worker_name in timed_imgs:
                    stats = worker_stats[worker_name]
                    stats["patches"] += 1
                    stats["total_seconds"] += elapsed
                    stats["max_seconds"] = max(stats["max_seconds"], elapsed)

                try:
                    infer_start = time.perf_counter()
                    results = self._adapter.predict(
                        batch_imgs, device=self._device, conf_thresh=self._conf_thresh,
                        imgsz=self._model_input_size,
                    )
                    batch_infer_seconds = time.perf_counter() - infer_start
                    infer_seconds += batch_infer_seconds
                    batch_durations.append(batch_infer_seconds)
                    batch_sizes.append(len(batch_imgs))
                    batch_detection_counts.append(
                        sum(len(boxes) for boxes, _scores, _classes in results)
                    )
                except RuntimeError as e:
                    if self._batch_size <= 1:
                        raise RuntimeError("Batch size 1 still OOM") from e
                    if not OOMRetryPolicy.is_oom(e):
                        raise e
                    logger.warning("OOM detected, reducing batch size for retry")
                    self._batch_size = OOMRetryPolicy.next_batch_size(self._batch_size)
                    _cancel_pending_batches(pending_batches)
                    pending_batches.clear()
                    next_index = batch_start
                    prefetch_batches = self._resolve_prefetch_batches()
                    refill_queue()
                    continue

                map_start = time.perf_counter()
                new_boxes, new_scores, new_classes = PredictionMapper.to_level0_batch(
                    results, batch_coords
                )
                map_seconds += time.perf_counter() - map_start
                global_boxes.extend(new_boxes)
                global_scores.extend(new_scores)
                global_classes.extend(new_classes)

                processed += len(batch_coords)
                pbar.update(len(batch_coords))

                if progress_callback:
                    progress_callback(processed)

            _cancel_pending_batches(pending_batches)

        pbar.close()
        if processed:
            total_seconds = max(time.perf_counter() - total_start, 1e-9)
            patches_per_sec = processed / total_seconds
            _log_pipeline_summary(
                processed, self._batch_size, io_workers, prefetch_batches,
                max_queue_depth, read_seconds, read_wait_seconds, infer_seconds,
                map_seconds, total_seconds, patches_per_sec,
                sum(batch_detection_counts), len(global_boxes),
            )
            _log_worker_summary(worker_stats)
            _log_model_summary(batch_durations, batch_sizes, batch_detection_counts)
            _log_cpu_summary(cpu_sampler.stop())
        else:
            _log_cpu_summary(cpu_sampler.stop())
        return global_boxes, global_scores, global_classes, processed

    def _resolve_io_workers(self) -> int:
        if self._device == "cpu":
            cpu_count = os.cpu_count() or 2
            return max(2, min(8, cpu_count // 2 or 1))
        return max(1, min(8, self._batch_size))

    def _submit_batch(self, executor, coords, start: int):
        batch_coords = coords[start : start + self._batch_size]
        if not batch_coords:
            return None
        futures = [executor.submit(self._timed_read, coord) for coord in batch_coords]
        return start, batch_coords, futures, start + len(batch_coords)

    def _timed_read(self, coord):
        start = time.perf_counter()
        image = self._reader.read(coord)
        return image, time.perf_counter() - start, threading.current_thread().name

    def _resolve_prefetch_batches(self) -> int:
        batch_size = max(1, self._batch_size)
        side = max(1, self._model_input_size)
        estimated_patch_bytes = int(side * side * 3 * 2.5)
        estimated_batch_bytes = max(1, estimated_patch_bytes * batch_size)
        memory_budget = int(_available_memory_bytes() * 0.10)
        batches_by_memory = max(1, memory_budget // estimated_batch_bytes)
        return max(1, min(4, batches_by_memory))


def _available_memory_bytes() -> int:
    try:
        import psutil
        return int(psutil.virtual_memory().available)
    except Exception:
        return 512 * 1024 * 1024


def _cancel_pending_batches(pending_batches):
    for _start, _coords, futures, _end in pending_batches:
        for future in futures:
            future.cancel()


class _CpuSampler:
    def __init__(self):
        self._psutil = None

    def start(self):
        try:
            import psutil
            self._psutil = psutil
            psutil.cpu_percent(interval=None, percpu=True)
        except Exception:
            self._psutil = None

    def stop(self):
        if self._psutil is None:
            return None
        try:
            return self._psutil.cpu_percent(interval=None, percpu=True)
        except Exception:
            return None


def _torch_thread_info() -> tuple[str, str]:
    try:
        import torch
        return str(torch.get_num_threads()), str(torch.get_num_interop_threads())
    except Exception:
        return "未知", "未知"


def _physical_cpu_count():
    try:
        import psutil
        return psutil.cpu_count(logical=False)
    except Exception:
        return None


def _log_runtime_header(
    device: str,
    patch_count: int,
    batch_size: int,
    io_workers: int,
    prefetch_batches: int,
    model_input_size: int,
):
    torch_threads, torch_interop = _torch_thread_info()
    logger.info(
        "\n========== CPU 推理运行配置 ==========\n"
        "推理设备               %s\n"
        "待推理 patch 数        %d\n"
        "模型输入尺寸           %d\n"
        "batch size             %d\n"
        "I/O worker 数          %d\n"
        "预取 batch 数          %d\n"
        "逻辑 CPU 核心          %s\n"
        "物理 CPU 核心          %s\n"
        "PyTorch 计算线程       %s\n"
        "PyTorch interop 线程   %s\n"
        "说明                   模型推理由 PyTorch 在线程池内调度；"
        "patch 只在 I/O worker 间显式分配\n"
        "=====================================",
        device,
        patch_count,
        model_input_size,
        batch_size,
        io_workers,
        prefetch_batches,
        os.cpu_count() or "未知",
        _physical_cpu_count() or "未知",
        torch_threads,
        torch_interop,
    )


def _log_pipeline_summary(
    processed: int,
    batch_size: int,
    io_workers: int,
    prefetch_batches: int,
    max_queue_depth: int,
    read_seconds: float,
    read_wait_seconds: float,
    infer_seconds: float,
    map_seconds: float,
    total_seconds: float,
    patches_per_sec: float,
    raw_detection_count: int,
    mapped_detection_count: int,
):
    logger.info(
        "\n========== Batch 流水线汇总 ==========\n"
        "完成 patch 数          %d\n"
        "batch size             %d\n"
        "I/O worker 数          %d\n"
        "预取 batch 数          %d\n"
        "队列最大占用           %d\n"
        "总耗时                 %.2fs\n"
        "整体吞吐               %.2f patches/s\n"
        "读取+resize 累计耗时   %.2fs\n"
        "主线程等待读取耗时     %.2fs\n"
        "模型 predict 总耗时    %.2fs\n"
        "坐标映射总耗时         %.2fs\n"
        "原始检测框数量         %d\n"
        "映射后检测框数量       %d\n"
        "=====================================",
        processed,
        batch_size,
        io_workers,
        prefetch_batches,
        max_queue_depth,
        total_seconds,
        patches_per_sec,
        read_seconds,
        read_wait_seconds,
        infer_seconds,
        map_seconds,
        raw_detection_count,
        mapped_detection_count,
    )


def _log_worker_summary(worker_stats):
    if not worker_stats:
        return
    lines = [
        "\n========== I/O worker 分配 ==========",
        "worker              patch数    总耗时(s)   平均(ms)   最慢(ms)",
    ]
    for worker_name in sorted(worker_stats):
        stats = worker_stats[worker_name]
        patches = stats["patches"]
        avg_ms = stats["total_seconds"] / patches * 1000 if patches else 0.0
        lines.append(
            f"{worker_name:<18}{patches:>7}"
            f"{stats['total_seconds']:>12.2f}{avg_ms:>11.1f}"
            f"{stats['max_seconds'] * 1000:>11.1f}"
        )
    lines.append("====================================")
    logger.info("\n".join(lines))


def _log_model_summary(batch_durations, batch_sizes, batch_detection_counts):
    if not batch_durations:
        return
    sorted_durations = sorted(batch_durations)
    slowest = sorted(
        enumerate(batch_durations, start=1),
        key=lambda item: item[1],
        reverse=True,
    )[:5]
    slowest_text = ", ".join(f"#{idx} {seconds:.2f}s" for idx, seconds in slowest)
    total_infer = sum(batch_durations)
    avg_patch_per_sec = sum(batch_sizes) / total_infer if total_infer > 0 else 0.0
    logger.info(
        "\n========== 模型 predict 汇总 ==========\n"
        "batch 数               %d\n"
        "总 patch 数            %d\n"
        "总检测框数             %d\n"
        "平均 batch 耗时        %.2fs\n"
        "P50 batch 耗时         %.2fs\n"
        "P95 batch 耗时         %.2fs\n"
        "最慢 batch 耗时        %.2fs\n"
        "平均模型吞吐           %.2f patches/s\n"
        "最慢 batch             %s\n"
        "=====================================",
        len(batch_durations),
        sum(batch_sizes),
        sum(batch_detection_counts),
        statistics.mean(batch_durations),
        _percentile(sorted_durations, 50),
        _percentile(sorted_durations, 95),
        max(batch_durations),
        avg_patch_per_sec,
        slowest_text,
    )


def _log_cpu_summary(per_core_percent):
    if not per_core_percent:
        logger.info("[CPU 利用率] 当前环境无法采样每核心利用率")
        return
    avg_usage = sum(per_core_percent) / len(per_core_percent)
    max_usage = max(per_core_percent)
    lines = [
        "\n========== CPU 每核心利用率 ==========",
        f"平均利用率             {avg_usage:.1f}%",
        f"最高核心利用率         {max_usage:.1f}%",
        "核心利用率             "
        + " ".join(f"{idx}:{usage:.0f}%" for idx, usage in enumerate(per_core_percent)),
        "说明                   这是推理阶段的系统级采样，"
        "不是 PyTorch 内部算子的精确核心分工",
        "====================================",
    ]
    logger.info("\n".join(lines))


def _percentile(sorted_values, percentile: int) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    rank = (len(sorted_values) - 1) * percentile / 100
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = rank - lower
    return float(sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight)
