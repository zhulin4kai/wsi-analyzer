import sys
import os

def resource_path(relative_path):
    """生成资源绝对路径，兼顾开发环境与 PyInstaller 打包环境"""
    if hasattr(sys, '_MEIPASS'):
        # 单文件模式 (--onefile) 会用到 _MEIPASS
        base_path = sys._MEIPASS
    else:
        # 目录模式 (--onedir) 下
        base_path = os.path.dirname(os.path.abspath(sys.argv[0]))
    # 因为这个文件在 utils 文件夹下，所以要获取上一级目录的基准
    if not hasattr(sys, '_MEIPASS'):
        base_path = os.path.dirname(base_path)
    return os.path.join(base_path, relative_path)

def setup_environment():
    """初始化环境，挂载 DLL (必须在 import openslide 之前调用)"""
    if os.name == 'nt':
        openslide_bin_path = resource_path('openslide-bin')
        if os.path.exists(openslide_bin_path):
            os.add_dll_directory(openslide_bin_path)