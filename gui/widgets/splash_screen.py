import os
import tkinter as tk

try:
    from PIL import Image, ImageTk

    HAS_PIL = True
except ImportError:
    HAS_PIL = False


class TkSplashScreen:
    """
    Tkinter based splash screen.
    Displays immediately before heavy frameworks like Qt start.
    """

    def __init__(self, image_path: str, width: int = 640, height: int = 360):
        # 1. Fix Windows DPI scaling issue for accurate screen resolution & centering
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

        self.root = tk.Tk()

        # Remove window borders and decorations
        self.root.overrideredirect(True)

        # Keep splash screen on top
        self.root.attributes("-topmost", True)
        self.root.configure(bg="white")

        # Hide window while configuring to avoid flashing at coordinates (0, 0)
        self.root.withdraw()

        # Force tkinter to update its internal geometry states
        self.root.update_idletasks()

        # 2. Accurately center the window on the screen
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = int((screen_width - width) / 2)
        y = int((screen_height - height) / 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

        # 3. Load and exactly scale the image (requires Pillow for good resizing)
        if os.path.exists(image_path) and HAS_PIL:
            try:
                img = Image.open(image_path)

                # Convert to RGB to prevent transparency/alpha channel issues in Tkinter
                if img.mode != "RGB":
                    img = img.convert("RGB")

                # Resize to exactly 640x360 (16:9) with high quality
                resample_filter = getattr(Image, "Resampling", Image).LANCZOS
                img = img.resize((width, height), resample_filter)

                # Keep a reference to prevent garbage collection
                self.image = ImageTk.PhotoImage(img)

                # Use bd=0 and highlightthickness=0 to prevent any default borders
                label = tk.Label(
                    self.root, image=self.image, bg="white", bd=0, highlightthickness=0
                )
                label.pack(expand=True, fill="both")
            except Exception as e:
                print(f"Failed to load or resize splash image: {e}")
                self._create_fallback_text()
        else:
            if not HAS_PIL:
                print(
                    "Pillow (PIL) is not installed. Scaling splash image is not supported."
                )
            self._create_fallback_text()

        # 4. Show window
        self.root.deiconify()

    def run(self):
        """Enter the tkinter main loop. Keeps the window responsive in a separate process."""
        if self.root:
            self.root.mainloop()

    def _create_fallback_text(self):
        label = tk.Label(
            self.root,
            text="Loading WSIAnalyzer...",
            font=("Arial", 20),
            bg="white",
            fg="black",
        )
        label.pack(expand=True, fill="both")

    def close(self):
        """Destroy the splash screen."""
        if self.root:
            self.root.destroy()
            self.root = None
