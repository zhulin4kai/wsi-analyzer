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
    负责在 AI 分析完成后，或者加载已有数据时，安全静默地截取高危病灶的上下文缩略图。
    """

    # 信号定义：
    # thumb_ready: 抛出 (排名索引, QImage 图块, 病灶原始字典数据)
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
        :param top_results: 经过排序截断的 top-K 病灶数据列表
        :param target_size: 最终显示在 UI 上的小图尺寸 (128x128)
        :param context_size: 从 Level 0 截取的实际视野大小 (256x256)，确保病灶周围有足够的组织上下文
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
            # 核心安全机制：在子线程中独立打开一个新的文件句柄
            # 彻底隔离主线程的渲染 I/O，避免 OpenSlide 等底层 C 库在并发读图时发生死锁或花屏
            engine = WSIDataEngine(self.wsi_path)

            # 获取切片的真实宽高，防止截取越界
            # 兼容不同写法的 engine，可能是 engine.dimensions 或 engine.slide.dimensions
            if hasattr(engine, "dimensions"):
                max_w, max_h = engine.dimensions
            elif hasattr(engine, "slide") and hasattr(engine.slide, "dimensions"):
                max_w, max_h = engine.slide.dimensions
            else:
                # 兜底：如果获取不到边界，给一个极大的值，依靠底层库自己的越界保护
                max_w, max_h = 1000000, 1000000

            for idx, item in enumerate(self.top_results):
                # 检查中断标志（如果医生切换了切片，立刻停止无意义的切图）
                if self._is_cancelled:
                    logger.info("GalleryWorker 收到中断信号，已安全退出。")
                    break

                b = item["bbox"]
                # 计算病灶的绝对物理中心点
                cx = (b[0] + b[2]) // 2
                cy = (b[1] + b[3]) // 2

                # 动态计算上下文大小，确保病灶完全包含且不会过度缩放导致模糊
                bw, bh = b[2] - b[0], b[3] - b[1]
                dynamic_context = max(self.target_size, int(max(bw, bh) * 1.5))

                # 计算带有上下文 (Context) 的截取区域左上角
                # 保证病灶位于截取框正中心
                start_x = max(0, int(cx - dynamic_context / 2))
                start_y = max(0, int(cy - dynamic_context / 2))

                # 防止越界到右侧或下侧外
                read_w = min(dynamic_context, max_w - start_x)
                read_h = min(dynamic_context, max_h - start_y)

                # 提取 Level 0 高清像素 (使用底层的 read_region)
                # 注意：不同封装库可能直接挂在 engine 下，或 engine.slide 下
                if hasattr(engine, "read_region"):
                    region = engine.read_region((start_x, start_y), 0, (read_w, read_h))
                else:
                    region = engine.slide.read_region(
                        (start_x, start_y), 0, (read_w, read_h)
                    )

                # 统一转为 RGB 丢弃可能导致渲染异常的 Alpha 通道
                if region.mode != "RGB":
                    region = region.convert("RGB")

                # 如果因为贴近边缘导致提取的图像尺寸不足，创建一个纯白背景进行垫底居中
                if read_w != dynamic_context or read_h != dynamic_context:
                    bg = Image.new(
                        "RGB", (dynamic_context, dynamic_context), (255, 255, 255)
                    )
                    bg.paste(region, (0, 0))
                    region = bg

                # 缩小到 UI 的目标尺寸 (128x128)，极大减少 UI 层的显存/内存占用
                resample_filter = getattr(Image, "Resampling", Image).LANCZOS
                thumb = region.resize(
                    (self.target_size, self.target_size), resample_filter
                )

                # 转为 QImage 并深拷贝 (copy)
                # 极为关键：必须深拷贝，防止 Python 垃圾回收机制回收 PIL Image 后，
                # 导致 PyQt 底层的 C++ 指针悬空而引发随机崩溃 (Segfault)
                qimg = ImageQt(thumb).copy()

                # 将截取好的小图，连同它原本的数据（如置信度、中心坐标）通过信号抛给 UI 主线程
                self.thumb_ready.emit(idx, qimg, item)

            if not self._is_cancelled:
                self.finished_all.emit()

        except Exception as e:
            logger.error(f"GalleryWorker 切图发生异常: {e}")
            logger.error(traceback.format_exc())
            self.error_occurred.emit(str(e))

        finally:
            # 释放独立的文件句柄，防止内存和系统句柄耗尽 (Handle Leak)
            if engine:
                try:
                    if hasattr(engine, "close"):
                        engine.close()
                    elif hasattr(engine, "slide") and hasattr(engine.slide, "close"):
                        engine.slide.close()
                except Exception:
                    pass

    def cancel(self):
        """安全中断切图任务"""
        self._is_cancelled = True
