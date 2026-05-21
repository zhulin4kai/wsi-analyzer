import concurrent.futures
import os
import time
from collections import deque
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

        pbar = tqdm(total=len(coords), desc="inference")
        io_workers = self._resolve_io_workers()
        prefetch_batches = self._resolve_prefetch_batches()

        with concurrent.futures.ThreadPoolExecutor(max_workers=io_workers) as executor:
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
                batch_imgs = [img for img, _elapsed in timed_imgs]
                read_seconds += sum(elapsed for _img, elapsed in timed_imgs)

                try:
                    infer_start = time.perf_counter()
                    results = self._adapter.predict(
                        batch_imgs, device=self._device, conf_thresh=self._conf_thresh,
                        imgsz=self._model_input_size,
                    )
                    infer_seconds += time.perf_counter() - infer_start
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
            logger.info(
                "[inference timing] patches=%d batch_size=%d io_workers=%d "
                "prefetch_batches=%d max_queue=%d read=%.2fs read_wait=%.2fs "
                "infer=%.2fs map=%.2fs throughput=%.2f patches/s",
                processed, self._batch_size, io_workers, prefetch_batches,
                max_queue_depth, read_seconds, read_wait_seconds,
                infer_seconds, map_seconds, patches_per_sec,
            )
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
        return image, time.perf_counter() - start

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
