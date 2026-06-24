# Migration Notes — Agentic Layer

This document records every existing file touched as part of the agentic
upgrade and the rationale for each touch. New files created in `backend/agent/`
are not listed here — they are entirely additive.

## Phase 1 — Foundation

### `backend/main.py`

Four targeted additions. No existing response shape was changed; the agent
hooks all run after the response is composed (or fire-and-forget for the
websocket).

1. **Imports + startup event.** Imported `asyncio`, `BackgroundTasks`, and the
   `agent` package. Added an `@app.on_event("startup")` handler that calls
   `init_db()` and `load_policy()` and stashes the policy on `app.state`.
2. **`/detect/`.** Added a `background_tasks: BackgroundTasks` parameter and
   one call: `background_tasks.add_task(log_detection, "image", detections)`.
   The response shape is identical; persistence runs after FastAPI returns.
3. **`/detect_url/`.** Same treatment as `/detect/`.
4. **`/detect_video/` + `/detect_video_url/`.** Added one call to
   `_log_video_summary(summary_data)` immediately before the `FileResponse`.
   Because the existing endpoints already use `BackgroundTask(cleanup)` for
   the temp-file cleanup, the new helper writes synchronously — it only
   touches the aggregated counts, so it's a handful of SQLite inserts.
5. **`_log_video_summary` helper.** New private function near the bottom of
   the file. Converts the video processor's aggregated counts into one
   `Detection` row per distinct violation type (with a dummy box). The
   spatial precision is lost — the trade-off is a unified analytics surface
   so the agent can query video, image, and live sources the same way.
6. **`/ws/detect` websocket.** Two lines added after `send_json`:
   `bus.detections.publish(...)` and `asyncio.create_task(asyncio.to_thread(log_detection, ...))`.
   Both are fire-and-forget. The inference loop is never blocked.

### `backend/requirements.txt`

- Re-saved as **UTF-8** (was UTF-16 LE with BOM and CRLF). The original
  encoding is fine for Windows tooling but breaks `pip install -r` on Linux
  and some CI runners.
- **Added** `SQLAlchemy==2.0.36`.
- No existing pins removed or changed.

### New files (additive only — listed here for completeness, not as touches)

- `backend/agent/__init__.py`
- `backend/agent/storage.py`       — SQLAlchemy 2.x models + helper functions
- `backend/agent/policy.py`        — Pydantic-validated policy loader
- `backend/agent/policy.yaml`      — default policy (zones, escalation, supervisors, llm)
- `backend/agent/audit.py`         — `@audited` decorator
- `backend/agent/bus.py`           — in-process async event bus
- `backend/agent/zones.py`         — point/box-in-polygon, no Shapely
- `backend/.env.example`           — placeholders for LLM credentials
- `MIGRATION_NOTES.md`             — this file

## Verification

After pulling Phase 1, the existing behavior must be identical:

- `POST /detect/`, `/detect_url/`, `/detect_video/`, `/detect_video_url/`
  return the same JSON / FileResponse as before.
- `GET /` and `/model_info/` are unchanged.
- The websocket `/ws/detect` sends the same `{detections, summary}` payload.

The only externally visible change is the creation of
`backend/agent/ppe_guard.db` on first startup and rows accumulating in the
`detections` table as inference runs.

## Phase 2 — Analytics Agent (chatbot tab)

### New files

- `backend/agent/llm.py`              — Groq-backed `chat()` wrapper with function-calling support; provider swappable via `LLM_PROVIDER` env var
- `backend/agent/tools.py`            — Five analytics tools (`query_violations`, `summarize_period`, `top_offenders`, `get_incident`, `draft_incident_email`) all wrapped with `@audited`; plus `TOOL_SCHEMAS` (function-calling spec) and `TOOL_REGISTRY` (name → callable)
- `backend/agent/analytics_agent.py`  — `ask(question)` loop: system prompt → LLM → dispatch tools → repeat up to `policy.llm.max_tool_turns` → final answer
- `frontend/src/tabs/AgentTab.jsx`    — Chat-style UI with suggested-prompt chips, user/assistant bubbles, collapsible tool-call panel per turn

