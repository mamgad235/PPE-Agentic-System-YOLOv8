# main.py
from fastapi import FastAPI, File, UploadFile, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel
from PIL import Image
import io
import tempfile
import os
import requests
import shutil
import time
import uuid
import json

from config import CLASS_NAMES, VIOLATION_CLASSES, CONF_THRESHOLD
from utils import build_summary
from engine import (
    run_inference_basic, 
    run_inference_advanced, 
    process_video_frames,
    model_static_path, 
    model_live_path
)

app = FastAPI(title="PPE Detection API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"], 
)

class URLRequest(BaseModel): 
    url: str

@app.get("/")
def health_check():
    return {
        "status"      : "PPE Detection API is running",
        "static_model": model_static_path,
        "live_model"  : model_live_path,
        "version"     : "2.0",
    }

@app.post("/detect/")
async def detect_image(file: UploadFile = File(...)):
    start      = time.time()
    img_bytes  = await file.read()
    image      = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    detections = run_inference_advanced(image)
    elapsed    = round(time.time() - start, 3)
    return {
        "filename"        : file.filename,
        "inference_time_s": elapsed,
        "detections"      : detections,
        "summary"         : build_summary(detections),
    }

@app.post("/detect_url/")
def detect_image_url(body: URLRequest):
    try:
        resp = requests.get(body.url, timeout=10)
        resp.raise_for_status()
    except Exception as e: raise HTTPException(status_code=400, detail=str(e))
    start      = time.time()
    image      = Image.open(io.BytesIO(resp.content)).convert("RGB")
    detections = run_inference_advanced(image)
    elapsed    = round(time.time() - start, 3)
    return {
        "url"             : body.url,
        "inference_time_s": elapsed,
        "detections"      : detections,
        "summary"         : build_summary(detections),
    }

@app.post("/detect_video/")
def detect_video(file: UploadFile = File(...)):
    uid     = uuid.uuid4().hex
    temp_in = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{uid}.mp4")
    temp_in.close()
    with open(temp_in.name, "wb") as f: shutil.copyfileobj(file.file, f)

    out_path, summary_data = process_video_frames(temp_in.name)

    def cleanup():
        for f in [temp_in.name, out_path]:
            try: os.remove(f)
            except: pass

    return FileResponse(
        out_path,
        media_type="video/webm",
        filename="ppe_annotated.webm",
        background=BackgroundTask(cleanup),
        headers={"X-Video-Summary": json.dumps(summary_data)},
    )

@app.post("/detect_video_url/")
def detect_video_url(body: URLRequest):
    try:
        resp = requests.get(body.url, timeout=30, stream=True)
        resp.raise_for_status()
    except Exception as e: raise HTTPException(status_code=400, detail=str(e))

    uid     = uuid.uuid4().hex
    temp_in = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{uid}.mp4")
    for chunk in resp.iter_content(chunk_size=1024 * 1024): temp_in.write(chunk)
    temp_in.close()

    out_path, summary_data = process_video_frames(temp_in.name)

    def cleanup():
        for f in [temp_in.name, out_path]:
            try: os.remove(f)
            except: pass

    return FileResponse(
        out_path,
        media_type="video/webm",
        filename="ppe_annotated.webm",
        background=BackgroundTask(cleanup),
        headers={"X-Video-Summary": json.dumps(summary_data)},
    )

@app.get("/model_info/")
def model_info():
    return {
        "static_model"     : model_static_path,
        "live_model"       : model_live_path,
        "classes"          : CLASS_NAMES,
        "violation_classes": list(VIOLATION_CLASSES),
        "conf_threshold"   : CONF_THRESHOLD,
    }

@app.websocket("/ws/detect")
async def websocket_detect(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data       = await websocket.receive_bytes()
            image      = Image.open(io.BytesIO(data)).convert("RGB")
            detections = run_inference_basic(image)
            await websocket.send_json({
                "detections": detections,
                "summary"   : build_summary(detections),
            })
    except WebSocketDisconnect:
        pass