import sys
from PySide6.QtWidgets import QApplication

# 1. 初始化环境，挂载DLL
from utils.file_helper import setup_environment
setup_environment()

# 2. 导入
from gui.main_window import MainWindow
from PySide6.QtGui import Qt

if __name__ == "__main__":
    app = QApplication(sys.argv)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())