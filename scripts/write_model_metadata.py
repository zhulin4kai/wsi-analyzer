#!/usr/bin/env python
"""Generate a .model.yaml sidecar file for a trained model checkpoint.

Usage:
    python scripts/write_model_metadata.py best.pt \
        --model-input-size 768 \
        --target-mpp 0.1725 \
        --classes micropapillary \
        --dataset-name hospital_x

This writes best.model.yaml alongside best.pt.
The inference backend reads it automatically via ModelMetadataLoader.
"""

import argparse
import json
import os
import sys

try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


def main():
    parser = argparse.ArgumentParser(description="Write model metadata sidecar")
    parser.add_argument("model_path", help="Path to the model checkpoint (e.g. best.pt)")
    parser.add_argument("--model-input-size", type=int, required=True,
                        help="Model input side length in px (YOLO imgsz)")
    parser.add_argument("--target-mpp", type=float, required=True,
                        help="Microns per pixel the model was trained at")
    parser.add_argument("--classes", nargs="+", required=True,
                        help="Class names (e.g. micropapillary benign malignant)")
    parser.add_argument("--backend", default="ultralytics_yolo")
    parser.add_argument("--task", default="detect")
    parser.add_argument("--model-name", default=None)
    parser.add_argument("--dataset-name", default=None)
    parser.add_argument("--source-mpp", type=float, default=None)
    args = parser.parse_args()

    model_name = args.model_name or os.path.splitext(os.path.basename(args.model_path))[0]
    classes = {i: name for i, name in enumerate(args.classes)}

    data = {
        "model_name": model_name,
        "backend": args.backend,
        "task": args.task,
        "model_input_size": args.model_input_size,
        "target_mpp": args.target_mpp,
        "classes": classes,
    }
    if args.dataset_name:
        data["dataset_name"] = args.dataset_name
    if args.source_mpp:
        data["source_mpp"] = args.source_mpp

    base = os.path.splitext(args.model_path)[0]
    yaml_path = base + ".model.yaml"
    json_path = base + ".model.json"

    if _HAS_YAML:
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        print(f"Written: {yaml_path}")
    else:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Written: {json_path} (install PyYAML for .yaml output)")


if __name__ == "__main__":
    main()
