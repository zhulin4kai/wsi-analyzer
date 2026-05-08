import concurrent.futures
from typing import Optional, Tuple

import numpy as np
from tqdm import tqdm

from wsi_analyzer.infrastructure.logging import logger


class BatchInferencer:
    def __init__(self, model_adapter, patch_reader, device: str, batch_size: int, conf_thresh: float):
        self._adapter = model_adapter
        self._reader = patch_reader
        self._device = device
        self._batch_size = batch_size
        self._conf_thresh = conf_thresh

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
        i = 0

        pbar = tqdm(total=len(coords), desc="推理进度")

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            while i < len(coords):
                if cancel_check and cancel_check():
                    break

                batch_coords = coords[i : i + self._batch_size]
                i += len(batch_coords)

                batch_imgs = list(executor.map(self._reader.read, batch_coords))

                try:
                    results = self._adapter.predict(
                        batch_imgs, device=self._device, conf_thresh=self._conf_thresh
                    )
                except RuntimeError as e:
                    if self._batch_size <= 1:
                        raise RuntimeError("Batch Size 已降至 1 但显存仍不足") from e
                    if not any(kw in str(e).lower() for kw in ("out of memory", "oom", "memory")):
                        raise e
                    logger.warning("发生显存溢出 (OOM)，正在缩减 Batch Size 进行重试")
                    self._batch_size = max(1, self._batch_size // 2)
                    i -= len(batch_coords)
                    continue

                for j, (boxes, scores, classes) in enumerate(results):
                    coord = batch_coords[j]
                    X, Y = coord.x, coord.y
                    if len(boxes) == 0:
                        continue
                    for box, score, cls_id in zip(boxes, scores, classes):
                        lx1, ly1, lx2, ly2 = box
                        global_boxes.append([lx1 + X, ly1 + Y, lx2 + X, ly2 + Y])
                        global_scores.append(score)
                        global_classes.append(cls_id)

                processed += len(batch_coords)
                pbar.update(len(batch_coords))

                if progress_callback:
                    progress_callback(processed)

        pbar.close()
        return global_boxes, global_scores, global_classes, processed
