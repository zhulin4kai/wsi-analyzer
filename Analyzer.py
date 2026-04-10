import json

import cv2
import numpy as np
import openslide
import torch
import torchvision
from tqdm import tqdm
from ultralytics import YOLO


class WSIAnalyzer:
    def __init__(self, svs_path, model_path, patch_size=512, stride=400, batch_size=32, nms_iou_thresh=0.3, conf_thresh=0.5):
        self.svs_path = svs_path
        self.patch_size = patch_size
        self.stride = stride
        self.batch_size = batch_size
        self.nms_iou_thresh = nms_iou_thresh
        self.conf_thresh = conf_thresh

        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        print(f"[*] 使用计算设备: {self.device}")

        # 加载 YOLO 模型
        print(f"[*] 正在加载 YOLOv8 模型: {model_path}")
        self.model = YOLO(model_path)

        # 加载 WSI 图像（后台线程独立句柄）
        print(f"[*] 正在打开 WSI 文件: {svs_path}")
        self.slide = openslide.OpenSlide(svs_path)
        self.level_0_dim = self.slide.level_dimensions[0]

    def _generate_solid_mask(self, target_level=3):
        level = min(target_level, self.slide.level_count - 1)
        downsample_factor = self.slide.level_downsamples[level]
        dim = self.slide.level_dimensions[level]

        thumb_rgba = self.slide.read_region((0, 0), level, dim)
        thumb_rgb = np.array(thumb_rgba.convert('RGB'))
        gray = cv2.cvtColor(thumb_rgb, cv2.COLOR_RGB2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
        
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        binary_cleaned = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
        
        contours, _ = cv2.findContours(binary_cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        solid_mask = np.zeros_like(gray)

        # 过滤掉小于 0.1% 面积的斑点
        total_area = gray.shape[0] * gray.shape[1]
        min_area = total_area * 0.001

        valid_contours = [cnt for cnt in contours if cv2.contourArea(cnt) > min_area]
        cv2.drawContours(solid_mask, valid_contours, -1, 255, thickness=-1)

        return solid_mask, downsample_factor

    def _generate_patch_coordinates(self, solid_mask, downsample_factor):
        W, H = self.level_0_dim
        valid_coords =[]
        for y in range(0, H - self.patch_size, self.stride):
            for x in range(0, W - self.patch_size, self.stride):
                cx_level0 = x + self.patch_size / 2
                cy_level0 = y + self.patch_size / 2
                mask_x = min(max(int(cx_level0 / downsample_factor), 0), solid_mask.shape[1] - 1)
                mask_y = min(max(int(cy_level0 / downsample_factor), 0), solid_mask.shape[0] - 1)

                if solid_mask[mask_y, mask_x] == 255:
                    valid_coords.append((x, y))
        return valid_coords

    def _batch_inference(self, valid_coords, progress_callback=None):
        global_boxes = []
        global_scores = []
        global_classes =[]

        batches = [valid_coords[i:i + self.batch_size] for i in range(0, len(valid_coords), self.batch_size)]
        
        # 遍历批次，并向外抛出进度
        for idx, batch_coords in enumerate(tqdm(batches, desc="推理进度")):
            batch_imgs =[]
            for (x_min, y_min) in batch_coords:
                patch_rgba = self.slide.read_region((x_min, y_min), 0, (self.patch_size, self.patch_size))
                batch_imgs.append(patch_rgba.convert('RGB'))

            results = self.model(batch_imgs, verbose=False, device=self.device, conf=self.conf_thresh)

            for i, result in enumerate(results):
                X_min, Y_min = batch_coords[i]
                if len(result.boxes) == 0:
                    continue

                boxes = result.boxes.xyxy.cpu().numpy()
                scores = result.boxes.conf.cpu().numpy()
                classes = result.boxes.cls.cpu().numpy()

                for box, score, cls_id in zip(boxes, scores, classes):
                    loc_x1, loc_y1, loc_x2, loc_y2 = box
                    global_boxes.append([loc_x1 + X_min, loc_y1 + Y_min, loc_x2 + X_min, loc_y2 + Y_min])
                    global_scores.append(score)
                    global_classes.append(cls_id)
            
            # 【核心修改】触发进度条更新
            if progress_callback:
                progress_percent = int((idx + 1) / len(batches) * 100)
                progress_callback(progress_percent)

        return global_boxes, global_scores, global_classes

    def _apply_global_nms(self, global_boxes, global_scores, global_classes):
        if len(global_boxes) == 0:
            return[]
        boxes_tensor = torch.tensor(global_boxes, dtype=torch.float32)
        scores_tensor = torch.tensor(global_scores, dtype=torch.float32)
        keep_indices = torchvision.ops.nms(boxes_tensor, scores_tensor, iou_threshold=self.nms_iou_thresh)
        
        final_results =[]
        for idx in keep_indices.cpu().numpy():
            final_results.append({
                "bbox":[round(float(b), 2) for b in global_boxes[idx]],
                "confidence": round(float(global_scores[idx]), 4),
                "class_id": int(global_classes[idx])
            })
        return final_results

    def process(self, output_json="result.json", progress_callback=None, status_callback=None):
        """新增 status_callback 用于给界面左下角的 StatusBar 汇报当前处于哪个阶段"""
        if status_callback: status_callback("阶段 1/4: 正在提取宏观图像与生成组织掩码...")
        solid_mask, downsample_factor = self._generate_solid_mask(target_level=3)

        if status_callback: status_callback("阶段 2/4: 正在计算有效滑动窗口坐标...")
        valid_coords = self._generate_patch_coordinates(solid_mask, downsample_factor)

        if not valid_coords:
            if status_callback: status_callback("错误: 未提取到有效的组织区域。")
            return None

        if status_callback: status_callback(f"阶段 3/4: 开始模型推理 (共 {len(valid_coords)} 个图像块)...")
        global_boxes, global_scores, global_classes = self._batch_inference(valid_coords, progress_callback)

        if status_callback: status_callback("阶段 4/4: 正在执行全局非极大值抑制 (NMS)...")
        final_results = self._apply_global_nms(global_boxes, global_scores, global_classes)

        with open(output_json, 'w', encoding='utf-8') as f:
            json.dump(final_results, f, ensure_ascii=False, indent=4)
        
        if status_callback: status_callback(f"分析完成！共检测到 {len(final_results)} 个病灶。")
        return final_results

    def close(self):
        """ 释放 OpenSlide 句柄和 GPU 显存"""
        if hasattr(self, 'slide') and self.slide is not None:
            self.slide.close()

        if torch.cuda.is_available():
            torch.cuda.empty_cache()