### Touched

- `backend/agent/__init__.py`     — exported `agent_ask` (re-export of `analytics_agent.ask`)
- `backend/main.py`               — imported `agent_ask`; added `AgentAskRequest` Pydantic model and `POST /agent/ask` endpoint. No existing routes changed.
- `backend/requirements.txt`      — appended `groq==0.13.0`
- `frontend/src/config.js`        — added `agent` entry to `NAV_ITEMS` and `PAGE_META`
- `frontend/src/App.jsx`          — imported `AgentTab`, added the `activeNav==="agent"` route

### Verification

- Install the new dep (`pip install groq==0.13.0` inside the second-copy venv)
- Put `GROQ_API_KEY=...` in `backend/.env` (free key at console.groq.com)
- Restart uvicorn; the existing startup line still fires
- Open the React app, click "Safety Agent" in the sidebar, click a suggested chip — you should see the agent's answer + a "Show N tool calls" link expanding the SQL-derived results

## Phase 2 patch — list_incidents tool + demo seeder

### New file

- `backend/agent/seed.py` — synthetic demo data generator. Inserts 7 demo workers, a configurable window of detections (default 7 days, ~50-90 rows/day, ~28% violations, peak afternoon hours), and 7 incidents with full audit trails (mix of open / closed / escalated, one obvious top offender at `track_W005`). Run with `python -m agent.seed --reset` from the backend folder.

### Touched

- `backend/agent/tools.py`     — added `list_incidents(status, limit)` tool; updated `TOOL_SCHEMAS` and `TOOL_REGISTRY`. The agent now has a way to discover what incidents exist before calling `get_incident` / `draft_incident_email`, which fixes the timeout loop when no incidents are present.
- `.gitignore`                 — added `backend/.env`, `backend/agent/ppe_guard.db`, `backend/agent/reports/`

## Phase 3 — Autonomous Escalation Engine

The shift from passive analytics to active supervision: a deterministic state
machine that opens, warns, escalates, and closes incidents on its own.

### New files

- `backend/agent/escalation.py`   — `EscalationEngine`, an in-memory deterministic state machine keyed by `(zone_id, violation_type)`. Drives the transitions defined in `policy.yaml`: open incident → audible warning → supervisor alert → auto-close, plus a reopen path for a worker bouncing in/out of frame.
- `backend/agent/webhook.py`      — `notify_supervisor(event)`: builds a polished structured-JSON alert (headline, message, recommended actions, site-local time) and POSTs it to the supervisor URL from `policy.yaml`. Swallows all network errors so escalation never blocks.
- `frontend/src/components/EscalationOverlay.jsx` — global overlay mounted at app root. Subscribes to `/ws/agent_events`, renders red incident banners, and speaks **audible warnings via the Web Speech API** (`window.speechSynthesis`). Auto-reconnects every 2 s.

### Touched

- `backend/agent/storage.py`   — added `open_incident`, `close_incident`, `reopen_recent_incident`, and `log_action` to persist incidents + the audit trail.
- `backend/agent/policy.yaml`  — populated `escalation` timings (audible 2 s, supervisor after 2 repeats, auto-close 8 s), `zones` with `severity_multiplier`, and `supervisors[0].contact_webhook`.
- `backend/main.py`            — added: a background `_escalation_worker_loop` (drains `bus.detections`, ticks the engine ~1 Hz), `_emit_agent_event` (broadcasts + fires the webhook task), the `/ws/agent_events` websocket, `/agent/escalation/status`, an in-process detection **simulator** (`/agent/sim/start|stop|status`) for camera-free demos, and `_annotate_and_throttle_live` (zone-tag + 1-row/s throttle before persistence).
- `backend/agent/__init__.py`  — exported the new storage helpers and `bus`.
- `frontend/src/App.jsx`       — mounted `<EscalationOverlay />` at the root so banners + speech persist across tab switches.

### Verification

