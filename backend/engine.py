# engine.py
from ultralytics import YOLO
import cv2
import uuid
from pathlib import Path
from collections import defaultdict
from typing import Optional
from PIL import Image
from fastapi import HTTPException

from config import *
from utils import is_valid_person, check_ppe_status, calculate_iou, calculate_iosa, annotate_frame

model_static = None
model_live = None
model_static_path = None
model_live_path = None

# Custom BoT-SORT config with appearance Re-ID enabled. BoT-SORT plus
# `with_reid: true` + `model: auto` lets the tracker re-acquire the SAME
# track id when a worker walks out of the frame and back in, by using the
# YOLO detector's own feature embeddings as appearance vectors. ByteTrack
# (motion-only) can't do that.
_TRACKER_CFG = Path(__file__).resolve().parent / "agent" / "botsort_ppe.yaml"

def load_model():
    global model_static, model_live, model_static_path, model_live_path
    
    if Path(OLD_MODEL_PATH).exists():
        model_live = YOLO(OLD_MODEL_PATH)
        model_live_path = OLD_MODEL_PATH
        print(f"✅ Loaded LIVE model: {OLD_MODEL_PATH}")
    else:
        model_live = YOLO("yolov8s.pt")
        model_live_path = "yolov8s.pt (base)"
        print(f"⚠️  Live model not found at {OLD_MODEL_PATH}. Using base YOLO.")

    if Path(NEW_MODEL_PATH).exists():
        model_static = YOLO(NEW_MODEL_PATH)
        model_static_path = NEW_MODEL_PATH
        print(f"✅ Loaded STATIC model: {NEW_MODEL_PATH}")
    else:
        model_static = YOLO("yolov8m.pt")
        model_static_path = "yolov8m.pt (base)"
        print(f"⚠️  Static model not found at {NEW_MODEL_PATH}. Using base YOLOv8m.")

load_model()

def run_inference_basic(image) -> list:
    # Lightweight live post-processing. Unlike run_inference_advanced (used for
    # images/video) we deliberately keep this cheap so live latency stays low,
    # but we DO apply two O(n^2)-on-a-handful-of-boxes guards that fix the most
    # visible live-feed artifacts:
    #   1. is_valid_person  -> rejects background objects mis-detected as Person
    #      (low confidence or non-upright width/height ratio).
    #   2. IoSA/IoU dedup    -> drops nested/duplicate same-class boxes that
    #      YOLO's built-in IoU-only NMS misses (e.g. two stacked Person boxes
    #      on the same worker). IoSA catches the nested case IoU cannot.
    results = model_live(image, conf=CONF_THRESHOLD)
    raw = []
    for r in results:
        for box in r.boxes:
            conf = float(box.conf[0])
            if conf < CONF_THRESHOLD: continue
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            cls = int(box.cls[0])
            class_name = model_live.names[cls]
            box_coords = [round(x1), round(y1), round(x2), round(y2)]
            # Reject false-positive persons (low conf / non-upright aspect ratio).
            if class_name == "Person" and not is_valid_person(box_coords, conf):
                continue
            raw.append({
                "class"       : class_name,
                "confidence"  : round(conf, 2),
                "box"         : box_coords,
                "is_violation": class_name in VIOLATION_CLASSES,
            })

    # Light NMS pass: keep highest-confidence boxes, drop nested/duplicate
    # same-class boxes the detector's built-in NMS let through.
    raw.sort(key=lambda d: d["confidence"], reverse=True)
    detections = []
    for det in raw:
        if any(
            det["class"] == kept["class"] and
            (calculate_iou(det["box"], kept["box"]) > NMS_IOU_THRESHOLD or
             calculate_iosa(det["box"], kept["box"]) > NESTED_IOSA_THRESHOLD)
            for kept in detections
        ):
            continue
        detections.append(det)
    return detections


_TRACKER_LOGGED = False  # guard so we only print the tracker line once


