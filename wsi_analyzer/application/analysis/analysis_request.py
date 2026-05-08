from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class AnalysisRequest:
    slide_path: str
    model_path: str
    roi_bbox: Optional[tuple] = None
    resume_data: Optional[dict] = None
