import multiprocessing
import sys
from queue import Empty
from typing import Callable

from .splash_ui import SplashUI


class AppLauncher:
    """
    应用程序启动器。
    """

    def __init__(
        self,
        image_path: str,
        heavy_task_func: Callable[[multiprocessing.Event, multiprocessing.Queue], None],
        width: int = 640,
        height: int = 360,
    ):
        """
        :param image_path: 启动画面图像的路径。
        :param heavy_task_func: 子进程的目标函数。
                                必须接受 (ready_event, msg_queue) 作为参数。
        :param width: 启动画面宽度。
        :param height: 启动画面高度。
        """
        self.image_path = image_path
        self.heavy_task_func = heavy_task_func
        self.width = width
        self.height = height

        # 进程间通信 (IPC) 对象
        self.ready_event = multiprocessing.Event()
        self.msg_queue = multiprocessing.Queue()

        self.process = None
        self.splash = None

    def _monitor_child(self):
        """
        在Tkinter主循环中定期运行，以检查子进程的状态。
        """
        if not self.splash:
            return

        # 1. 提取消息队列以获取动态状态更新
        while not self.msg_queue.empty():
            try:
                msg = self.msg_queue.get_nowait()
                self.splash.update_text(msg)
            except Empty:
                pass

        # 2. 检查Qt是否完全加载并渲染完成
        if self.ready_event.is_set():
            self.splash.close()
            return

        # 3. 检查子进程是否发生意外崩溃
        if self.process and not self.process.is_alive():
            print(f"启动器：子进程意外终止，退出码为 {self.process.exitcode}。")
            self.splash.close()
            return

        # 4. 50毫秒后再次循环检查
        self.splash.schedule_task(50, self._monitor_child)

    def run(self):
        """
        执行完整的启动序列。
        """
        try:
            multiprocessing.set_start_method("spawn", force=True)
        except RuntimeError:
            pass  # 已在其他地方设置过

        self.splash = SplashUI(self.image_path, self.width, self.height)

        self.process = multiprocessing.Process(
            target=self.heavy_task_func, args=(self.ready_event, self.msg_queue)
        )
        self.process.start()
        self.splash.schedule_task(50, self._monitor_child)
        self.splash.run()

        if self.process.is_alive():
            self.process.join()

        if self.process.exitcode is not None and self.process.exitcode != 0:
            print(f"应用程序异常终止，退出码：{self.process.exitcode}")
            sys.exit(self.process.exitcode)

        sys.exit(0)
