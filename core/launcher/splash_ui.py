import os
import tkinter as tk

try:
    from PIL import Image, ImageTk

    HAS_PIL = True
except ImportError:
    HAS_PIL = False


class SplashUI:
    """
    启动画面的纯视觉组件。
    处理Tkinter窗口创建、DPI缩放、图像渲染和文本叠加。
    不包含任何多进程或业务逻辑。
    """

    def __init__(self, image_path: str, width: int = 640, height: int = 360):
        self.width = width
        self.height = height

        # 1. 修复Windows DPI缩放问题，以确保准确的屏幕分辨率和居中
        if os.name == "nt":
            import ctypes

            try:
                # Windows 8.1+
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                try:
                    # Windows Vista/7/8
                    ctypes.windll.user32.SetProcessDPIAware()
                except Exception:
                    pass

        # 确保任务栏图标分组一致并显示独立图标
        if os.name == "nt":
            try:
                import ctypes

                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "wsianalyzer.app.v0.0.1"
                )
            except Exception:
                pass

        self.root = tk.Tk()

        # 设置任务栏和窗口图标
        base_dir = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        icon_path = os.path.join(base_dir, "assets", "app_icon.ico")
        if not os.path.exists(icon_path):
            icon_path = os.path.join(base_dir, "app_icon.ico")
        if os.path.exists(icon_path):
            try:
                self.root.iconbitmap(icon_path)
            except Exception:
                pass

        # 移除窗口边框和标题栏
        self.root.overrideredirect(True)
        # 保持窗口在最顶层
        self.root.attributes("-topmost", True)
        self.root.configure(bg="white")

        # 初始隐藏窗口，防止在错误的坐标处闪烁
        self.root.withdraw()
        self.root.update_idletasks()

        # 2. 准确居中计算
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = int((screen_width - width) / 2)
        y = int((screen_height - height) / 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

        # 3. 用于渲染图像和动态文本叠加的Canvas画布
        self.canvas = tk.Canvas(
            self.root, width=width, height=height, bg="white", highlightthickness=0
        )
        self.canvas.pack(fill="both", expand=True)

        self.image_ref = None
        self.text_item = None

        # 加载并设置图像
        self._load_image(image_path)

        # 创建文本叠加项
        self._create_text_overlay()

        # 4. 显示窗口
        self.root.deiconify()
        self.root.lift()  # 将窗口提升到Z-index的最上层
        self.root.attributes("-topmost", True)  # 再次强制声明最高层级
        self.root.update_idletasks()
        self.root.update()

    def _load_image(self, image_path: str):
        if os.path.exists(image_path) and HAS_PIL:
            try:
                img = Image.open(image_path)
                if img.mode != "RGB":
                    img = img.convert("RGB")

                resample_filter = getattr(Image, "Resampling", Image).LANCZOS
                img = img.resize((self.width, self.height), resample_filter)
                self.image_ref = ImageTk.PhotoImage(img)

                self.canvas.create_image(0, 0, anchor="nw", image=self.image_ref)
            except Exception as e:
                print(f"SplashUI failed to load image: {e}")
        else:
            # 后备背景（图片加载失败时显示）
            self.canvas.configure(bg="#2d2d2d")
            self.canvas.create_text(
                self.width / 2,
                self.height / 2,
                text="WSIAnalyzer\nLoading...",
                fill="white",
                font=("Arial", 24),
                justify="center",
            )

    def _create_text_overlay(self):
        """在启动画面左下角创建动态状态文本。"""
        self.text_item = self.canvas.create_text(
            15,
            self.height - 20,  # 左下角边距
            text="Initializing...",
            fill="white",  # 默认白色文本（适合深色启动背景）
            anchor="w",
            font=("Arial", 10),
        )

    def update_text(self, message: str):
        """更新启动画面上的状态文本。"""
        if self.text_item is not None:
            self.canvas.itemconfig(self.text_item, text=message)
            self.root.update_idletasks()

    def schedule_task(self, delay_ms: int, func):
        """暴露Tkinter的after()方法，供启动器调度检查任务。"""
        if self.root:
            self.root.after(delay_ms, func)

    def run(self):
        """进入Tkinter主循环。"""
        if self.root:
            self.root.mainloop()

    def close(self):
        """销毁UI界面。"""
        if self.root:
            self.root.destroy()
            self.root = None