- Start uvicorn + the React app, open the **Safety Agent** tab, click **Simulate violation**.
- Within ~2 s you should hear a spoken warning and see a red banner; after the repeat threshold a webhook fires (point `contact_webhook` at a free https://webhook.site/ URL to watch it land); after 8 s of silence the incident auto-closes.

## Phase 4 — Worker Re-Identification (BoT-SORT) — **rolled back**

Implemented but intentionally disabled in the live path for demo stability;
the code is kept for future revival.

### New files

- `backend/agent/botsort_ppe.yaml`  — BoT-SORT tracker config with appearance Re-ID (`with_reid: true`) so a worker who leaves and re-enters frame keeps the same track id.
- `backend/agent/bytetrack_ppe.yaml` — motion-only fallback config.

### Touched

- `backend/engine.py` — added `run_inference_basic_tracked` (persistent `.track()` with the BoT-SORT config) and `_assign_to_person` (inherits a Person's track id for nearby PPE boxes).

### Status

`run_inference_basic_tracked` is **deliberately not imported** in `main.py` —
the live `/ws/detect` path still uses the untracked `run_inference_basic`,
because tracker-ID churn produced spammy banners during the demo. Worker
attribution therefore runs on seeded data, not the live feed. Re-enabling is a
one-line import swap.

## Phase 5 — PDF Incident Reports, Incidents UI, multi-provider + timezone

### New files

- `backend/agent/report_pdf.py`     — `build_incident_report(id)`: a **deterministic** one-page PDF (via `fpdf2`) rendered from the incident row + its `agent_actions` (header, summary, escalation status, **Action Log**, footer). The LLM never writes it.
- `backend/agent/tz_context.py`     — per-request timezone context so "today/yesterday/peak hour" are computed in the user's local time, not UTC.
- `frontend/src/tabs/IncidentsTab.jsx` — incidents browser (polls `/agent/incidents` every 4 s) with filters and a one-click **Download PDF report** button; also exports `RecentIncidentsStrip` and `IncidentsBrowser`.

### Touched

- `backend/main.py`           — added `/agent/incidents`, `/agent/incidents/{id}/report.pdf`, `/agent/providers`, `/agent/provider` (runtime LLM switch), and `/agent/webhook/test`.
- `backend/agent/llm.py`      — added Gemini support via the OpenAI-compatible endpoint, a runtime provider/model override, short-rate-limit auto-retry, and friendly provider-error messages.
- `backend/agent/tools.py`    — tools now format timestamps/hours in the active user timezone (`tz_context`).
- `frontend/src/tabs/AgentTab.jsx` — added the provider/model dropdown (persisted to `localStorage`, pushed to `/agent/provider`), the Simulate-violation toggle, and the embedded collapsible Incidents panel. Sends the browser IANA timezone with every `/agent/ask`.

### Verification

- In the Safety Agent tab, expand the model picker and switch Groq ↔ Gemini (needs `GEMINI_API_KEY` in `.env` for Gemini).
- Open the Incidents panel, pick any incident, click **Download PDF** — the report opens with a complete, timestamped Action Log.

## Phase 6 — Live-path post-processing parity

A small hardening pass so the live feed isn't raw YOLO output.

### Touched

- `backend/engine.py` — `run_inference_basic` now applies two cheap guards before returning: `is_valid_person` (rejects background objects mis-detected as Person) and a light IoU/IoSA dedup (drops nested/duplicate same-class boxes the detector's built-in NMS misses, e.g. two stacked Person boxes on one worker). The full anatomical PPE-zone check remains image/video-only for latency.

## Dependencies added across phases

`backend/requirements.txt` gained (beyond Phase 1's `SQLAlchemy` and Phase 2's
`groq`): `fpdf2==2.7.9` (PDF reports), `openai` (Gemini compat client),
`tzdata` (timezone DB on Windows). `httpx` and `PyYAML` were already present.

## `.gitignore`

Hardened for a clean push: global `__pycache__/` + `*.py[cod]` (covers
`backend/agent/__pycache__/`), global `.env` (keeps `.env.example` tracked),
OS/editor junk, and temp files. Secrets (`backend/.env`), the SQLite DB
(`backend/agent/ppe_guard.db`), and generated `backend/agent/reports/` remain
ignored. The trained weights under `runs/detect/train4` and `train6` are kept
(both `best.pt` are < 100 MB).
