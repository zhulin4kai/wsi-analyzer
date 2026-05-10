# wsi_analyzer/app/bootstrap.py

from __future__ import annotations

import os
import sys
import multiprocessing

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from wsi_analyzer.app.dependency_container import container
from wsi_analyzer.infrastructure.logging import logger
from wsi_analyzer.ui.main_window import MainWindow


def run_qt_app(
    ready_event: multiprocessing.Event,
    msg_queue: multiprocessing.Queue,
) -> None:
    msg_queue.put("正在加载核心框架...")

    logger.info("========== 智能病理辅助诊断系统启动 ==========")

    msg_queue.put("正在初始化数据库...")
    _ = container.database  # trigger singleton init

    msg_queue.put("正在启动图形界面引擎...")
    app = QApplication(sys.argv)

    _configure_windows_app_id()
    _configure_app_icon(app)

    msg_queue.put("正在构建主窗口...")
    window = MainWindow()
    window.show()

    msg_queue.put("正在完成最终渲染...")
    app.processEvents()
    ready_event.set()

    exit_code = app.exec()
    logger.info(f"========== 系统正常退出，退出码: {exit_code} ==========")

    container.image_server.shutdown()
    sys.exit(exit_code)


def _configure_windows_app_id() -> None:
    if os.name != "nt":
        return
    import ctypes
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "wsianalyzer.app.v0.0.1"
        )
    except Exception:
        pass


def _configure_app_icon(app: QApplication) -> None:
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    icon_path = os.path.join(base_dir, "assets", "app_icon.ico")
    if not os.path.exists(icon_path):
        icon_path = os.path.join(base_dir, "app_icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
