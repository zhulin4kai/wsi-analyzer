import multiprocessing
import os
import sys

from core.launcher import AppLauncher


def run_qt_app(ready_event: multiprocessing.Event, msg_queue: multiprocessing.Queue):
    """
    子进程入口：负责加载所有重量级框架（Qt、数据库、AI模型等）。
    通过 msg_queue 实时汇报加载进度给启动器的贴图界面。
    """
    msg_queue.put("正在加载核心框架...")
    from PySide6.QtWidgets import QApplication

    from gui.main_window import MainWindow
    from utils import logger
    from utils.db_manager import DatabaseManager

    logger.info("========== 智能病理辅助诊断系统启动 ==========")

    msg_queue.put("正在初始化数据库...")
    DatabaseManager()

    msg_queue.put("正在启动图形界面引擎...")
    app = QApplication(sys.argv)

    msg_queue.put("正在构建主窗口...")
    window = MainWindow()
    window.show()

    msg_queue.put("正在完成最终渲染...")
    app.processEvents()

    # 触发交接信号：告诉主进程Qt界面已经真正绘制完毕，可以安全关掉贴图了
    ready_event.set()

    # 正式进入主程序Qt事件循环
    exit_code = app.exec()
    logger.info(f"========== 系统正常退出，退出码: {exit_code} ==========")

    sys.exit(exit_code)


def main():
    # 获取贴图路径 (支持 assets 资源目录与根目录回退)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    splash_image_path = os.path.join(base_dir, "assets", "splash.png")
    if not os.path.exists(splash_image_path):
        splash_image_path = os.path.join(base_dir, "splash.png")

    # 实例化工业级启动器，传入UI参数与核心后台任务
    launcher = AppLauncher(
        image_path=splash_image_path, heavy_task_func=run_qt_app, width=640, height=360
    )

    # 阻塞并接管整个软件的启动生命周期
    launcher.run()


if __name__ == "__main__":
    # Windows下打包exe防多进程炸弹必备
    multiprocessing.freeze_support()
    main()
