# main.py
import asyncio
from fastapi import FastAPI, File, UploadFile, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel
from typing import Optional
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
# Note: `run_inference_basic_tracked` (BoT-SORT worker re-ID) is still
# defined in engine.py but is intentionally NOT imported here. The Phase 4
# worker-tracking pipeline was rolled back because tracker-ID churn produced
# spammy banners during the demo. The code is kept for future revival.

# --- Agentic layer (additive; never blocks detection responses) ---
from agent import init_db, log_detection, load_policy, bus, agent_ask
from agent.llm        import PROVIDER_MODELS, set_runtime_override, current_provider_and_model
from agent.escalation import EscalationEngine
from agent.webhook    import notify_supervisor
from agent.zones      import find_zone_for_box

app = FastAPI(title="PPE Detection API", version="2.0")

# Phase 3 — autonomous escalation engine (singleton). In-memory state machine;
# persistent incident rows still live in SQLite via storage.py.
_escalation_engine = EscalationEngine()


# Live-detection logging throttle. The live WebSocket pushes ~30 frames/s, and
# each frame typically contains the same persistent violations (e.g. "NO-Hardhat"
# on the same worker). Writing one Detection row per frame floods the DB and
# makes "how many violations today" return absurd counts (thousands of frames,
# not real violation events). We collapse repeated detections to at most one
# row per (camera, class) per second. Image and video paths are not throttled.
_live_log_last: dict[tuple[str, str], float] = {}
_LIVE_LOG_INTERVAL_S = 1.0


def _annotate_and_throttle_live(detections: list[dict], camera_id: str = "cam_0") -> list[dict]:
    """
    Pre-persistence post-processing for live-source detections:
      1. tag each detection with the zone_id its box center falls in, so the
         analytics agent can answer per-zone questions (instead of every row
         landing under 'unknown zone'),
      2. throttle to at most one row per (camera_id, class) per
         _LIVE_LOG_INTERVAL_S so a 30fps webcam stream doesn't produce 30
         duplicate rows per second.
    Returns the subset of detections that should actually be written. The
    full unthrottled batch still flows to bus.detections for escalation.
    """
    pol  = load_policy()
    now  = time.time()
    kept: list[dict] = []
    for d in detections:
        d = dict(d)  # avoid mutating caller's dict
        d["zone_id"] = find_zone_for_box(d.get("box") or [0, 0, 0, 0], pol.zones)
        key  = (camera_id, d.get("class", "unknown"))
        last = _live_log_last.get(key, 0.0)
        if (now - last) >= _LIVE_LOG_INTERVAL_S:
            _live_log_last[key] = now
            kept.append(d)
    return kept


@app.on_event("startup")
def _agent_startup():
    init_db()
    app.state.policy = load_policy()
    print(f"[agent] DB initialized, policy loaded: zones={len(app.state.policy.zones)}, llm={app.state.policy.llm.provider}/{app.state.policy.llm.model}")


@app.on_event("startup")
async def _start_escalation_worker():
    """Background coroutine that drives the escalation state machine."""
    asyncio.create_task(_escalation_worker_loop())
    print("[agent] escalation worker scheduled")


async def _escalation_worker_loop():
    q = bus.detections.subscribe()
    last_tick = time.time()
    try:
        while True:
            # Drain detection events. Only the live WebSocket publishes here.
            try:
                event = await asyncio.wait_for(q.get(), timeout=0.5)
                if event.get("source") == "live":
                    emits = _escalation_engine.process_detection_batch(
                        event.get("detections") or []
                    )
                    for e in emits: _emit_agent_event(e)
            except asyncio.TimeoutError:
                pass

            # Time-based transitions (audible_warning, auto_close) — tick ~1Hz
            now = time.time()
            if (now - last_tick) >= 1.0:
                for e in _escalation_engine.tick(): _emit_agent_event(e)
                last_tick = now
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[agent] escalation worker crashed: {type(e).__name__}: {e}")
    finally:
        bus.detections.unsubscribe(q)


# Strong references to in-flight webhook tasks. asyncio.create_task() returns
# a task that the event loop only tracks via a WeakSet — without holding our
# own reference, the GC can collect the task before httpx finishes its POST.
# That bug was making the dashboard show "Supervisor ✓" while the webhook
# never actually delivered anything.
_PENDING_WEBHOOK_TASKS: set[asyncio.Task] = set()


