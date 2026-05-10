"""
evaluate.py
───────────
Runs a full COCO-style evaluation on the test (or val) split.

Usage (from the backend/ directory):
    python evaluate.py                       # evaluates on test split with latest trained model
    python evaluate.py val                   # evaluates on val split
    python evaluate.py test path/to/best.pt  # specify split and model explicitly

Outputs saved to runs/detect/val<N>/:
    - confusion_matrix_normalized.png   <- grab this for your defence slides
    - PR_curve.png
    - F1_curve.png
    - predictions.json                  <- COCO-format predictions (--save-json)
    - results.csv

Metrics printed:
    - mAP50       (standard metric, main headline number)
    - mAP50-95    (COCO primary metric, stricter IoU range)
    - Per-class AP50
"""

import os
import sys
from pathlib import Path
from ultralytics import YOLO


def find_best_model():
    runs_dir = Path("runs/detect")
    if not runs_dir.exists():
        return None
    train_dirs = sorted(runs_dir.glob("train*"), key=os.path.getmtime, reverse=True)
    for d in train_dirs:
        best = d / "weights" / "best.pt"
        if best.exists():
            return str(best)
    return None


def evaluate(model_path=None, split="test"):
    if model_path is None:
        model_path = find_best_model()
        if model_path is None:
            print("No trained model found in runs/detect/. Run train.py first.")
            return

    if not Path(model_path).exists():
        print(f"Model file not found: {model_path}")
        return

    print("=" * 55)
    print(f"  PPE Detection — COCO Evaluation")
    print("=" * 55)
    print(f"  Model : {model_path}")
    print(f"  Split : {split}")
    print(f"  Data  : datasets/data.yaml")
    print("=" * 55)

    model = YOLO(model_path)

    metrics = model.val(
        data="datasets/data.yaml",
        split=split,
        save_json=True,   # COCO-format predictions.json
        plots=True,       # confusion matrix, PR curve, F1 curve
        conf=0.001,       # low conf threshold = full PR curve coverage
        iou=0.6,
        verbose=True,
    )

    print("\n" + "=" * 55)
    print("  Summary")
    print("=" * 55)
    print(f"  mAP50     : {metrics.box.map50:.4f}  ({metrics.box.map50*100:.1f}%)")
    print(f"  mAP50-95  : {metrics.box.map:.4f}  ({metrics.box.map*100:.1f}%)")
    print(f"  Precision : {metrics.box.mp:.4f}")
    print(f"  Recall    : {metrics.box.mr:.4f}")
    print()
    print("  Per-class AP50:")
    names = model.names
    per_class = list(zip(names.values(), metrics.box.ap50))
    per_class.sort(key=lambda x: x[1], reverse=True)
    for cls_name, ap in per_class:
        bar = "#" * int(ap * 30)
        print(f"    {cls_name:<22s}  {ap:.4f}  {bar}")

    save_dir = metrics.save_dir
    print(f"\n  Plots saved to : {save_dir}")
    conf_matrix = Path(save_dir) / "confusion_matrix_normalized.png"
    if conf_matrix.exists():
        print(f"  Confusion matrix: {conf_matrix}")
    print("=" * 55)


if __name__ == "__main__":
    args = sys.argv[1:]
    split      = "test"
    model_path = None

    for arg in args:
        if arg in ("test", "val", "train"):
            split = arg
        elif arg.endswith(".pt"):
            model_path = arg

    evaluate(model_path, split)
