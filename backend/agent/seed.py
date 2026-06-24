# backend/agent/seed.py
"""
Seed the agent DB with a realistic week of synthetic site detection data so
the Safety Agent has interesting questions to answer during the defense.

Run from the backend/ folder with the venv activated:

    python -m agent.seed                # append synthetic data (no wipe)
    python -m agent.seed --reset        # wipe ALL existing rows first
    python -m agent.seed --reset --days 14   # seed 14 days instead of 7

The seeder uses fixed random seed so the output is deterministic across runs.
Workers, zones, violation patterns, and a handful of incidents (with audit
trails) are generated. Times skew to working hours, with peak afternoon spike.
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from .storage import (
    init_db, SessionLocal, utcnow,
    Detection, Incident, AgentAction, Worker, Zone,
)
from .policy import load_policy

# ---------- demo cast ----------

DEMO_WORKERS = [
    ("track_W001", "Ahmed Mostafa"),
    ("track_W002", "Mariam Ibrahim"),
    ("track_W003", "Khaled Ali"),
    ("track_W004", "Salma Hassan"),
    ("track_W005", "Tarek Saeed"),   # repeat offender
    ("track_W006", "Nour Adel"),
    ("track_W007", "Yousef Sami"),
]

VIOLATION_TYPES = ["NO-Hardhat", "NO-Mask", "NO-Safety Vest"]
COMPLIANT_TYPES = ["Hardhat", "Mask", "Safety Vest", "Person"]

# Hour-of-day weights — peak afternoon, lunch lull, evening drop-off.
HOUR_WEIGHTS = {
    7: 4, 8: 6, 9: 7, 10: 8, 11: 7, 12: 3, 13: 5,
    14: 9, 15: 10, 16: 8, 17: 5, 18: 2,
}

# Per-worker bias — track_W005 violates 4x more often than others.
WORKER_VIOLATION_WEIGHT = {
    "track_W001": 1.0, "track_W002": 1.2, "track_W003": 0.8,
    "track_W004": 0.6, "track_W005": 4.0, "track_W006": 1.1,
    "track_W007": 1.0,
}


def _seeded_random() -> random.Random:
    r = random.Random()
    r.seed(20260522)  # deterministic
    return r


def _wipe(s) -> None:
    """Delete all rows from agent-owned tables. Detection table is preserved unless --reset."""
    s.execute(delete(AgentAction))
    s.execute(delete(Incident))
    s.execute(delete(Detection))
    s.execute(delete(Worker))
    # Don't wipe Zone — those mirror policy.yaml on next startup
    s.commit()


def _ensure_workers(s) -> None:
    existing = {w.track_id for w in s.query(Worker).all()}
    for track_id, name in DEMO_WORKERS:
        if track_id in existing: continue
        s.add(Worker(track_id=track_id, display_name=name))
    s.commit()


def _mirror_zones_from_policy(s) -> None:
    """Drop and re-insert Zone rows from the policy file."""
    pol = load_policy()
    s.execute(delete(Zone))
    for z in pol.zones:
        s.add(Zone(
            id=z.id, name=z.name,
            polygon_json=json.dumps(z.polygon),
            required_ppe_json=json.dumps(z.required_ppe),
            severity_multiplier=z.severity_multiplier,
        ))
    s.commit()


def _pick_hour(r: random.Random) -> int:
    pool = []
    for hour, weight in HOUR_WEIGHTS.items(): pool.extend([hour] * weight)
    return r.choice(pool)


def _pick_worker(r: random.Random, want_violation: bool) -> str:
    pool = []
    for track_id, _ in DEMO_WORKERS:
        weight = WORKER_VIOLATION_WEIGHT[track_id] if want_violation else 1.0
        pool.extend([track_id] * max(1, int(weight * 10)))
    return r.choice(pool)


def _generate_detections(s, r: random.Random, days: int) -> int:
    """Insert a week+ of detections. Violations and compliant frames mixed."""
    now = utcnow()
    inserted = 0
    pol = load_policy()
    zone_ids = [z.id for z in pol.zones] or [None]

    for day_offset in range(days):
        day = now - timedelta(days=day_offset)
        # 40-90 detections per day, weighted toward weekdays
        n_today = r.randint(40, 90) if day.weekday() < 5 else r.randint(15, 35)
        for _ in range(n_today):
            hour    = _pick_hour(r)
            minute  = r.randint(0, 59)
            second  = r.randint(0, 59)
            ts      = day.replace(hour=hour, minute=minute, second=second, microsecond=0)

            # ~28% of detections are violations
            is_viol = r.random() < 0.28
            cls     = r.choice(VIOLATION_TYPES if is_viol else COMPLIANT_TYPES)
            worker  = _pick_worker(r, is_viol)
            zone    = r.choices(zone_ids, weights=[2 if z == "zone_a" else 1 for z in zone_ids], k=1)[0]

            s.add(Detection(
                timestamp       = ts,
                source          = r.choice(["live", "video", "image"]),
                camera_id       = r.choice(["cam_0", "cam_1", "cam_2"]),
                class_name      = cls,
                confidence      = round(r.uniform(0.55, 0.97), 2),
                box_x1=r.randint(50, 400), box_y1=r.randint(50, 300),
                box_x2=r.randint(450, 800), box_y2=r.randint(350, 600),
                is_violation    = is_viol,
                worker_track_id = worker,
                zone_id         = zone,
            ))
            inserted += 1
    s.commit()
    return inserted


def _generate_incidents(s, r: random.Random) -> int:
    """Create a handful of incidents (mix of statuses) with realistic audit trails."""
    now = utcnow()
    inserted = 0

    incidents_to_make = [
        # (days_ago, hours_ago, worker, violation, zone, severity, status, escalated)
        (0, 1,  "track_W005", "NO-Hardhat",     "zone_a", "high",   "open",       True),
        (0, 4,  "track_W002", "NO-Mask",        "default","low",    "open",       False),
        (1, 8,  "track_W005", "NO-Safety Vest", "zone_a", "high",   "escalated",  True),
        (2, 14, "track_W001", "NO-Hardhat",     "default","medium", "closed",     True),
        (3, 9,  "track_W005", "NO-Hardhat",     "zone_a", "high",   "closed",     True),
        (4, 11, "track_W006", "NO-Mask",        "default","low",    "closed",     False),
        (5, 15, "track_W003", "NO-Safety Vest", "default","medium", "closed",     True),
    ]
    # Insert oldest first so the auto-increment ids line up with chronological
    # order: #1 = the oldest seeded incident, the highest id = the newest.
    # Total seconds-ago = days_ago * 86400 + hours_ago * 3600. Sort DESC by
    # seconds-ago to get oldest-first.
    incidents_to_make.sort(key=lambda x: -(x[0] * 86400 + x[1] * 3600))

    for days_ago, hours_ago, worker, vtype, zone, severity, status, escalated in incidents_to_make:
        opened_at  = now - timedelta(days=days_ago, hours=hours_ago)
        closed_at  = None if status == "open" else opened_at + timedelta(minutes=r.randint(8, 45))

        inc = Incident(
            opened_at       = opened_at,
            closed_at       = closed_at,
            worker_track_id = worker,
            violation_type  = vtype,
            severity        = severity,
            zone_id         = zone,
            status          = status,
        )
        s.add(inc); s.flush()  # need inc.id

        # Audit trail: notify_dashboard → maybe audible → maybe supervisor → maybe close
        s.add(AgentAction(
            timestamp=opened_at, incident_id=inc.id,
            action_name="notify_dashboard", tool_used="notify_dashboard",
            reasoning=f"rule:first_violation, zone={zone}, severity={severity}",
            payload_json=json.dumps({"worker": worker, "violation": vtype}),
            result="Dashboard banner broadcast", success=True,
        ))
        if escalated:
            s.add(AgentAction(
                timestamp=opened_at + timedelta(seconds=6), incident_id=inc.id,
                action_name="audible_warning", tool_used="tool_play_audible_warning",
                reasoning=f"rule:violation_active>5s, zone={zone}",
                payload_json=json.dumps({"message": f"Warning: {vtype.replace('NO-','')} required in {zone}."}),
                result="TTS broadcast on webcam tab", success=True,
            ))
            s.add(AgentAction(
                timestamp=opened_at + timedelta(minutes=2), incident_id=inc.id,
                action_name="notify_supervisor", tool_used="tool_notify_supervisor",
                reasoning=f"rule:repeat_3_within_10min, zone={zone}, severity_multiplier=2.0" if zone == "zone_a" else "rule:repeat_3_within_10min",
                payload_json=json.dumps({"webhook": "https://webhook.site/demo", "body": "(LLM-drafted incident summary)"}),
                result="HTTP 200", success=True,
            ))
        if status == "closed":
            s.add(AgentAction(
                timestamp=closed_at, incident_id=inc.id,
                action_name="auto_close", tool_used="auto_close",
                reasoning=f"rule:no_new_detections_within_{30}s",
                payload_json=json.dumps({}),
                result="incident closed", success=True,
            ))
        inserted += 1

    s.commit()
    return inserted


def main(reset: bool = False, days: int = 7) -> None:
    init_db()
    r = _seeded_random()
    with SessionLocal() as s:
        if reset:
            print("[seed] --reset: wiping detections, incidents, actions, workers...")
            _wipe(s)
        _mirror_zones_from_policy(s)
        _ensure_workers(s)
        det_n = _generate_detections(s, r, days)
        inc_n = _generate_incidents(s, r)
        # Quick visible summary
        from sqlalchemy import select, func
        v_total = s.scalar(select(func.count(Detection.id)).where(Detection.is_violation == True))
        d_total = s.scalar(select(func.count(Detection.id)))
        a_total = s.scalar(select(func.count(AgentAction.id)))
        print(f"[seed] inserted {det_n} detections over {days} days "
              f"({v_total} violations of {d_total} total rows)")
        print(f"[seed] inserted {inc_n} incidents with {a_total} audit-trail actions")
        print(f"[seed] workers: {len(DEMO_WORKERS)} (top offender: track_W005)")
        print("[seed] Try the Safety Agent now with prompts like:")
        print("       \"who is the top offender this week\"")
        print("       \"summarize today's violations\"")
        print("       \"list open incidents\"")
        print("       \"draft an incident email for the most recent open incident\"")


def simulate(api: str, rate_hz: float, violation_type: str, zone: str) -> None:
    """
    Live-simulation mode. Asks the running uvicorn to publish synthetic
    detection events to bus.detections at `rate_hz` Hz so the escalation
    agent fires end-to-end without a camera attached.

    Blocks until Ctrl-C, then asks uvicorn to stop the loop.
    """
    try:
        import requests
    except ImportError:
        print("[sim] `requests` not installed. Run: pip install requests")
        return

    start_url = f"{api.rstrip('/')}/agent/sim/start"
    stop_url  = f"{api.rstrip('/')}/agent/sim/stop"
    status_url = f"{api.rstrip('/')}/agent/sim/status"
    body = {"rate_hz": rate_hz, "violation_type": violation_type, "zone": zone}

    print(f"[sim] POST {start_url}  body={body}")
    try:
        r = requests.post(start_url, json=body, timeout=5)
        r.raise_for_status()
        print(f"[sim] backend responded: {r.json()}")
    except Exception as e:
        print(f"[sim] failed to start: {type(e).__name__}: {e}")
        print(f"[sim] is uvicorn running at {api}? Try: uvicorn main:app --reload")
        return

    print(f"[sim] running at {rate_hz} Hz. Press Ctrl-C to stop.")
    try:
        import time as _t
        while True:
            _t.sleep(1.0)
            # Light heartbeat — every 5s confirm the sim is still alive.
            # If uvicorn restarts the loop is gone and we should bail.
            try:
                st = requests.get(status_url, timeout=2).json()
                if not st.get("running"):
                    print("[sim] backend says simulator no longer running. Exiting.")
                    return
            except Exception:
                pass
    except KeyboardInterrupt:
        print("\n[sim] Ctrl-C received, stopping simulator...")
        try:
            r = requests.post(stop_url, timeout=5)
            print(f"[sim] {r.json()}")
        except Exception as e:
            print(f"[sim] stop call failed (sim may still be running): {e}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Seed PPE Guard demo data.")
    ap.add_argument("--reset",    action="store_true", help="Wipe all existing data first")
    ap.add_argument("--days",     type=int, default=7, help="Days of history to generate (default 7)")
    ap.add_argument("--simulate", action="store_true",
                    help="Live-simulation mode: publish synthetic detection events to "
                         "the running uvicorn's bus.detections so the escalation agent "
                         "fires end-to-end without a camera attached.")
    ap.add_argument("--api",      type=str, default="http://127.0.0.1:8000",
                    help="(--simulate only) uvicorn base URL")
    ap.add_argument("--rate",     type=float, default=2.0,
                    help="(--simulate only) publish rate in Hz, default 2.0")
    ap.add_argument("--zone",     type=str, default="zone_a",
                    help="(--simulate only) target zone id, default zone_a")
    ap.add_argument("--violation", type=str, default="NO-Hardhat",
                    help="(--simulate only) violation class, default NO-Hardhat")
    args = ap.parse_args()
    if args.simulate:
        simulate(api=args.api, rate_hz=args.rate,
                 violation_type=args.violation, zone=args.zone)
    else:
        main(reset=args.reset, days=args.days)
