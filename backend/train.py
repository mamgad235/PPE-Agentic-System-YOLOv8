from ultralytics import YOLO
import torch

# ─────────────────────────────────────────────────────────────────
# MODEL SIZE — change to "m" for the medium model (recommended for
# final submission if time allows):
#
#   "s"  Small  — 22 MB, batch=8,  ~fast training
#   "m"  Medium — 52 MB, batch=4,  +2-4 mAP points
#
# If you switch to "m", the batch size is automatically halved
# to protect your 6 GB VRAM.
# ─────────────────────────────────────────────────────────────────
MODEL_SIZE = "m"


def start_training():
    model = YOLO(f'yolov8{MODEL_SIZE}.pt')

    if torch.cuda.is_available():
        device = 0
        print(f"Training on GPU: {torch.cuda.get_device_name(0)}")
    else:
        device = 'cpu'
        print("GPU not found, falling back to CPU.")

    # Batch size: small=8, medium=4 (fits in 6 GB VRAM)
    batch = 8 if MODEL_SIZE == "s" else 4

    model.train(
        data='datasets/data.yaml',
        epochs=100,
        imgsz=800,
        batch=batch,
        device=device,
        workers=4,
        patience=50,

        # Better optimiser for small datasets
        optimizer='AdamW',
        lr0=0.001,
        lrf=0.01,
        cos_lr=True,        # cosine LR decay

        # Augmentation improvements
        mixup=0.15,         # reduces NO-Hardhat/Hardhat confusion
        copy_paste=0.1,     # helps rare classes (Safety Cone)
        flipud=0.1,         # overhead construction site cameras
        close_mosaic=20,    # stabilises final epochs

        # Higher classification loss weight for 10-class imbalance
        cls=1.0,

        plots=True,
    )


if __name__ == '__main__':
    start_training()
