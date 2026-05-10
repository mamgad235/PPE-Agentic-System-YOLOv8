"""
export_model.py
───────────────
Exports the trained PPE detection model to ONNX format for deployment.

ONNX (Open Neural Network Exchange) allows the model to run:
  - Without PyTorch installed
  - On edge devices (Jetson Nano, Raspberry Pi, etc.)
  - In C++, Java, C# applications
  - Via ONNX Runtime — much faster inference than PyTorch on CPU

Usage (from the backend/ directory):
    python export_model.py                        # exports latest trained model
    python export_model.py path/to/best.pt        # exports specific model

Output:
    A .onnx file next to the .pt file, e.g.:
    runs/detect/train5/weights/best.onnx

Inference speed comparison (typical, CPU):
    PyTorch .pt   ~120 ms/frame
    ONNX Runtime   ~35 ms/frame   (~3x faster)
    TensorRT       ~8 ms/frame    (~15x faster, GPU only)
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


def export(model_path=None):
    if model_path is None:
        model_path = find_best_model()
        if model_path is None:
            print("No trained model found. Run train.py first.")
            return

    if not Path(model_path).exists():
        print(f"Model not found: {model_path}")
        return

    print("=" * 55)
    print("  PPE Model Export — ONNX")
    print("=" * 55)
    print(f"  Source : {model_path}")
    print(f"  Format : ONNX (opset 17)")
    print(f"  Image  : 800x800")
    print(f"  Batch  : dynamic")
    print("  Exporting...")

    model  = YOLO(model_path)
    output = model.export(
        format="onnx",
        imgsz=800,
        dynamic=True,     # accept any batch size at inference time
        simplify=True,    # simplify ONNX graph (removes redundant ops)
        opset=17,
    )

    print(f"\n  Exported to : {output}")
    print(f"  File size   : {Path(output).stat().st_size / 1e6:.1f} MB")
    print()
    print("  To run inference with ONNX Runtime:")
    print("    pip install onnxruntime")
    print("    from ultralytics import YOLO")
    print(f"    model = YOLO('{output}')")
    print("    results = model('image.jpg')")
    print("=" * 55)


if __name__ == "__main__":
    model_path = sys.argv[1] if len(sys.argv) > 1 else None
    export(model_path)