def run_inference_basic_tracked(image) -> list:
    """
    Phase 4 — live inference with persistent tracker IDs.

    Returns the same detection dicts as run_inference_basic, plus:
      - `track_id` (int | None): the raw tracker id of THIS box
      - `worker_track_id` (str | None): "track_LIVE_<n>" if the detection
        belongs to a tracked Person, otherwise None. For PPE / violation
        boxes, we look up the Person box that contains (or best overlaps)
        this detection and inherit that Person's track id.

    persist=True keeps the tracker's state across successive .track() calls,
    which is the whole reason re-id works frame-to-frame.
    """
    global _TRACKER_LOGGED
    if not _TRACKER_LOGGED:
        _TRACKER_LOGGED = True
        try:
            import yaml
            cfg = yaml.safe_load(open(_TRACKER_CFG))
            print(f"[tracker] config={_TRACKER_CFG.name}  type={cfg.get('tracker_type')}  "
                  f"with_reid={cfg.get('with_reid')}  model={cfg.get('model')}  "
                  f"appearance_thresh={cfg.get('appearance_thresh')}  "
                  f"track_buffer={cfg.get('track_buffer')}")
        except Exception as e:
            print(f"[tracker] failed to read tracker config: {type(e).__name__}: {e}")

    # BoT-SORT (with Re-ID) config; falls back to ByteTrack-style motion-only
    # matching if the YAML can't be parsed by ultralytics.
    results = model_live.track(
        image, conf=CONF_THRESHOLD, persist=True,
        tracker=str(_TRACKER_CFG), verbose=False,
    )

    raw: list[dict] = []
    for r in results:
        if r.boxes is None: continue
        for box in r.boxes:
            conf = float(box.conf[0])
            if conf < CONF_THRESHOLD: continue
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            cls = int(box.cls[0])
            class_name = model_live.names[cls]
            track_id = None
            tid_t = getattr(box, "id", None)
            if tid_t is not None:
                try: track_id = int(tid_t[0].item())
                except Exception: track_id = None
            raw.append({
                "class"       : class_name,
                "confidence"  : round(conf, 2),
                "box"         : [round(x1), round(y1), round(x2), round(y2)],
                "is_violation": class_name in VIOLATION_CLASSES,
                "track_id"    : track_id,
            })

    # Build a list of (person_box, track_id, confidence) for boxes the
    # tracker actually assigned an id to. We use these as the "workers".
    persons = [
        (d["box"], d["track_id"], d["confidence"])
        for d in raw
        if d["class"] == "Person" and d["track_id"] is not None
    ]

    for det in raw:
        wtid: Optional[int] = None
        if det["class"] == "Person":
            wtid = det["track_id"]
        elif persons:
            wtid = _assign_to_person(det["box"], persons)
        det["worker_track_id"] = f"track_LIVE_{wtid}" if wtid is not None else None

    return raw


def _assign_to_person(item_box, persons) -> "int | None":
    """
    Pick the most plausible Person track id for a non-Person detection box.

    Rule: prefer the highest-confidence Person whose box CONTAINS the item's
    centroid; if none contain it, fall back to the Person with the largest IoU.
    """
    cx = (item_box[0] + item_box[2]) / 2
    cy = (item_box[1] + item_box[3]) / 2

    containing = [
        (tid, conf) for pbox, tid, conf in persons
        if pbox[0] <= cx <= pbox[2] and pbox[1] <= cy <= pbox[3]
    ]
    if containing:
        containing.sort(key=lambda x: -x[1])  # highest conf first
        return containing[0][0]

    # Fallback: largest IoU
    best = (None, 0.0)
    for pbox, tid, _ in persons:
        iou = calculate_iou(item_box, pbox)
        if iou > best[1]:
            best = (tid, iou)
    return best[0]

