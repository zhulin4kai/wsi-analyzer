import sys
from PySide6.QtWidgets import QApplication

from utils import logger
# 初始化环境，挂载DLL
from utils.file_helper import setup_environment
setup_environment()

from gui.main_window import MainWindow

if __name__ == "__main__":
    logger.info("========== 智能病理辅助诊断系统启动 ==========")
    app = QApplication(sys.argv)

    window = MainWindow()
    window.show()

    exit_code = app.exec()
    logger.info(f"========== 系统正常退出，退出码: {exit_code} ==========")

    sys.exit(app.exec())