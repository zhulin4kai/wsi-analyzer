import traceback

from PIL import Image
from PIL.ImageQt import ImageQt
from PySide6.QtCore import QThread, Signal

# 假设这些是项目中已有的核心组件路径
from core.slide_engine import WSIDataEngine
from utils import logger


class GalleryWorker(QThread):
    """
    后台异步病灶缩略图截取线程。
    负责截取病灶的上下文缩略图。
    """

    # 信号定义：
    # thumb_ready: 发送 (排名索引, QImage 图块, 病灶原始字典数据)
    thumb_ready = Signal(int, object, dict)
    finished_all = Signal()
    error_occurred = Signal(str)

    def __init__(
        self,
        wsi_path: str,
        top_results: list,
        target_size: int = 128,
        context_size: int = 256,
    ):
        """
        :param wsi_path: 切片的绝对路径，用于开启独立的文件句柄
        :param top_results: 排序后的 top-K 病灶数据列表
        :param target_size: 最终显示在 UI 上的小图尺寸 (128x128)
        :param context_size: 截取的视野大小 (256x256)，保留病灶周围的组织上下文
        """
        super().__init__()
        self.wsi_path = wsi_path
        self.top_results = top_results
        self.target_size = target_size
        self.context_size = context_size
        self._is_cancelled = False

    def run(self):
        engine = None
        try:
            # 在子线程中独立打开文件句柄，隔离主线程的渲染 I/O，避免并发读图时发生异常
            engine = WSIDataEngine(self.wsi_path)

            # 获取切片宽高，防止截取越界
            # 兼容不同的 engine 属性
            if hasattr(engine, "dimensions"):
                max_w, max_h = engine.dimensions
            elif hasattr(engine, "slide") and hasattr(engine.slide, "dimensions"):
                max_w, max_h = engine.slide.dimensions
            else:
                # 未获取到边界时分配默认极大值，依靠底层库处理越界
                max_w, max_h = 1000000, 1000000

            for idx, item in enumerate(self.top_results):
                # 检查中断标志
                if self._is_cancelled:
                    logger.info("GalleryWorker 收到中断信号，已退出。")
                    break

                b = item["bbox"]
                # 计算病灶的绝对物理中心点
                cx = (b[0] + b[2]) // 2
                cy = (b[1] + b[3]) // 2

                # 动态计算上下文大小
                bw, bh = b[2] - b[0], b[3] - b[1]
                dynamic_context = max(self.target_size, int(max(bw, bh) * 1.5))

                # 计算截取区域左上角，使病灶位于截取框中心
                start_x = max(0, int(cx - dynamic_context / 2))
                start_y = max(0, int(cy - dynamic_context / 2))

                # 防止越界
                read_w = min(dynamic_context, max_w - start_x)
                read_h = min(dynamic_context, max_h - start_y)

                # 提取 Level 0 像素 (使用 read_region)
                # 兼容不同封装库调用方式
                if hasattr(engine, "read_region"):
                    region = engine.read_region((start_x, start_y), 0, (read_w, read_h))
                else:
                    region = engine.slide.read_region(
                        (start_x, start_y), 0, (read_w, read_h)
                    )

                # 统一转为 RGB 丢弃 Alpha 通道
                if region.mode != "RGB":
                    region = region.convert("RGB")

                # 如果提取的图像尺寸不足，创建纯白背景居中填充
                if read_w != dynamic_context or read_h != dynamic_context:
                    bg = Image.new(
                        "RGB", (dynamic_context, dynamic_context), (255, 255, 255)
                    )
                    bg.paste(region, (0, 0))
                    region = bg

                # 缩放至 UI 目标尺寸 (128x128)，减少资源占用
                resample_filter = getattr(Image, "Resampling", Image).LANCZOS
                thumb = region.resize(
                    (self.target_size, self.target_size), resample_filter
                )

                # 转为 QImage 并深拷贝 (copy)，防止 PIL Image 被回收后导致指针悬空崩溃
                qimg = ImageQt(thumb).copy()

                # 将缩略图及附加数据通过信号发送给 UI 线程
                self.thumb_ready.emit(idx, qimg, item)

            if not self._is_cancelled:
                self.finished_all.emit()

        except Exception as e:
            logger.error(f"GalleryWorker 切图发生异常: {e}")
            logger.error(traceback.format_exc())
            self.error_occurred.emit(str(e))

        finally:
            # 释放文件句柄，防止资源泄漏
            if engine:
                try:
                    if hasattr(engine, "close"):
                        engine.close()
                    elif hasattr(engine, "slide") and hasattr(engine.slide, "close"):
                        engine.slide.close()
                except Exception:
                    pass

    def cancel(self):
        """中断切图任务"""
        self._is_cancelled = True
