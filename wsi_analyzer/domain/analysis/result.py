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
    message: Optional[str] = None

    def to_dict(self) -> dict:
        return {
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
        )
