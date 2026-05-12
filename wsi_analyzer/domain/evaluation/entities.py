from dataclasses import dataclass, field
from typing import Optional, Literal


@dataclass(frozen=True)
class EvalBox:
    box_id: str
    slide_id: str
    x1: float
    y1: float
    x2: float
    y2: float
    class_id: int = 0
    class_name: str = "micropapillary"
    confidence: Optional[float] = None
    source: Literal["prediction", "ground_truth"] = "prediction"

    def area(self) -> float:
        if self.x2 < self.x1 or self.y2 < self.y1:
            return 0.0
        return (self.x2 - self.x1) * (self.y2 - self.y1)

    def normalize(self) -> "EvalBox":
        x1, x2 = (self.x1, self.x2) if self.x1 <= self.x2 else (self.x2, self.x1)
        y1, y2 = (self.y1, self.y2) if self.y1 <= self.y2 else (self.y2, self.y1)
        return EvalBox(
            box_id=self.box_id, slide_id=self.slide_id,
            x1=x1, y1=y1, x2=x2, y2=y2,
            class_id=self.class_id, class_name=self.class_name,
            confidence=self.confidence, source=self.source,
        )


@dataclass(frozen=True)
class MatchRecord:
    prediction: Optional[EvalBox]
    ground_truth: Optional[EvalBox]
    iou: float
    status: Literal["TP", "FP", "FN"]


@dataclass(frozen=True)
class EvaluationMetrics:
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float
    ap50: Optional[float] = None


@dataclass(frozen=True)
class EvaluationResult:
    slide_id: str
    iou_threshold: float
    metrics: EvaluationMetrics
    matches: list[MatchRecord] = field(default_factory=list)
