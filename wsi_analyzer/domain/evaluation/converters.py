import json

from wsi_analyzer.domain.evaluation.entities import EvalBox
from wsi_analyzer.domain.slide.coordinates import Level0Box


def detections_to_eval_boxes(
    detections,
    slide_id: str,
) -> list[EvalBox]:
    """Convert project detection results into EvalBox list.

    Compatible inputs:
      - List[Detection]      (domain/detection/entities)
      - AnalysisResult.detections
      - list[dict]           (results_json format: {"bbox": [...], "confidence": ..., "class_id": ...})
    """
    boxes: list[EvalBox] = []
    for i, det in enumerate(detections):
        if hasattr(det, "bbox") and isinstance(det.bbox, Level0Box):
            b = det.bbox
            boxes.append(EvalBox(
                box_id=f"pred_{slide_id}_{i}",
                slide_id=slide_id,
                x1=b.x1, y1=b.y1, x2=b.x2, y2=b.y2,
                confidence=getattr(det, "confidence", None),
                class_id=getattr(det, "class_id", 0),
                source="prediction",
            ))
        elif isinstance(det, dict) and "bbox" in det:
            b = det["bbox"]
            boxes.append(EvalBox(
                box_id=f"pred_{slide_id}_{i}",
                slide_id=slide_id,
                x1=b[0], y1=b[1], x2=b[2], y2=b[3],
                confidence=det.get("confidence"),
                class_id=det.get("class_id", 0),
                source="prediction",
            ))
    return boxes


def geojson_annotations_to_eval_boxes(
    geojson_path: str,
    slide_id: str,
) -> list[EvalBox]:
    """Parse a GeoJSON annotation file into ground-truth EvalBox list.

    Supports Polygon and MultiPolygon geometry types.
    Converts polygon outlines to minimal axis-aligned bounding rectangles.
    """
    with open(geojson_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    boxes: list[EvalBox] = []
    for i, feature in enumerate(data.get("features", [])):
        geom = feature.get("geometry", {})
        props = feature.get("properties", {})

        coords = _extract_coords(geom)
        if not coords:
            continue

        xs = [p[0] for p in coords]
        ys = [p[1] for p in coords]
        boxes.append(EvalBox(
            box_id=f"gt_{slide_id}_{i}",
            slide_id=slide_id,
            x1=min(xs), y1=min(ys),
            x2=max(xs), y2=max(ys),
            class_id=props.get("class_id", 0),
            class_name=props.get("class_name", "micropapillary"),
            confidence=None,
            source="ground_truth",
        ))
    return boxes


def _extract_coords(geom: dict) -> list | None:
    gtype = geom.get("type", "")
    raw_coords = geom.get("coordinates", [])
    if gtype == "Polygon" and raw_coords:
        return raw_coords[0]
    if gtype == "MultiPolygon":
        # flatten first ring of each polygon
        all_pts = []
        for polygon in raw_coords:
            if polygon:
                all_pts.extend(polygon[0])
        return all_pts if all_pts else None
    return None
