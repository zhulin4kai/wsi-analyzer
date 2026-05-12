#!/usr/bin/env python
"""Batch WSI evaluation script for paper experiment tables.

Usage:
    python scripts/evaluate_wsi_batch.py \
        --wsi-dir data/test_wsi \
        --gt-dir data/geojson \
        --model runs/detect/best.pt \
        --out-dir results/eval_run_001 \
        --conf 0.25 --iou 0.5 --device cuda:0

Outputs eval_summary.csv, eval_summary.json, eval_details.json, failed_cases.csv.
"""

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

from wsi_analyzer.application.evaluation.batch_evaluation_service import BatchEvaluationService

WSI_EXTS = {".svs", ".tif", ".tiff", ".ndpi", ".mrxs"}
GT_EXTS = {".geojson", ".json"}


def _find_gt(wsi_path: str, gt_dir: str) -> str | None:
    stem = os.path.splitext(os.path.basename(wsi_path))[0]
    for ext in GT_EXTS:
        candidate = os.path.join(gt_dir, stem + ext)
        if os.path.isfile(candidate):
            return candidate
    return None


def main():
    parser = argparse.ArgumentParser(description="Batch WSI evaluation")
    parser.add_argument("--wsi-dir", required=True)
    parser.add_argument("--gt-dir", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--iou", type=float, default=0.5)
    parser.add_argument("--nms-iou", type=float, default=0.5)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--skip-missing-gt", action="store_true")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    os.makedirs(os.path.join(args.out_dir, "logs"), exist_ok=True)

    # collect WSI files
    wsi_files: list[str] = []
    for fname in sorted(os.listdir(args.wsi_dir)):
        if os.path.splitext(fname)[1].lower() in WSI_EXTS:
            wsi_files.append(os.path.join(args.wsi_dir, fname))
    if args.limit:
        wsi_files = wsi_files[: args.limit]

    if not wsi_files:
        print("No WSI files found in", args.wsi_dir)
        sys.exit(1)

    service = BatchEvaluationService(args.model)
    summaries: list[dict] = []
    details: dict[str, dict] = {}
    failures: list[dict] = []

    t0_total = time.perf_counter()
    for i, wsi_path in enumerate(wsi_files):
        slide_id = os.path.splitext(os.path.basename(wsi_path))[0]
        gt_path = _find_gt(wsi_path, args.gt_dir)
        if gt_path is None:
            if args.skip_missing_gt:
                failures.append({"slide_id": slide_id, "error": "missing_gt"})
                continue
            else:
                print(f"ERROR: no GT found for {slide_id}")
                sys.exit(1)

        print(f"[{i + 1}/{len(wsi_files)}] {slide_id} ...", end=" ", flush=True)
        try:
            result = service.run_single(slide_id, wsi_path, gt_path, args.iou)
            m = result.metrics
            row = {
                "slide_id": slide_id, "wsi_path": wsi_path, "gt_path": gt_path,
                "model_path": args.model,
                "detection_count": getattr(result, "detection_count", 0),
                "gt_count": getattr(result, "gt_count", 0),
                "tp": m.tp, "fp": m.fp, "fn": m.fn,
                "precision": m.precision, "recall": m.recall, "f1": m.f1,
                "ap50": m.ap50,
                "analysis_seconds": getattr(result, "analysis_seconds", 0),
                "status": "ok",
            }
            summaries.append(row)
            details[slide_id] = {
                "slide_id": slide_id, "metrics": {"tp": m.tp, "fp": m.fp, "fn": m.fn,
                                                   "precision": m.precision, "recall": m.recall,
                                                   "f1": m.f1, "ap50": m.ap50},
                "detection_count": getattr(result, "detection_count", 0),
                "gt_count": getattr(result, "gt_count", 0),
                "matches": [
                    {"status": mx.status, "iou": round(mx.iou, 4)}
                    for mx in result.matches
                ],
            }
            print(f"P={m.precision:.3f} R={m.recall:.3f} F1={m.f1:.3f} AP50={m.ap50:.3f} "
                  f"TP={m.tp} FP={m.fp} FN={m.fn}")
        except Exception as e:
            failures.append({"slide_id": slide_id, "error": str(e)})
            summaries.append({"slide_id": slide_id, "status": "error", "error_message": str(e)})
            print(f"FAILED: {e}")

    elapsed_total = time.perf_counter() - t0_total

    # -- summaries --
    ok_summaries = [s for s in summaries if s.get("status") == "ok"]
    if ok_summaries:
        avg = {
            "precision": sum(s["precision"] for s in ok_summaries) / len(ok_summaries),
            "recall": sum(s["recall"] for s in ok_summaries) / len(ok_summaries),
            "f1": sum(s["f1"] for s in ok_summaries) / len(ok_summaries),
            "ap50": sum(s.get("ap50", 0) for s in ok_summaries) / len(ok_summaries),
        }
        print(f"\n--- Overall ({len(ok_summaries)} slides) ---")
        print(f"Precision={avg['precision']:.4f}  Recall={avg['recall']:.4f}  "
              f"F1={avg['f1']:.4f}  AP50={avg['ap50']:.4f}")
        print(f"Total time: {elapsed_total:.1f}s  Avg: {elapsed_total / len(ok_summaries):.1f}s/slide")

    # -- write output --
    summary_csv = os.path.join(args.out_dir, "eval_summary.csv")
    if summaries:
        fields = ["slide_id", "wsi_path", "gt_path", "model_path",
                  "detection_count", "gt_count",
                  "tp", "fp", "fn", "precision", "recall", "f1", "ap50",
                  "analysis_seconds", "status"]
        with open(summary_csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(summaries)

    summary_json = os.path.join(args.out_dir, "eval_summary.json")
    with open(summary_json, "w", encoding="utf-8") as f:
        json.dump({"summaries": summaries, "total_time_s": round(elapsed_total, 1),
                   "params": vars(args)}, f, indent=2, ensure_ascii=False)

    details_json = os.path.join(args.out_dir, "eval_details.json")
    with open(details_json, "w", encoding="utf-8") as f:
        json.dump(details, f, indent=2, ensure_ascii=False)

    if failures:
        fail_csv = os.path.join(args.out_dir, "failed_cases.csv")
        with open(fail_csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["slide_id", "error"])
            w.writeheader()
            w.writerows(failures)


if __name__ == "__main__":
    main()
