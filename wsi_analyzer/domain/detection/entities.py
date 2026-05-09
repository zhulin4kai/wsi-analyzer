from dataclasses import dataclass

from wsi_analyzer.domain.slide.coordinates import Level0Box


@dataclass(frozen=True)
class Detection:
    bbox: Level0Box
    confidence: float
    class_id: int
