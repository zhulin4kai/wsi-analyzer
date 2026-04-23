import multiprocessing
import os
import sys


def run_qt_app(ready_event: multiprocessing.Event):
    """
    子进程入口：负责加载所有重量级框架（Qt、数据库、AI模型等）。
    不会阻塞主进程中贴图的显示。
    """
    # 延迟导入重量级模块
    from PySide6.QtWidgets import QApplication

    from gui.main_window import MainWindow
    from utils import logger
    from utils.db_manager import DatabaseManager

    logger.info("========== 智能病理辅助诊断系统启动 ==========")

    # 初始化本地数据库等耗时操作
    DatabaseManager()

    # 启动QtApplication
    app = QApplication(sys.argv)

    window = MainWindow()
    window.show()

    # 强制处理Qt的挂起事件，确保主界面真正渲染到屏幕上
    app.processEvents()

    # 触发交接信号：告诉主进程Qt界面已经准备好，可以关掉贴图了
    ready_event.set()

    # 正式进入主程序Qt事件循环
    exit_code = app.exec()
    logger.info(f"========== 系统正常退出，退出码: {exit_code} ==========")

    sys.exit(exit_code)


def main():
    # 1. 创建跨进程事件，用于监控Qt加载状态
    app_ready_event = multiprocessing.Event()

    # 2. 在后台静默拉起子进程执行重量级加载
    qt_process = multiprocessing.Process(target=run_qt_app, args=(app_ready_event,))
    qt_process.start()

    # 3. 主进程毫秒级瞬间拉起Tkinter贴图，实现“点击即显示”
    splash_image_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "splash.png"
    )
    from gui.widgets.splash_screen import TkSplashScreen

    splash = TkSplashScreen(splash_image_path, width=640, height=360)

    # 4. 设置定时轮询：监控子进程是否发出了“绿灯”信号
    def check_if_ready():
        # 如果绿灯亮了，或者Qt子进程意外崩溃了
        if app_ready_event.is_set() or not qt_process.is_alive():
            splash.close()
        else:
            # 否则过 50ms 后再次检查
            splash.root.after(50, check_if_ready)

    if splash.root:
        splash.root.after(50, check_if_ready)
        # 进入Tkinter主循环，保证贴图在后台高负载时永不假死（无未响应）
        splash.run()

    # 5. 贴图关闭后，主进程在此默默等待用户关闭Qt主窗口
    qt_process.join()


if __name__ == "__main__":
    # Windows下使用multiprocessing必备，防止打包exe后无限创建子进程灾难
    multiprocessing.freeze_support()
    main()
