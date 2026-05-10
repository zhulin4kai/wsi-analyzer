import logging
import os
import sys
from logging.handlers import RotatingFileHandler


def _get_log_dir() -> str:
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        else:
            base = os.environ.get(
                "XDG_STATE_HOME", os.path.join(os.path.expanduser("~"), ".local", "state")
            )
        base = os.path.join(base, "WSIAnalyzer")
    else:
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "logs")


def setup_logger():
    log_dir = _get_log_dir()
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_file = os.path.join(log_dir, "wsi_analyzer.log")

    _logger = logging.getLogger("WSIAnalyzer")
    _logger.setLevel(logging.DEBUG)

    if _logger.handlers:
        return _logger

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        str(log_file), maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)

    _logger.addHandler(file_handler)
    _logger.addHandler(console_handler)

    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        _logger.critical("发生未捕获异常", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = handle_exception

    return _logger


logger = setup_logger()
