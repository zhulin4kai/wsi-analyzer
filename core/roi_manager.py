import numpy as np

import config
from utils import logger
from utils.nms import nms_numpy


class ROIManager:
    """
    管理感兴趣区域 (ROI) 的生成与数据融合操作。
    """

    @staticmethod
    def generate_roi_coordinates(
        roi_bbox,
        patch_size,
        stride,
        max_width,
        max_height,
        solid_mask=None,
        downsample_factor=1.0,
    ):
        """
        为特定的 ROI 边界框生成滑动窗口坐标。

        :param roi_bbox: Level 0 物理像素下的 (X_min, Y_min, X_max, Y_max) 元组
        :param patch_size: 提取图块的尺寸
        :param stride: 滑动窗口步长（对于 ROI 通常为密集步长）
        :param max_width: Level 0 下的最大 WSI 宽度
        :param max_height: Level 0 下的最大 WSI 高度
        :param solid_mask: 可选的组织掩码（与全图分析复用），用于过滤 ROI 内的非组织区域
        :param downsample_factor: 掩码相对于 Level 0 的降采样倍率
        :return: (x, y) 坐标元组的列表
        """
        x_min, y_min, x_max, y_max = roi_bbox

        # 强制执行边界约束
        x_min = max(0, int(x_min))
        y_min = max(0, int(y_min))
        x_max = min(max_width, int(x_max))
        y_max = min(max_height, int(y_max))

        if x_min >= x_max or y_min >= y_max:
            return []

        valid_coords = []

        for y in range(y_min, y_max, stride):
            for x in range(x_min, x_max, stride):
                # 确保图块不会超过绝对切片尺寸
                coord_x = (
                    min(x, max_width - patch_size) if x + patch_size > max_width else x
                )
                coord_y = (
                    min(y, max_height - patch_size)
                    if y + patch_size > max_height
                    else y
                )

                # 如果 patch_size > max_dimension，则防止出现负坐标
                coord_x = max(0, coord_x)
                coord_y = max(0, coord_y)

                # 若提供了组织掩码，则过滤掉非组织区域的图块
                if solid_mask is not None:
                    cx_level0 = coord_x + patch_size / 2
                    cy_level0 = coord_y + patch_size / 2
                    mask_x = min(
                        max(int(cx_level0 / downsample_factor), 0),
                        solid_mask.shape[1] - 1,
                    )
                    mask_y = min(
                        max(int(cy_level0 / downsample_factor), 0),
                        solid_mask.shape[0] - 1,
                    )
                    if solid_mask[mask_y, mask_x] != 255:
                        continue

                valid_coords.append((coord_x, coord_y))

        # 移除边缘潜在的重复项
        valid_coords = list(dict.fromkeys(valid_coords))

        return valid_coords

    @staticmethod
    def fuse_results(existing_results, new_results, nms_iou_thresh):
        """
        使用非极大值抑制 (NMS) 融合现有的全局结果与新的 ROI 结果，
        以消除重叠的边界框。

        :param existing_results: 包含现有推理结果的字典列表
        :param new_results: 包含新 ROI 推理结果的字典列表
        :param nms_iou_thresh: 用于 NMS 过滤的 IoU 阈值
        :return: 融合并过滤后的推理结果列表
        """
        combined_results = existing_results + new_results
        if not combined_results:
            return []

        boxes = np.array([r["bbox"] for r in combined_results], dtype=np.float32)
        scores = np.array([r["confidence"] for r in combined_results], dtype=np.float32)

        keep_indices = nms_numpy(boxes, scores, nms_iou_thresh)

        return [combined_results[idx] for idx in keep_indices]
