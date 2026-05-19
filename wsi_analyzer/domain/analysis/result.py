from dataclasses import dataclass, field
from typing import List, Optional

from wsi_analyzer.domain.detection.entities import Detection
from wsi_analyzer.domain.slide.coordinates import Level0Box


@dataclass
class AnalysisResult:
    status: str  # "completed" | "interrupted" | "error"
    detections: List[Detection] = field(default_factory=list)
    valid_coords: Optional[List[tuple]] = None
    processed_patches: int = 0
    total_patches: int = 0
    raw_boxes: Optional[List[List[float]]] = None
    raw_scores: Optional[List[float]] = None
    raw_classes: Optional[List[int]] = None
    # fields for geometry persistence (for resume compatibility)
    level0_window_size: int = 0
    level0_stride: int = 0
    model_input_size: int = 0
    read_level: int = 0
    read_downsample: float = 0.0
    message: Optional[str] = None

    def to_dict(self) -> dict:
        d = {
            "status": self.status,
            "results": [
                {
                    "bbox": [d.bbox.x1, d.bbox.y1, d.bbox.x2, d.bbox.y2],
                    "confidence": d.confidence,
                    "class_id": d.class_id,
                }
                for d in self.detections
            ],
            "valid_coords": self.valid_coords,
            "processed_patches": self.processed_patches,
            "total_patches": self.total_patches,
            "raw_boxes": self.raw_boxes,
            "raw_scores": self.raw_scores,
            "raw_classes": self.raw_classes,
            "message": self.message,
        }
        if self.level0_window_size:
            d["level0_window_size"] = self.level0_window_size
            d["level0_stride"] = self.level0_stride
            d["model_input_size"] = self.model_input_size
            d["read_level"] = self.read_level
            d["read_downsample"] = self.read_downsample
        return d

    @classmethod
    def from_cache(cls, cache_data: dict) -> "AnalysisResult":
        return cls(
            status=cache_data.get("status", "completed"),
            detections=[
                Detection(
                    bbox=Level0Box(*d["bbox"][:4]),
                    confidence=d.get("confidence", 0),
                    class_id=d.get("class_id", -1),
                )
                for d in cache_data.get("results", [])
            ],
            valid_coords=cache_data.get("valid_coords"),
            processed_patches=cache_data.get("processed_patches", 0),
            total_patches=cache_data.get("total_patches", 0),
            raw_boxes=cache_data.get("raw_boxes"),
            raw_scores=cache_data.get("raw_scores"),
            raw_classes=cache_data.get("raw_classes"),
            level0_window_size=cache_data.get("level0_window_size", 0),
            level0_stride=cache_data.get("level0_stride", 0),
            model_input_size=cache_data.get("model_input_size", 0),
            read_level=cache_data.get("read_level", 0),
            read_downsample=cache_data.get("read_downsample", 0.0),
        )