def run_inference_advanced(image) -> list:
    results = model_static(image, conf=CONF_THRESHOLD) 
    raw_detections = []
    for r in results:
        for box in r.boxes:
            conf = float(box.conf[0])
            cls = int(box.cls[0])
            class_name = model_static.names[cls]
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            box_coords = [round(x1), round(y1), round(x2), round(y2)]
            if class_name == "Person" and not is_valid_person(box_coords, conf): continue
            raw_detections.append({
                "class"       : class_name,
                "confidence"  : round(conf, 2),
                "box"         : box_coords,
                "is_violation": class_name in VIOLATION_CLASSES,
            })
            
    person_boxes = [d["box"] for d in raw_detections if d["class"] == "Person"]
    spatial_filtered_detections = []
    for det in raw_detections:
        if det["class"] in REQUIRES_PERSON:
            is_correctly_worn, overlaps_someone = check_ppe_status(person_boxes, det["box"], det["class"])
            if is_correctly_worn:
                spatial_filtered_detections.append(det)
            elif not overlaps_someone and det["confidence"] >= TRUST_THRESHOLD:
                spatial_filtered_detections.append(det)
        else:
            spatial_filtered_detections.append(det)

    spatial_filtered_detections = sorted(spatial_filtered_detections, key=lambda x: x['confidence'], reverse=True)
    final_detections = []
    for det in spatial_filtered_detections:
        keep = True
        for kept_det in final_detections:
            iou = calculate_iou(det["box"], kept_det["box"])
            iosa = calculate_iosa(det["box"], kept_det["box"])
            pair = {det["class"], kept_det["class"]}
            is_opposite = pair in MUTUALLY_EXCLUSIVE_PAIRS
            is_duplicate = (det["class"] == kept_det["class"])
            if (iou > NMS_IOU_THRESHOLD and (is_opposite or is_duplicate)) or (iosa > NESTED_IOSA_THRESHOLD and is_duplicate):
                keep = False
                break
        if keep: final_detections.append(det)
    return final_detections

def process_video_frames(input_path: str, process_every_n: int = 3) -> tuple:
    uid      = uuid.uuid4().hex
    out_path = input_path.replace(".mp4", f"_{uid}_out.webm")

    cap    = cv2.VideoCapture(input_path)
    fps    = int(cap.get(cv2.CAP_PROP_FPS)) or 25
    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if width == 0 or height == 0:
        cap.release()
        raise HTTPException(status_code=400, detail="Could not read video.")

    fourcc = cv2.VideoWriter_fourcc(*"vp80")
    out    = cv2.VideoWriter(out_path, fourcc, fps, (width, height))

    frame_count = 0
    max_det = 0
    max_ppe = 0
    incident_count = 0
    type_counts = defaultdict(int)
    
    grace_frames = fps * 5 
    history_buffer = [] 
    last_detections = []

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret: break
        frame_count += 1

        if frame_count % process_every_n == 1 or process_every_n == 1:
            pil_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            last_detections = run_inference_advanced(pil_img)
            
            max_det = max(max_det, len(last_detections))
            max_ppe = max(max_ppe, len([d for d in last_detections if d["class"] in WEARABLE_PPE]))
            
            current_counts = defaultdict(int)
            for d in last_detections:
                if d["is_violation"]:
                    current_counts[d["class"]] += 1
            
            history_buffer.append({"frame": frame_count, "counts": current_counts})
            history_buffer = [h for h in history_buffer if frame_count - h["frame"] <= grace_frames]
            
            max_in_window = defaultdict(int)
            for h in history_buffer:
                if h["frame"] == frame_count: continue 
                for v, c in h["counts"].items():
                    max_in_window[v] = max(max_in_window[v], c)
                    
            for v, current_n in current_counts.items():
                stable_n = max_in_window[v]
                if current_n > stable_n:
                    new_instances = current_n - stable_n
                    incident_count += new_instances
                    type_counts[v] += new_instances

        has_violation = any(d["is_violation"] for d in last_detections)
        if has_violation:
            cv2.rectangle(frame, (0, 0), (width, height), (0, 0, 255), 8)
            cv2.rectangle(frame, (0, 0), (width, 45), (0, 0, 255), -1)
            cv2.putText(frame, "WARNING: SAFETY VIOLATION DETECTED", (10, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)

        annotated = annotate_frame(frame, last_detections)
        out.write(annotated)

    cap.release()
    out.release()

    summary_data = {
        "total_frames": frame_count,
        "max_det": max_det,
        "max_ppe": max_ppe,
        "incident_count": incident_count,
        "violations_found": list(type_counts.keys()),
        "violation_counts": dict(type_counts)
    }

    return out_path, summary_data