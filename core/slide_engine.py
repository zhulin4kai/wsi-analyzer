from typing import Optional, Tuple

import openslide


class WSIDataEngine:
    """
    WSI 图像数据引擎：封装 OpenSlide 图像读取与金字塔层级计算逻辑。
    UI 层与算法层统一通过本引擎获取数据。
    """

    def __init__(self, file_path):
        self.file_path = file_path
        self.slide = openslide.OpenSlide(file_path)
        self.level_0_dim = self.slide.dimensions

    def get_thumbnail(self, level_from_last=1):
        """
        获取缩略图
        :param level_from_last: 1 表示最后一层(最小)，2 表示倒数第二层
        :return: (PIL.Image(RGB格式), downsample_factor)
        """
        level = max(0, self.slide.level_count - level_from_last)
        dim = self.slide.level_dimensions[level]

        # 读取并转为 RGB
        thumb_rgba = self.slide.read_region((0, 0), level, dim)
        thumb_img = thumb_rgba.convert("RGB")

        # 计算该层到 Level 0 的降采样率
        downsample_factor = self.level_0_dim[0] / dim[0]

        return thumb_img, downsample_factor

    def get_level_info(self, target_level):
        """为 AI 引擎提供指定层级的基本信息"""
        level = min(target_level, self.slide.level_count - 1)
        dim = self.slide.level_dimensions[level]
        downsample_factor = self.slide.level_downsamples[level]
        return level, dim, downsample_factor

    def read_region(self, location, level, size):
        """提供 OpenSlide 的读取接口"""
        return self.slide.read_region(location, level, size)

    def get_mpp(self) -> Optional[Tuple[float, float]]:
        """
        返回切片的物理分辨率 (mpp_x, mpp_y)，单位：微米/像素 (μm/px)。
        若元数据缺失则返回 None。
        """
        try:
            mpp_x = float(self.slide.properties.get(openslide.PROPERTY_NAME_MPP_X, 0))
            mpp_y = float(self.slide.properties.get(openslide.PROPERTY_NAME_MPP_Y, 0))
            if mpp_x > 0 and mpp_y > 0:
                return mpp_x, mpp_y
        except (ValueError, TypeError):
            pass
        return None

    def get_objective_power(self) -> Optional[float]:
        """
        返回切片的物镜倍率（如 20.0、40.0）。
        若元数据缺失则返回 None。
        """
        try:
            power = self.slide.properties.get(
                openslide.PROPERTY_NAME_OBJECTIVE_POWER, None
            )
            if power is not None:
                return float(power)
        except (ValueError, TypeError):
            pass
        return None

    def close(self):
        self.slide.close()
