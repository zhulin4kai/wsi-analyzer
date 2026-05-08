import multiprocessing
import os
import sys

from wsi_analyzer.app.bootstrap import run_qt_app
from wsi_analyzer.app.launcher import AppLauncher


def _patch_stdio_for_pyinstaller() -> None:
    if sys.stdout is None:
        import io
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        import io
        sys.stderr = io.StringIO()


def main() -> None:
    _patch_stdio_for_pyinstaller()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    splash_image_path = os.path.join(base_dir, "assets", "splash.png")
    if not os.path.exists(splash_image_path):
        splash_image_path = os.path.join(base_dir, "splash.png")

    launcher = AppLauncher(
        image_path=splash_image_path,
        heavy_task_func=run_qt_app,
        width=640,
        height=360,
    )
    launcher.run()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    multiprocessing.set_start_method("spawn", force=True)
    main()