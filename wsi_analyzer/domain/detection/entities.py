from dataclasses import dataclass, field
from typing import List, Optional

from wsi_analyzer.domain.slide.coordinates import Level0Box


@dataclass(frozen=True)
class Detection:
    bbox: Level0Box
    confidence: float
    class_id: int


@dataclass(frozen=True)
class AnalysisResult:
    status: str  # "completed" | "interrupted" | "error"
    detections: List[Detection]
    total_patches: int
    processed_patches: int
    valid_coords: Optional[list] = None
    raw_boxes: Optional[List[List[float]]] = None
    raw_scores: Optional[List[float]] = None
    raw_classes: Optional[List[int]] = None
    message: Optional[str] = None
