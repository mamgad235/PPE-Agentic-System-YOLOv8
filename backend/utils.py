# utils.py
import cv2
from collections import defaultdict
from config import VIOLATION_CLASSES, WEARABLE_PPE

def build_summary(detections: list) -> dict:
    violations = [d for d in detections if d["class"] in VIOLATION_CLASSES]
    ppe_worn   = [d for d in detections if d["class"] in WEARABLE_PPE]
    counts     = defaultdict(int)
    for d in detections: counts[d["class"]] += 1
    return {
        "total_detections" : len(detections),
        "ppe_worn_count"   : len(ppe_worn),
        "violation_count"  : len(violations),
        "is_compliant"     : len(violations) == 0,
        "class_counts"     : dict(counts),
        "violations_found" : list({d["class"] for d in violations}),
    }

def calculate_iou(box1, box2):
    x_left   = max(box1[0], box2[0])
    y_top    = max(box1[1], box2[1])
    x_right  = min(box1[2], box2[2])
    y_bottom = min(box1[3], box2[3])
    if x_right < x_left or y_bottom < y_top: return 0.0
    intersection_area = (x_right - x_left) * (y_bottom - y_top)
    box1_area = (box1[2] - box1[0]) * (box1[3] - box1[1])
    box2_area = (box2[2] - box2[0]) * (box2[3] - box2[1])
    return intersection_area / float(box1_area + box2_area - intersection_area)

def calculate_ioa(person_box, ppe_box):
    px1, py1, px2, py2 = person_box
    hx1, hy1, hx2, hy2 = ppe_box
    x_left   = max(px1, hx1)
    y_top    = max(py1, hy1)
    x_right  = min(px2, hx2)
    y_bottom = min(py2, hy2)
    if x_right < x_left or y_bottom < y_top: return 0.0
    intersection_area = (x_right - x_left) * (y_bottom - y_top)
    ppe_area = (hx2 - hx1) * (hy2 - hy1)
    if ppe_area == 0: return 0.0
    return intersection_area / float(ppe_area)

def calculate_iosa(box1, box2):
    x_left   = max(box1[0], box2[0])
    y_top    = max(box1[1], box2[1])
    x_right  = min(box1[2], box2[2])
    y_bottom = min(box1[3], box2[3])
    if x_right < x_left or y_bottom < y_top: return 0.0
    intersection_area = (x_right - x_left) * (y_bottom - y_top)
    box1_area = (box1[2] - box1[0]) * (box1[3] - box1[1])
    box2_area = (box2[2] - box2[0]) * (box2[3] - box2[1])
    smaller_area = min(box1_area, box2_area)
    if smaller_area == 0: return 0.0
    return intersection_area / float(smaller_area)

def is_valid_person(box, conf):
    if conf < 0.65: return False
    width = box[2] - box[0]
    height = box[3] - box[1]
    if width > height * 1.5: return False
    return True

def check_ppe_status(person_boxes, ppe_box, ppe_class):
    overlaps_any = False
    for p_box in person_boxes:
        if calculate_ioa(p_box, ppe_box) >= 0.05:
            overlaps_any = True
            py1, py2 = p_box[1], p_box[3]
            hy1, hy2 = ppe_box[1], ppe_box[3]
            p_height = py2 - py1
            ppe_center_y = hy1 + (hy2 - hy1) / 2

            head_zone_bottom = py1 + (p_height * 0.50)  
            torso_zone_top = py1 + (p_height * 0.15)    
            torso_zone_bottom = py1 + (p_height * 0.80) 

            valid_zone = True
            if ppe_class in ["Hardhat", "NO-Hardhat", "Mask", "NO-Mask"]:
                if ppe_center_y > head_zone_bottom: valid_zone = False 
            if ppe_class in ["Safety Vest", "NO-Safety Vest"]:
                if ppe_center_y < torso_zone_top or ppe_center_y > torso_zone_bottom: valid_zone = False 

            if valid_zone: return True, True 
    return False, overlaps_any

def annotate_frame(frame, detections: list):
    COLOR_MAP = {
        "Hardhat": (255, 165, 0), "Mask": (0, 255, 0),
        "Safety Vest": (255, 140, 0), "Safety Cone": (0, 165, 255),
        "Person": (191, 0, 255), "machinery": (255, 128, 0),
        "vehicle": (42, 42, 165), "NO-Hardhat": (0, 0, 255),
        "NO-Mask": (0, 0, 255), "NO-Safety Vest": (0, 0, 255),
    }
    for det in detections:
        x1, y1, x2, y2 = det["box"]
        color = COLOR_MAP.get(det["class"], (0, 255, 0))
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        label = f"{det['class']} {det['confidence']:.0%}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        ly = max(y1 - 5, th + 5)
        cv2.rectangle(frame, (x1, ly - th - 4), (x1 + tw + 4, ly + 2), color, -1)
        text_color = (255, 255, 255) if det["class"] in VIOLATION_CLASSES else (0, 0, 0)
        cv2.putText(frame, label, (x1 + 2, ly), cv2.FONT_HERSHEY_SIMPLEX, 0.5, text_color, 1)
    return frame