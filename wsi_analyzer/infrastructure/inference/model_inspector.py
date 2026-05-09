from typing import Optional


class ModelInspector:
    @staticmethod
    def read_input_size(file_path: str) -> Optional[int]:
        """Read the expected input size from a model weight file.

        Currently supports PyTorch (.pt/.pth) via ultralytics YOLO.
        Returns None if the file format is unsupported or parsing fails.
        """
        if not file_path.endswith(('.pt', '.pth')):
            return None
        try:
            from ultralytics import YOLO
            model = YOLO(file_path)
            imgsz = model.model.args.get("imgsz")
            if isinstance(imgsz, int):
                return imgsz
            return None
        except ImportError:
            return None
        except Exception:
            return None