def _emit_agent_event(e: dict) -> None:
    """Broadcast event to /ws/agent_events and fire webhook on supervisor_alert."""
    bus.agent_events.publish(e)
    if e.get("type") == "supervisor_alert":
        inc_id = e.get("incident_id")
        print(f"[agent] supervisor_alert event for incident #{inc_id} — firing webhook task")
        task = asyncio.create_task(notify_supervisor(e))
        _PENDING_WEBHOOK_TASKS.add(task)
        # Remove from the set once done so it doesn't grow unbounded.
        task.add_done_callback(_PENDING_WEBHOOK_TASKS.discard)

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
async def detect_image(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    start      = time.time()
    img_bytes  = await file.read()
    image      = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    detections = run_inference_advanced(image)
    elapsed    = round(time.time() - start, 3)
    background_tasks.add_task(log_detection, "image", detections)
    return {
        "filename"        : file.filename,
        "inference_time_s": elapsed,
        "detections"      : detections,
        "summary"         : build_summary(detections),
    }

@app.post("/detect_url/")
def detect_image_url(body: URLRequest, background_tasks: BackgroundTasks):
    try:
        resp = requests.get(body.url, timeout=10)
        resp.raise_for_status()
    except Exception as e: raise HTTPException(status_code=400, detail=str(e))
    start      = time.time()
    image      = Image.open(io.BytesIO(resp.content)).convert("RGB")
    detections = run_inference_advanced(image)
    elapsed    = round(time.time() - start, 3)
    background_tasks.add_task(log_detection, "image", detections)
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

    # Persist a synthetic per-violation-type row so the analytics agent can
    # query video-source incidents alongside image/live ones.
    _log_video_summary(summary_data)

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
    _log_video_summary(summary_data)

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


def _log_video_summary(summary_data: dict) -> None:
    """
    Convert the video-processor's aggregated counts into one Detection row per
    distinct violation type, with a dummy box. Loses spatial precision but
    keeps the analytics surface unified across image/video/live sources.
    """
    rows = [
        {"class": vtype, "confidence": 0.0, "box": [0, 0, 0, 0], "is_violation": True}
        for vtype, _n in (summary_data.get("violation_counts") or {}).items()
    ]
    try: log_detection("video", rows)
    except Exception as e: print(f"[agent] log_detection(video) failed: {e}")

@app.get("/model_info/")
def model_info():
    return {
        "static_model"     : model_static_path,
        "live_model"       : model_live_path,
        "classes"          : CLASS_NAMES,
        "violation_classes": list(VIOLATION_CLASSES),
        "conf_threshold"   : CONF_THRESHOLD,
    }

class AgentAskRequest(BaseModel):
    question: str
    tz: Optional[str] = None   # IANA tz from the browser, e.g. "Africa/Cairo"

class SetProviderRequest(BaseModel):
    provider: str
    model: str

@app.get("/agent/providers")
def list_providers():
    return {
        "providers": PROVIDER_MODELS,
        "current":   current_provider_and_model(),
    }

@app.post("/agent/provider")
def set_provider(body: SetProviderRequest):
    p = (body.provider or "").lower()
    if p not in PROVIDER_MODELS:
        raise HTTPException(status_code=400, detail=f"unknown provider {p!r}; expected one of {list(PROVIDER_MODELS)}")
    set_runtime_override(p, body.model)
    return {"ok": True, **current_provider_and_model()}

@app.post("/agent/webhook/test")
async def agent_webhook_test():
    """
    Manual webhook self-test. Builds a fake supervisor_alert event and POSTs
    it to the configured webhook URL, awaiting the result so the caller can
    see the actual HTTP status from the URL in policy.yaml.

    Use this to isolate "is the URL alive" from "is the escalation logic
    firing". From the dashboard host:
        curl -X POST http://localhost:8000/agent/webhook/test
    """
    from datetime import datetime, timezone
    fake_event = {
        "type":            "supervisor_alert",
        "incident_id":     -1,                              # sentinel for diagnostic
        "violation_type":  "NO-Hardhat",
        "zone_id":         "zone_a",
        "zone_name":       "High-risk welding area",
        "severity":        "high",
        "repeat_count":    2,
        "ts":              datetime.now(timezone.utc).isoformat(),
    }
    result = await notify_supervisor(fake_event)
    # Trim the body payload to keep the response small
    if result.get("body"):
        result = {**result, "body_preview": {
            "headline": result["body"].get("headline"),
            "message":  (result["body"].get("message") or "")[:140] + "...",
        }}
        result.pop("body", None)
    return result


@app.post("/agent/ask")
async def agent_ask_endpoint(body: AgentAskRequest):
    q = (body.question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="question is required")
    try:
        return await asyncio.wait_for(agent_ask(q, tz=body.tz), timeout=60.0)
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="Agent did not finish within 60 seconds. Try a simpler question or rephrase.",
        )
    except RuntimeError as e:
        # Configuration errors (missing key, missing dep, etc.) → 503
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        # Catch-all so the frontend never sees a bare connection drop / Failed to fetch.
        # Return a clean JSON error instead.
        print(f"[agent] /agent/ask error: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")

