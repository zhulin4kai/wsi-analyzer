import concurrent.futures

import cv2
import numpy as np
from tqdm import tqdm

import config
from .image_server import ImageServer
from .model_adapters import ModelAdapterFactory
from .roi_manager import generate_roi_coordinates
from utils import logger
from utils import nms_numpy


class WSIAnalyzer:
    def __init__(
        self,
        svs_path,
        model_path,
        patch_size=512,
        stride=400,
        nms_iou_thresh=0.25,
        conf_thresh=0.5,
        device="cpu",
        batch_size=16,
    ):
        self.svs_path = svs_path

        self.patch_size = max(
            getattr(config, "AI_PATCH_SIZE_MIN", 128),
            min(patch_size, getattr(config, "AI_PATCH_SIZE_MAX", 4096)),
        )

        self.stride = max(
            getattr(config, "AI_STRIDE_MIN", 64),
            min(stride, getattr(config, "AI_STRIDE_MAX", 4096)),
        )

        if self.stride > self.patch_size:
            logger.warning(
                f"自动纠正: 步长 ({self.stride}) 大于切片尺寸 ({self.patch_size})，已修改为 {self.patch_size}。"
            )
            self.stride = self.patch_size

        self.nms_iou_thresh = max(
            getattr(config, "AI_NMS_IOU_THRESH_MIN", 0.01),
            min(nms_iou_thresh, getattr(config, "AI_NMS_IOU_THRESH_MAX", 1.0)),
        )

        self.conf_thresh = max(
            getattr(config, "AI_CONF_THRESH_MIN", 0.01),
            min(conf_thresh, getattr(config, "AI_CONF_THRESH_MAX", 1.0)),
        )

        self.device = device
        self.batch_size = min(
            batch_size, getattr(config, "BATCH_SIZE_CAP_NVME_SSD", 64)
        )

        logger.info(f"[*] 使用计算设备: {self.device}, Batch Size: {self.batch_size}")

        self._is_cancelled = False

        logger.info(f"[*] 正在加载模型: {model_path}")
        self.model_adapter = ModelAdapterFactory.create_adapter(model_path)

        logger.info(f"[*] 正在打开 WSI 文件: {svs_path}")
        self.slide_engine = ImageServer.instance().acquire_engine(svs_path)
        self.level_0_dim = self.slide_engine.level_0_dim

    def cancel(self):
        """中止当前的分析任务"""
        self._is_cancelled = True
        logger.info("[*] 收到中止信号，退出推断循环...")

    def _generate_solid_mask(self, target_level=None):
        if target_level is None:
            target_level = getattr(config, "AI_MASK_TARGET_LEVEL", 3)
        level, dim, downsample_factor = self.slide_engine.get_level_info(target_level)
        thumb_rgba = self.slide_engine.read_region((0, 0), level, dim)
        thumb_rgb = np.array(thumb_rgba.convert("RGB"))
        gray = cv2.cvtColor(thumb_rgb, cv2.COLOR_RGB2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        binary_cleaned = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

        contours, _ = cv2.findContours(
            binary_cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        solid_mask = np.zeros_like(gray)

        # 过滤掉极小面积的斑点 (默认 0.1%)
        total_area = gray.shape[0] * gray.shape[1]
        min_area = total_area * getattr(config, "AI_MIN_AREA_RATIO", 0.001)

        valid_contours = [cnt for cnt in contours if cv2.contourArea(cnt) > min_area]
        cv2.drawContours(solid_mask, valid_contours, -1, 255, thickness=-1)

        return solid_mask, downsample_factor

    def _generate_patch_coordinates(self, solid_mask, downsample_factor):
        W, H = self.level_0_dim
        valid_coords = []
        # +1 确保末行/末列切片不被 range 截断（修复 Off-by-One）
        for y in range(0, H - self.patch_size + 1, self.stride):
            for x in range(0, W - self.patch_size + 1, self.stride):
                cx_level0 = x + self.patch_size / 2
                cy_level0 = y + self.patch_size / 2
                mask_x = min(
                    max(int(cx_level0 / downsample_factor), 0), solid_mask.shape[1] - 1
                )
                mask_y = min(
                    max(int(cy_level0 / downsample_factor), 0), solid_mask.shape[0] - 1
                )

                if solid_mask[mask_y, mask_x] == 255:
                    valid_coords.append((x, y))
        return valid_coords

    def _batch_inference(
        self,
        valid_coords,
        total_patches=0,
        processed_patches=0,
        progress_callback=None,
    ):
        global_boxes = []
        global_scores = []
        global_classes = []
        current_processed = 0

        # 动态组装批次
        i = 0
        pbar = tqdm(total=len(valid_coords), desc="推理进度")

        # 线程池在整个推理过程中复用，避免每批次重建/销毁的开销
        # fetch_patch 只引用 self，在循环外定义一次即可
        def fetch_patch(coord):
            x_min, y_min = coord
            patch_rgba = self.slide_engine.read_region(
                (x_min, y_min), 0, (self.patch_size, self.patch_size)
            )
            return patch_rgba.convert("RGB")

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            while i < len(valid_coords):
                if self._is_cancelled:
                    break

                batch_coords = valid_coords[i : i + self.batch_size]
                i += len(batch_coords)

                # 并发读取当前批次图像
                batch_imgs = list(executor.map(fetch_patch, batch_coords))

                try:
                    results = self.model_adapter.predict(
                        batch_imgs, device=self.device, conf_thresh=self.conf_thresh
                    )
                except RuntimeError as e:
                    # 捕获 OOM 异常并执行降级重试
                    if (
                        "out of memory" in str(e).lower()
                        or "oom" in str(e).lower()
                        or "memory" in str(e).lower()
                    ):
                        # batch_size 已降至 1 时无法再缩减，直接抛出避免无限循环
                        if self.batch_size <= 1:
                            logger.error("Batch Size 已降至 1 但显存仍不足，终止推理。")
                            raise RuntimeError(
                                "显存不足且 Batch Size 已降至最小值 (1)，无法继续推理。"
                                "请减小图块尺寸或释放显存后重试。"
                            ) from e
                        logger.warning(
                            "发生显存溢出 (OOM)，正在缩减 Batch Size 进行重试"
                        )
                        self.batch_size = max(1, self.batch_size // 2)
                        # 回退指针，重新处理当前批次
                        i -= len(batch_coords)
                        continue
                    else:
                        raise e

                for j, (boxes, scores, classes) in enumerate(results):
                    X_min, Y_min = batch_coords[j]
                    if len(boxes) == 0:
                        continue

                    for box, score, cls_id in zip(boxes, scores, classes):
                        loc_x1, loc_y1, loc_x2, loc_y2 = box
                        global_boxes.append(
                            [
                                loc_x1 + X_min,
                                loc_y1 + Y_min,
                                loc_x2 + X_min,
                                loc_y2 + Y_min,
                            ]
                        )
                        global_scores.append(score)
                        global_classes.append(cls_id)

                current_processed += len(batch_coords)
                pbar.update(len(batch_coords))

                # 触发进度条更新
                if progress_callback and total_patches > 0:
                    progress_percent = int(
                        (processed_patches + current_processed) / total_patches * 100
                    )
                    progress_callback(progress_percent)

        pbar.close()
        return global_boxes, global_scores, global_classes, current_processed

    def _apply_global_nms(self, global_boxes, global_scores, global_classes):
        if len(global_boxes) == 0:
            return []

        boxes_arr = np.array(global_boxes, dtype=np.float32)
        scores_arr = np.array(global_scores, dtype=np.float32)
        classes_arr = np.array(global_classes)

        keep_indices = nms_numpy(boxes_arr, scores_arr, self.nms_iou_thresh)

        return [
            {
                "bbox": [round(float(b), 2) for b in boxes_arr[idx]],
                "confidence": round(float(scores_arr[idx]), 4),
                "class_id": int(classes_arr[idx]),
            }
            for idx in keep_indices
        ]

    def process(
        self,
        resume_data=None,
        progress_callback=None,
        status_callback=None,
        roi_bbox=None,
    ):
        """处理推理逻辑并通过回调更新状态"""
        self._is_cancelled = False

        global_boxes = []
        global_scores = []
        global_classes = []
        valid_coords = []
        processed_patches = 0

        if roi_bbox:
            if status_callback:
                status_callback("阶段 1/2: 正在提取组织掩码并计算 ROI 靶向分析坐标...")

            solid_mask, downsample_factor = self._generate_solid_mask(
                target_level=getattr(config, "AI_MASK_TARGET_LEVEL", 3)
            )
            roi_stride = int(self.patch_size * getattr(config, "ROI_STRIDE_RATIO", 0.5))
            W, H = self.level_0_dim
            valid_coords = generate_roi_coordinates(
                roi_bbox,
                self.patch_size,
                roi_stride,
                W,
                H,
                solid_mask=solid_mask,
                downsample_factor=downsample_factor,
            )
        elif resume_data and resume_data.get("valid_coords"):
            if status_callback:
                status_callback("阶段 1/4: 发现断点缓存，跳过掩码生成...")
            valid_coords = resume_data["valid_coords"]
            processed_patches = resume_data.get("processed_patches", 0)

            # 优先使用未经 NMS 的原始框，确保续传时全局 NMS 可基于完整信息重算
            if "raw_boxes" in resume_data:
                global_boxes = list(resume_data["raw_boxes"])
                global_scores = list(resume_data["raw_scores"])
                global_classes = list(resume_data["raw_classes"])
            else:
                # 兼容旧格式：从 post-NMS 结果中重建（跨批 NMS 精度略有损失）
                for r in resume_data.get("results", []):
                    global_boxes.append(r["bbox"])
                    global_scores.append(r["confidence"])
                    global_classes.append(r["class_id"])
        else:
            if status_callback:
                status_callback("阶段 1/4: 正在提取宏观图像与生成组织掩码...")
            solid_mask, downsample_factor = self._generate_solid_mask(
                target_level=getattr(config, "AI_MASK_TARGET_LEVEL", 3)
            )

            if self._is_cancelled:
                return {
                    "status": "interrupted",
                    "results": [],
                    "valid_coords": [],
                    "processed_patches": 0,
                    "total_patches": 0,
                }

            if status_callback:
                status_callback("阶段 2/4: 正在计算有效滑动窗口坐标...")
            valid_coords = self._generate_patch_coordinates(
                solid_mask, downsample_factor
            )

        if not valid_coords:
            msg = "未提取到有效的组织区域。"
            if status_callback:
                status_callback(f"错误: {msg}")
            return {
                "status": "error",
                "message": msg,
                "results": [],
                "valid_coords": [],
                "processed_patches": 0,
                "total_patches": 0,
            }

        max_patches = getattr(config, "AI_MAX_PATCHES_LIMIT", 100000)
        if len(valid_coords) > max_patches:
            msg = (
                f"提取的图像块过多 ({len(valid_coords)} > {max_patches})，"
                "请检查并调大滑动步长。"
            )
            logger.warning(
                f"生成的图块数量 ({len(valid_coords)}) 超过安全上限 ({max_patches})！"
            )
            if status_callback:
                status_callback(f"错误: {msg}")
            return {
                "status": "error",
                "message": msg,
                "results": [],
                "valid_coords": [],
                "processed_patches": 0,
                "total_patches": 0,
            }

        total_patches = len(valid_coords)
        remaining_coords = valid_coords[processed_patches:]

        if status_callback:
            phase_str = "阶段 2/2" if roi_bbox else "阶段 3/4"
            status_callback(
                f"{phase_str}: 开始模型推理 (共 {total_patches} 个图像块，剩余 {len(remaining_coords)} 个)..."
            )

        new_boxes, new_scores, new_classes, current_processed = self._batch_inference(
            remaining_coords,
            total_patches=total_patches,
            processed_patches=processed_patches,
            progress_callback=progress_callback,
        )

        global_boxes.extend(new_boxes)
        global_scores.extend(new_scores)
        global_classes.extend(new_classes)

        final_processed = processed_patches + current_processed

        if self._is_cancelled:
            if status_callback:
                status_callback("阶段 4/4: 分析被中断，正在保存当前进度...")
            final_results = self._apply_global_nms(
                global_boxes, global_scores, global_classes
            )
            return {
                "status": "interrupted",
                "results": final_results,
                # 保存原始框，续传时全局 NMS 可基于完整 pre-NMS 数据重算
                "raw_boxes": global_boxes,
                "raw_scores": global_scores,
                "raw_classes": global_classes,
                "valid_coords": valid_coords,
                "processed_patches": final_processed,
                "total_patches": total_patches,
            }

        final_results = self._apply_global_nms(
            global_boxes, global_scores, global_classes
        )

        if status_callback:
            status_callback(f"分析完成！共检测到 {len(final_results)} 个病灶。")
        return {
            "status": "completed",
            "results": final_results,
            "valid_coords": valid_coords,
            "processed_patches": final_processed,
            "total_patches": total_patches,
        }

    def close(self):
        """释放引擎引用和模型资源。"""
        if hasattr(self, "slide_engine") and self.slide_engine is not None:
            ImageServer.instance().release_engine(self.svs_path)
            self.slide_engine = None
        if hasattr(self, "model_adapter") and self.model_adapter is not None:
            del self.model_adapter
            self.model_adapter = None
