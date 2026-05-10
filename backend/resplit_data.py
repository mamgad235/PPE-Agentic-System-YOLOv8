"""
resplit_data.py
───────────────
Pools all images + labels from the existing train/valid/test folders,
shuffles them with a fixed seed, and re-splits into 80 / 15 / 5.

Run once from the backend/ directory:
    python resplit_data.py

A full backup is written to datasets/backup_original/ before any moves.
data.yaml does NOT need to change (paths stay the same).
"""

import os
import random
import shutil
from pathlib import Path

# ── Config ─────────────────────────────────────────────────────────────────
SEED        = 42
SPLIT_RATIO = (0.80, 0.15, 0.05)   # train / valid / test
DATASETS    = Path("datasets")
BACKUP_DIR  = DATASETS / "backup_original"
SPLITS      = ["train", "valid", "test"]

# Supported image extensions
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

# ── Step 1 — Backup originals ───────────────────────────────────────────────
def backup_originals():
    if BACKUP_DIR.exists():
        print(f"  Backup already exists at {BACKUP_DIR} - skipping backup step.")
        return
    print("  Backing up original split...")
    for split in SPLITS:
        src = DATASETS / split
        dst = BACKUP_DIR / split
        if src.exists():
            shutil.copytree(src, dst)
    print(f"   Backup saved to: {BACKUP_DIR}")

# ── Step 2 — Collect all (image, label) pairs ──────────────────────────────
def collect_pairs():
    """Always reads from backup_original (stable source) so clearing the
    working split folders never destroys the pool of files."""
    source_root = BACKUP_DIR if BACKUP_DIR.exists() else DATASETS
    pairs = []
    for split in SPLITS:
        img_dir   = source_root / split / "images"
        label_dir = source_root / split / "labels"
        if not img_dir.exists():
            print(f"   skip: {img_dir} not found.")
            continue
        for img_path in img_dir.iterdir():
            if img_path.suffix.lower() not in IMG_EXTS:
                continue
            label_path = label_dir / (img_path.stem + ".txt")
            if label_path.exists():
                pairs.append((img_path, label_path))
            else:
                # Include image even if no label file (background image)
                pairs.append((img_path, None))
    return pairs

# ── Step 3 — Shuffle + split ────────────────────────────────────────────────
def compute_split(pairs):
    random.seed(SEED)
    random.shuffle(pairs)
    n     = len(pairs)
    n_tr  = int(n * SPLIT_RATIO[0])
    n_val = int(n * SPLIT_RATIO[1])
    return {
        "train": pairs[:n_tr],
        "valid": pairs[n_tr : n_tr + n_val],
        "test" : pairs[n_tr + n_val :],
    }

# ── Step 4 — Clear existing split folders ──────────────────────────────────
def clear_splits():
    for split in SPLITS:
        for sub in ("images", "labels"):
            d = DATASETS / split / sub
            if d.exists():
                shutil.rmtree(d)
            d.mkdir(parents=True, exist_ok=True)

# ── Step 5 — Move / copy files into new folders ────────────────────────────
def populate_splits(split_map):
    for split, pairs in split_map.items():
        img_dir   = DATASETS / split / "images"
        label_dir = DATASETS / split / "labels"
        for img_src, lbl_src in pairs:
            shutil.copy2(img_src, img_dir / img_src.name)
            if lbl_src and lbl_src.exists():
                shutil.copy2(lbl_src, label_dir / lbl_src.name)

# ── Main ────────────────────────────────────────────────────────────────────
def main():
    print("=" * 55)
    print("  PPE Dataset Resplit  (80 / 15 / 5)")
    print("=" * 55)

    backup_originals()

    print("\n  Collecting image-label pairs from all splits...")
    pairs = collect_pairs()
    print(f"   Total pairs found: {len(pairs)}")

    split_map = compute_split(pairs)
    counts = {k: len(v) for k, v in split_map.items()}
    print(f"\n  New split:")
    for s, c in counts.items():
        pct = c / len(pairs) * 100
        print(f"   {s:6s} : {c:4d} images  ({pct:.1f}%)")

    print("\n  Clearing old split folders...")
    clear_splits()

    print("  Copying files into new splits...")
    populate_splits(split_map)

    print("\n  Resplit complete!")
    print(f"   Train : {counts['train']:4d} images")
    print(f"   Valid : {counts['valid']:4d} images")
    print(f"   Test  : {counts['test']:4d} images")
    print(f"\n   Originals preserved in: {BACKUP_DIR}")
    print("   data.yaml is unchanged — no edits needed.")
    print("=" * 55)

if __name__ == "__main__":
    main()