@app.websocket("/ws/detect")
async def websocket_detect(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data       = await websocket.receive_bytes()
            image      = Image.open(io.BytesIO(data)).convert("RGB")
            # Untracked live inference. Phase 4 (BoT-SORT worker re-ID) was
            # rolled back because tracker-ID churn produced spammy banners
            # during the demo. The tracker code still exists in engine.py
            # (`run_inference_basic_tracked`) and can be re-enabled later.
            detections = run_inference_basic(image)
            await websocket.send_json({
                "detections": detections,
                "summary"   : build_summary(detections),
            })
            # Fire-and-forget agent hooks. Never block the inference loop.
            if detections:
                # Escalation engine sees every frame (it's stateful — keeps its
                # own first_seen/last_seen per incident bucket).
                bus.detections.publish({"source": "live", "detections": detections})
                # Persistence layer sees the throttled stream (1 row/s per class)
                # with zone_id annotated per box.
                persistable = _annotate_and_throttle_live(detections)
                if persistable:
                    asyncio.create_task(asyncio.to_thread(
                        log_detection, "live", persistable, "cam_0",
                    ))
    except WebSocketDisconnect:
        pass


@app.websocket("/ws/agent_events")
async def websocket_agent_events(websocket: WebSocket):
    """
    Phase 3 — broadcasts escalation events to the frontend overlay.

    Event payloads (all share incident_id, violation_type, zone_id, zone_name,
    severity, repeat_count, ts):
      - dashboard_notify  : new incident opened
      - audible_warning   : sustained violation, frontend should speak via TTS
      - supervisor_alert  : repeat threshold breached, webhook also POSTed
      - incident_closed   : auto-close after silence
    """
    await websocket.accept()
    q = bus.agent_events.subscribe()
    try:
        # Hello message so the frontend can confirm the connection landed.
        await websocket.send_json({"type": "hello", "ts": time.time()})
        while True:
            event = await q.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[agent] /ws/agent_events error: {type(e).__name__}: {e}")
    finally:
        bus.agent_events.unsubscribe(q)


@app.get("/agent/escalation/status")
def escalation_status():
    """Debug endpoint — current in-memory escalation state. Useful for showing
    the live state machine alongside the audit trail during the defense."""
    return {"active": _escalation_engine.snapshot()}


# ----------------------------------------------------------------------
# Live simulation mode.
#
# Publishes synthetic detection events to `bus.detections` from inside uvicorn
# at a configurable rate, so the full escalation pipeline (incident open ->
# audible warning -> supervisor alert -> auto-close -> reopen on re-violation)
# can be demoed without a camera attached. The simulator is a single asyncio
# task tracked at module scope so /start is idempotent and /stop is safe.
# ----------------------------------------------------------------------

_SIM_TASK: Optional[asyncio.Task] = None
_SIM_CONFIG: dict = {"rate_hz": 2.0, "violation_type": "NO-Hardhat", "zone": "zone_a"}

# Polygon coordinates inside zone_a (defined in policy.yaml as a 400x300 box
# rooted at (100, 100)) so the simulated detection lands in the right zone
# and inherits zone_a's higher severity multiplier. For 'default' we use a
# box outside any other polygon.
_SIM_BOXES = {
    "zone_a":  [200, 150, 350, 350],
    "default": [600, 50, 750, 200],
}


class SimStartRequest(BaseModel):
    rate_hz:        Optional[float] = None
    violation_type: Optional[str]   = None
    zone:           Optional[str]   = None


async def _sim_loop(rate_hz: float, violation_type: str, zone: str) -> None:
    """Inner loop — publishes synthetic 'live' detections forever."""
    period_s = max(0.05, 1.0 / max(0.1, rate_hz))
    box      = _SIM_BOXES.get(zone, _SIM_BOXES["zone_a"])
    print(f"[sim] start  rate={rate_hz}Hz  violation={violation_type}  zone={zone}")
    try:
        while True:
            bus.detections.publish({
                "source": "live",
                "detections": [{
                    "class":        violation_type,
                    "confidence":   0.85,
                    "box":          list(box),
                    "is_violation": True,
                    # Tag with zone_id so storage can short-circuit zone lookup.
                    "zone_id":      zone,
                }],
            })
            await asyncio.sleep(period_s)
    except asyncio.CancelledError:
        print("[sim] stop")
        raise


@app.post("/agent/sim/start")
async def sim_start(body: Optional[SimStartRequest] = None):
    """
    Start the in-process detection simulator. Idempotent — if already
    running, returns the existing config without starting a second task.
    """
    global _SIM_TASK, _SIM_CONFIG
    if _SIM_TASK is not None and not _SIM_TASK.done():
        return {"ok": True, "already_running": True, **_SIM_CONFIG}
    body = body or SimStartRequest()
    cfg = dict(_SIM_CONFIG)
    if body.rate_hz        is not None: cfg["rate_hz"]        = float(body.rate_hz)
    if body.violation_type is not None: cfg["violation_type"] = body.violation_type
    if body.zone           is not None: cfg["zone"]           = body.zone
    _SIM_CONFIG = cfg
    _SIM_TASK = asyncio.create_task(_sim_loop(**cfg))
    return {"ok": True, "already_running": False, **cfg}


@app.post("/agent/sim/stop")
async def sim_stop():
    """Cancel the simulator. Safe to call when nothing's running."""
    global _SIM_TASK
    if _SIM_TASK is None or _SIM_TASK.done():
        return {"ok": True, "was_running": False}
    _SIM_TASK.cancel()
    try:
        await _SIM_TASK
    except (asyncio.CancelledError, Exception):
        pass
    _SIM_TASK = None
    return {"ok": True, "was_running": True}


@app.get("/agent/sim/status")
def sim_status():
    """Return whether the simulator is currently running, plus its config."""
    running = _SIM_TASK is not None and not _SIM_TASK.done()
    return {"running": running, **_SIM_CONFIG}


@app.get("/agent/incidents")
def list_incidents(
    status:         Optional[str] = None,   # "open" | "closed" | None=all
    violation_type: Optional[str] = None,   # e.g. "NO-Hardhat"
    zone_id:        Optional[str] = None,   # e.g. "zone_a" | "default"
    limit:          int           = 50,
):
    """
    Read-only incident list, newest first. Used by the Incidents tab and the
    Recent incidents strip on the live webcam tab. Pure SQL — no LLM call —
    so the dashboard can poll this every few seconds without burning budget.
    """
    from agent.storage import SessionLocal, Incident
    from sqlalchemy import select

    limit = max(1, min(int(limit or 50), 500))
    # Pure ID-descending sort. The seeder now writes incidents in
    # chronological order so id matches time order, and we don't want
    # closed-but-newer incidents (e.g. #8, #9) buried under older open
    # ones (#6, #7). Newest first — same rule as the "Recent" strip.
    stmt = select(Incident).order_by(Incident.id.desc())
    if status in ("open", "closed"):
        stmt = stmt.where(Incident.status == status)
    if violation_type:
        stmt = stmt.where(Incident.violation_type == violation_type)
    if zone_id:
        stmt = stmt.where(Incident.zone_id == zone_id)
    stmt = stmt.limit(limit)

    # SQLite's date type doesn't preserve tz, so SQLAlchemy reads tz-aware
    # writes back as naive UTC datetimes. We force a UTC suffix here so the
    # frontend's `new Date(iso)` parses them correctly — otherwise a freshly
    # created incident in Cairo (UTC+3) shows up as "3 hours ago".
    from datetime import timezone as _tz
    def _utc_iso(dt):
        if dt is None: return None
        if dt.tzinfo is None: dt = dt.replace(tzinfo=_tz.utc)
        return dt.isoformat()

    with SessionLocal() as s:
        rows = s.scalars(stmt).all()
        items = [
            {
                "id":             r.id,
                "opened_at":      _utc_iso(r.opened_at),
                "closed_at":      _utc_iso(r.closed_at),
                "violation_type": r.violation_type,
                "severity":       r.severity,
                "zone_id":        r.zone_id,
                "status":         r.status,
            } for r in rows
        ]
    return {"items": items, "count": len(items)}


@app.get("/agent/incidents/{incident_id}/report.pdf")
def incident_report_pdf(incident_id: int):
    """
    Phase 5 — one-page PDF incident report. Streams a fresh PDF on each call;
    no caching, since policy.yaml edits could change the timezone/site name.
    """
    from agent.report_pdf import build_incident_report
    from fastapi.responses import StreamingResponse

    try:
        pdf_bytes, filename = build_incident_report(incident_id)
    except LookupError:
        raise HTTPException(status_code=404, detail=f"incident #{incident_id} not found")
    except RuntimeError as e:
        # fpdf2 not installed, etc.
        raise HTTPException(status_code=503, detail=str(e))
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
