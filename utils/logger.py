import logging
import os
import sys
from logging.handlers import RotatingFileHandler


def _get_log_dir() -> str:
    """返回日志目录的绝对路径。

    打包模式：Windows → %LOCALAPPDATA%/WSIAnalyzer/logs
              Linux/macOS → ~/.local/state/WSIAnalyzer/logs
    开发模式：项目根目录下的 logs/
    """
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        else:
            base = os.environ.get(
                "XDG_STATE_HOME", os.path.join(os.path.expanduser("~"), ".local", "state")
            )
        base = os.path.join(base, "WSIAnalyzer")
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "logs")


def setup_logger():
    """初始化并配置全局日志系统"""
    log_dir = _get_log_dir()
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_file = os.path.join(log_dir, "wsi_analyzer.log")

    # 创建 Logger 实例
    logger = logging.getLogger("WSIAnalyzer")
    logger.setLevel(logging.DEBUG)  # 捕获所有级别的日志

    # 防止重复添加 Handler 导致日志重复打印
    if logger.handlers:
        return logger

    # 统一的日志格式：时间 [级别] 文件名:行号 - 信息
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 1. 文件处理器 (RotatingFileHandler)
    # 每个文件最大 10MB，最多保留 5 个历史备份 (wsi_analyzer.log.1, wsi_analyzer.log.2)
    file_handler = RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(logging.INFO)  # 文件里只记录 INFO、WARNING、ERROR
    file_handler.setFormatter(formatter)

    # 2. 控制台处理器 (StreamHandler)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)  # 控制台可以看 DEBUG
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    # 3. 全局未捕获异常拦截器
    # 用于记录程序中未处理的异常
    def handle_exception(exc_type, exc_value, exc_traceback):
        # 允许键盘中断 (Ctrl+C) 正常退出
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        # 记录异常及其堆栈信息
        logger.critical("发生未捕获异常", exc_info=(exc_type, exc_value, exc_traceback))

    # 替换 Python 的默认异常处理钩子
    sys.excepthook = handle_exception

    return logger


# 提供全局 logger 实例
logger = setup_logger()
