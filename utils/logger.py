import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import traceback


def setup_logger():
    """初始化并配置全局日志系统"""
    log_dir = "logs"
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
        fmt='%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 1. 文件处理器 (RotatingFileHandler) - 防爆盘
    # 每个文件最大 10MB，最多保留 5 个历史备份 (wsi_analyzer.log.1, .log.2...)
    file_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding='utf-8')
    file_handler.setLevel(logging.INFO)  # 文件里只记录 INFO、WARNING、ERROR
    file_handler.setFormatter(formatter)

    # 2. 控制台处理器 (StreamHandler) - 方便开发时查看
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)  # 控制台可以看 DEBUG
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    # 3. 全局未捕获异常拦截器
    # 解决 PySide6 报错时黑框一闪而过、静默闪退的问题
    def handle_exception(exc_type, exc_value, exc_traceback):
        # 允许键盘中断 (Ctrl+C) 正常退出
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        # 将闪退的严重错误连同堆栈信息记录到日志文件
        logger.critical("程序发生未捕获的全局异常崩溃", exc_info=(exc_type, exc_value, exc_traceback))

    # 替换 Python 的默认异常处理钩子
    sys.excepthook = handle_exception

    return logger


# 暴露出一个全局单例 logger 供其他文件导入
logger = setup_logger()