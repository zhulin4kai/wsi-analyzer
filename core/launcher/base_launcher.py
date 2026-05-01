import multiprocessing
import sys
from typing import Callable

from .splash_ui import SplashUI


class AppLauncher:
    """
    工业级应用程序启动器。

    实现了“启动器模式 / 角色反转”：
    1. 在主进程中瞬间显示轻量级的Tkinter UI。
    2. 派生后台工作子进程用于执行繁重的导入与加载（如Qt、数据库、AI模型）。
    3. 通过IPC队列和事件监控加载状态。
    4. 在后台应用完全渲染后无缝移交控制权。
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
            except Exception:
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
        # 0. 强制使用 spawn 方式启动子进程，避免 Linux/macOS 默认 fork
        #    因 PySide6/Qt 在 fork 后会导致段错误
        try:
            multiprocessing.set_start_method("spawn", force=True)
        except RuntimeError:
            pass  # 已在其他地方设置过

        # 1. 瞬间构建并显示可视化的启动UI
        self.splash = SplashUI(self.image_path, self.width, self.height)

        # 2. 在独立的子进程中启动繁重的后台任务
        self.process = multiprocessing.Process(
            target=self.heavy_task_func, args=(self.ready_event, self.msg_queue)
        )
        self.process.start()

        # 3. 开始监控Qt应用程序的加载状态
        self.splash.schedule_task(50, self._monitor_child)

        # 4. 进入Tkinter的阻塞主循环（保证UI不会出现未响应）
        self.splash.run()

        # 5. 启动画面关闭后，主进程作为幽灵守护进程在后台运行，
        # 等待用户关闭主Qt应用程序。
        if self.process.is_alive():
            self.process.join()

        # 6. 传递并继承退出码
        if self.process.exitcode is not None and self.process.exitcode != 0:
            print(f"应用程序异常终止，退出码：{self.process.exitcode}")
            sys.exit(self.process.exitcode)

        sys.exit(0)
