# config.py

CLASS_NAMES = [
    "Hardhat", "Mask", "NO-Hardhat", "NO-Mask",
    "NO-Safety Vest", "Person", "Safety Cone",
    "Safety Vest", "machinery", "vehicle"
]

VIOLATION_CLASSES = {"NO-Hardhat", "NO-Mask", "NO-Safety Vest"}
PPE_CLASSES       = {"Hardhat", "Mask", "Safety Vest", "Safety Cone", "machinery", "vehicle", "Person"}
WEARABLE_PPE      = {"Hardhat", "Mask", "Safety Vest"}  # Strict wearables limit
REQUIRES_PERSON   = {"Hardhat", "Mask", "Safety Vest", "NO-Hardhat", "NO-Mask", "NO-Safety Vest"}

# --- THRESHOLDS ---
CONF_THRESHOLD        = 0.50
TRUST_THRESHOLD       = 0.75 
NMS_IOU_THRESHOLD     = 0.45 
NESTED_IOSA_THRESHOLD = 0.70

MUTUALLY_EXCLUSIVE_PAIRS = [
    {"Hardhat", "NO-Hardhat"},
    {"Mask", "NO-Mask"},
    {"Safety Vest", "NO-Safety Vest"}
]

# --- MODEL PATHS ---
OLD_MODEL_PATH = "runs/detect/train4/weights/best.pt"
NEW_MODEL_PATH = "runs/detect/train6/weights/best.pt"