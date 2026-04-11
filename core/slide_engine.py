import openslide

class WSIDataEngine:
    """
    WSI 图像数据引擎：封装所有底层 OpenSlide 图片截取与金字塔层级计算逻辑。
    UI 层与算法层不直接操作 openslide，统一通过本引擎获取数据。
    """
    def __init__(self, file_path):
        self.file_path = file_path
        self.slide = openslide.OpenSlide(file_path)
        self.level_0_dim = self.slide.dimensions

    def get_thumbnail(self, level_from_last=1):
        """
        获取宏观底图（缩略图）
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

    def calculate_render_params(self, rect_left, rect_top, rect_width, rect_height, target_downsample):
        """
        根据当前视口请求，计算 OpenSlide 截取所需的全部参数
        :return: loc_x, loc_y, best_level, size_w, size_h, level_downsample
        """
        best_level = self.slide.get_best_level_for_downsample(target_downsample)
        level_downsample = self.slide.level_downsamples[best_level]

        loc_x = int(rect_left)
        loc_y = int(rect_top)
        size_w = int(rect_width / level_downsample)
        size_h = int(rect_height / level_downsample)

        return loc_x, loc_y, best_level, size_w, size_h, level_downsample

    def get_level_info(self, target_level):
        """为 AI 引擎提供指定层级的基本信息"""
        level = min(target_level, self.slide.level_count - 1)
        dim = self.slide.level_dimensions[level]
        downsample_factor = self.slide.level_downsamples[level]
        return level, dim, downsample_factor

    def read_region(self, location, level, size):
        """透传 OpenSlide 的读取功能（供多线程和 AI 使用）"""
        return self.slide.read_region(location, level, size)

    def close(self):
        self.slide.close()