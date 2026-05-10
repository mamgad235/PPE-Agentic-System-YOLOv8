from ultralytics import YOLO
import torch

def continue_training():
    # Start from your best checkpoint
    model = YOLO('runs/detect/train5/weights/best.pt')

    device = 0 if torch.cuda.is_available() else 'cpu'

    model.train(
        data='datasets/data.yaml',
        epochs=50,
        imgsz=800,
        batch=4,
        device=device,
        workers=4,
        patience=30,

        # Same settings as your original run
        optimizer='AdamW',
        lr0=0.0002,        # Much lower LR — we're fine-tuning, not training from scratch
        lrf=0.01,
        cos_lr=True,
        warmup_epochs=1,   # Short warmup since model is already trained

        mixup=0.15,
        copy_paste=0.1,
        flipud=0.1,
        close_mosaic=15,
        cls=1.0,

        plots=True,
    )

if __name__ == '__main__':
    continue_training()