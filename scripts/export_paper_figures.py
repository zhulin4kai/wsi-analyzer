#!/usr/bin/env python
"""Export paper-ready figures from a single WSI + prediction + GT + evaluation.

Usage:
    python scripts/export_paper_figures.py \
        --wsi data/test_wsi/001.svs \
        --prediction result.json \
        --gt data/geojson/001.geojson \
        --eval eval_details.json \
        --out-dir results/figures/001 \
        --max-examples 12
"""

import argparse
import json
import os
import sys

import cv2
import numpy as np

from wsi_analyzer.app.dependency_container import container
from wsi_analyzer.application.visualization import (
    render_gt_vs_pred_overlay, render_heatmap_image, render_prediction_overlay,
)


def main():
    parser = argparse.ArgumentParser(description="Export paper figures")
    parser.add_argument("--wsi", required=True)
    parser.add_argument("--prediction", required=True)
    parser.add_argument("--gt", required=True)
    parser.add_argument("--eval", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--max-examples", type=int, default=12)
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    slide_id = os.path.splitext(os.path.basename(args.wsi))[0]

    # Load predictions
    with open(args.prediction, "r", encoding="utf-8") as f:
        pred_data = json.load(f)
    detections = pred_data.get("results", pred_data.get("detections", []))

    # Load GT
    with open(args.gt, "r", encoding="utf-8") as f:
        gt_data = json.load(f)

    # Load eval details
    with open(args.eval, "r", encoding="utf-8") as f:
        eval_data = json.load(f)
    slide_eval = eval_data.get(slide_id, {})

    # Get WSI thumbnail
    engine = container.image_server.acquire_engine(args.wsi)
    try:
        thumb_pil, downsample = container.image_server.get_thumbnail(args.wsi, level_from_last=2)
        thumb = np.array(thumb_pil.convert("RGB"))
        wsi_w, wsi_h = engine.level_0_dim

        # 01: original thumbnail
        out = os.path.join(args.out_dir, "01_original_thumbnail.png")
        cv2.imwrite(out, cv2.cvtColor(thumb, cv2.COLOR_RGB2BGR))
        print(f"  {out}")

        # 02: prediction overlay
        out = os.path.join(args.out_dir, "02_prediction_overlay.png")
        render_prediction_overlay(thumb, detections, downsample, output_path=out)
        print(f"  {out}")

        # 03: heatmap
        out = os.path.join(args.out_dir, "03_heatmap.png")
        render_heatmap_image(detections, wsi_w, wsi_h, output_path=out)
        print(f"  {out}")

        # 04: GT vs pred overlay
        out = os.path.join(args.out_dir, "04_gt_vs_pred_overlay.png")
        matches = slide_eval.get("matches", [])
        gt_boxes = []
        for feature in gt_data.get("features", []):
            bbox = _geojson_to_bbox(feature.get("geometry", {}))
            if bbox:
                gt_boxes.append(bbox)
        render_gt_vs_pred_overlay(thumb, detections, gt_boxes, matches, downsample, output_path=out)
        print(f"  {out}")

        # 05: top confidence lesions
        top_dir = os.path.join(args.out_dir, "05_top_confidence_lesions")
        os.makedirs(top_dir, exist_ok=True)
        sorted_detections = sorted(detections, key=lambda d: d.get("confidence", 0), reverse=True)
        for i, det in enumerate(sorted_detections[:args.max_examples]):
            _export_lesion_patch(det, engine, top_dir, f"lesion_{i + 1:03d}_conf_{det.get('confidence', 0):.2f}.png")

        # 06: FP examples
        fp_dir = os.path.join(args.out_dir, "06_false_positive_examples")
        os.makedirs(fp_dir, exist_ok=True)
        fp_matches = [m for m in matches if m.get("status") == "FP"]
        for i, m in enumerate(fp_matches[:args.max_examples]):
            pred = m.get("prediction", {})
            _export_lesion_patch(pred, engine, fp_dir, f"fp_{i + 1:03d}.png")

        # 07: FN examples
        fn_dir = os.path.join(args.out_dir, "07_false_negative_examples")
        os.makedirs(fn_dir, exist_ok=True)
        fn_matches = [m for m in matches if m.get("status") == "FN"]
        for i, m in enumerate(fn_matches[:args.max_examples]):
            gt = m.get("ground_truth", {})
            _export_lesion_patch(gt, engine, fn_dir, f"fn_{i + 1:03d}.png")

        print("Done.")

    finally:
        container.image_server.release_engine(args.wsi)


def _geojson_to_bbox(geom: dict) -> dict | None:
    gtype = geom.get("type", "")
    raw = geom.get("coordinates", [])
    if gtype == "Polygon" and raw:
        coords = raw[0]
    elif gtype == "MultiPolygon" and raw:
        coords = raw[0][0] if raw[0] else []
    else:
        return None
    if not coords:
        return None
    xs = [p[0] for p in coords]
    ys = [p[1] for p in coords]
    return {"x1": min(xs), "y1": min(ys), "x2": max(xs), "y2": max(ys)}


def _export_lesion_patch(box: dict, engine, out_dir: str, filename: str):
    if not box:
        return
    x1, y1 = box.get("x1", 0), box.get("y1", 0)
    x2, y2 = box.get("x2", 0), box.get("y2", 0)
    cx = int((x1 + x2) / 2)
    cy = int((y1 + y2) / 2)
    size = 512
    sx = max(0, cx - size // 2)
    sy = max(0, cy - size // 2)

    try:
        patch = engine.read_region((sx, sy), 0, (size, size)).convert("RGB")
        out = os.path.join(out_dir, filename)
        cv2.imwrite(out, cv2.cvtColor(np.array(patch), cv2.COLOR_RGB2BGR))
        print(f"  {out}")
    except Exception as e:
        print(f"  SKIP {filename}: {e}")


if __name__ == "__main__":
    main()
