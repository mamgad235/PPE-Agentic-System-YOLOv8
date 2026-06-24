# backend/agent/tools.py
"""
Analytics tools the agent can call.

Every tool function is wrapped with @audited so each call lands in the
agent_actions table (the explainability trail). The TOOL_SCHEMAS list at
the bottom is the JSON-schema description the LLM sees (OpenAI/Groq format).

Tools defined here:
    query_violations(start_iso, end_iso, violation_type=None, zone=None, worker_id=None)
    summarize_period(start_iso, end_iso)
    top_offenders(limit=5)
    get_incident(incident_id)
    draft_incident_email(incident_id)
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, func

from .audit import audited
from .storage import (
    Detection, Incident, AgentAction, SessionLocal, utcnow,
)
from .tz_context import utc_to_local_hour, get_user_tz_name, get_user_tz


def _iso_to_local_str(iso_str: Optional[str]) -> Optional[str]:
    """Format an ISO-8601 UTC timestamp in the active user's local timezone.
    Returns None if the input is None; returns the original on parse failure."""
    if not iso_str: return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(get_user_tz())
        # Human-friendly: "May 22, 2026 at 11:51 PM"
        return local.strftime("%B %-d, %Y at %-I:%M %p") \
               if not _is_windows() else local.strftime("%B %#d, %Y at %#I:%M %p")
    except Exception:
        return iso_str


def _is_windows() -> bool:
    """strftime() lacks %-I / %-d on Windows; detect once."""
    import sys
    return sys.platform.startswith("win")


# ---------- parsing helpers ----------

def _parse_iso(s: Optional[str], default: datetime) -> datetime:
    if not s: return default
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return default


def _window(start_iso: Optional[str], end_iso: Optional[str]) -> tuple[datetime, datetime]:
    end   = _parse_iso(end_iso,   utcnow())
    start = _parse_iso(start_iso, end - timedelta(days=1))
    return start, end


def _int(v, default: int) -> int:
    """Coerce LLM tool-call values to int. Accepts ints, floats, numeric strings.
    Falls back to `default` for anything else (including None)."""
    if v is None: return default
    if isinstance(v, bool): return default  # bool subclasses int — exclude
    if isinstance(v, int): return v
    if isinstance(v, float): return int(v)
    if isinstance(v, str):
        try: return int(v.strip())
        except ValueError:
            try: return int(float(v.strip()))
            except ValueError: return default
    return default


# ---------- tools ----------

@audited("query_violations")
def query_violations(
    start_iso: Optional[str] = None,
    end_iso:   Optional[str] = None,
    violation_type: Optional[str] = None,
    zone:           Optional[str] = None,
    worker_id:      Optional[str] = None,
    limit = 100,
) -> list[dict]:
    """Return raw violation rows within [start, end] with optional filters."""
    limit = _int(limit, 100)
    start, end = _window(start_iso, end_iso)
    with SessionLocal() as s:
        stmt = (
            select(Detection)
            .where(Detection.is_violation == True,
                   Detection.timestamp >= start,
                   Detection.timestamp <= end)
            .order_by(Detection.timestamp.desc())
            .limit(min(max(limit, 1), 500))
        )
        if violation_type: stmt = stmt.where(Detection.class_name == violation_type)
        if zone:           stmt = stmt.where(Detection.zone_id == zone)
        if worker_id:      stmt = stmt.where(Detection.worker_track_id == worker_id)

        rows = s.scalars(stmt).all()
        return [
            {
                "id": r.id,
                "timestamp": r.timestamp.isoformat(),
                "class":     r.class_name,
                "confidence": round(r.confidence, 2),
                "source":    r.source,
                "camera_id": r.camera_id,
                "zone":      r.zone_id,
                "worker":    r.worker_track_id,
            } for r in rows
        ]


@audited("summarize_period")
def summarize_period(
    start_iso: Optional[str] = None,
    end_iso:   Optional[str] = None,
    violation_type: Optional[str] = None,
    zone: Optional[str] = None,
) -> dict:
    """
    Aggregate **incident episodes** within a window: counts by type, zone,
    hour-of-day (using opened_at), plus the top 3 workers.

    Optional filters:
      - violation_type='NO-Hardhat' counts only hardhat episodes in the window.
      - zone='zone_a'               counts only incidents in that zone.

    Semantics: one continuous violation = one incident, regardless of how many
    frames the detector logged. This is the number a supervisor cares about
    ('how many distinct violation events happened') — not raw frame counts.
    """
    start, end = _window(start_iso, end_iso)
    with SessionLocal() as s:
        stmt = select(Incident).where(
            Incident.opened_at >= start, Incident.opened_at <= end,
        )
        if violation_type: stmt = stmt.where(Incident.violation_type == violation_type)
        if zone:           stmt = stmt.where(Incident.zone_id == zone)
        rows = s.scalars(stmt).all()

        by_type:   dict[str, int] = defaultdict(int)
        by_zone:   dict[str, int] = defaultdict(int)
        by_hour:   dict[int, int] = defaultdict(int)
        by_worker: dict[str, int] = defaultdict(int)
        by_status: dict[str, int] = defaultdict(int)
        by_severity: dict[str, int] = defaultdict(int)
        for r in rows:
            by_type[r.violation_type] += 1
            by_zone[r.zone_id or "unknown"] += 1
            # opened_at is stored UTC; report hour in the user's local tz so
            # "peak hour 21" doesn't show up at midnight for a UTC+3 user.
            by_hour[utc_to_local_hour(r.opened_at)] += 1
            by_worker[r.worker_track_id or "anonymous"] += 1
            by_status[r.status or "unknown"] += 1
            by_severity[r.severity or "low"] += 1

        top_workers = sorted(by_worker.items(), key=lambda kv: kv[1], reverse=True)[:3]
        tz_name = get_user_tz_name()
        result = {
            "window": {"start": start.isoformat(), "end": end.isoformat()},
            "unit": "incidents (episodes)",
            "total_incidents": len(rows),
            "by_type":     dict(by_type),
            "by_zone":     dict(by_zone),
            "by_hour_local": {f"{h:02d}": n for h, n in sorted(by_hour.items())},
            "by_hour_local_tz": tz_name,
            "by_status":   dict(by_status),
            "by_severity": dict(by_severity),
            "top_workers": [{"worker_track_id": w, "count": n} for w, n in top_workers],
        }
        filters = {}
        if violation_type: filters["violation_type"] = violation_type
        if zone:           filters["zone"] = zone
        if filters:        result["filters"] = filters
        return result


@audited("top_offenders")
def top_offenders(limit = 5, days = 7) -> list[dict]:
    """
    Workers with the most **incidents (episodes)** in the last `days` days.
    Counts distinct violation episodes opened against each worker, not raw
    detection frames.
    """
    limit = _int(limit, 5)
    days  = _int(days,  7)
    cutoff = utcnow() - timedelta(days=max(days, 1))
    with SessionLocal() as s:
        stmt = (
            select(Incident.worker_track_id, func.count(Incident.id).label("n"))
            .where(Incident.opened_at >= cutoff,
                   Incident.worker_track_id.isnot(None))
            .group_by(Incident.worker_track_id)
            .order_by(func.count(Incident.id).desc())
            .limit(min(max(limit, 1), 50))
        )
        rows = s.execute(stmt).all()
        return [{"worker_track_id": w, "incidents": int(n)} for w, n in rows]


@audited("list_incidents")
def list_incidents(status: str = "open", limit = 20) -> list[dict]:
    """List incidents, defaulting to open ones. Returns [] if none exist yet."""
    limit = _int(limit, 20)
    with SessionLocal() as s:
        stmt = select(Incident).order_by(Incident.opened_at.desc()).limit(min(max(limit, 1), 100))
        if status and status.lower() != "all":
            stmt = stmt.where(Incident.status == status.lower())
        rows = s.scalars(stmt).all()
        return [
            {
                "id": r.id,
                "opened_at": r.opened_at.isoformat(),
                "closed_at": r.closed_at.isoformat() if r.closed_at else None,
                "worker_track_id": r.worker_track_id,
                "violation_type":  r.violation_type,
                "severity":        r.severity,
                "zone_id":         r.zone_id,
                "status":          r.status,
            } for r in rows
        ]


@audited("get_incident")
def get_incident(incident_id) -> dict:
    """Full record of one incident: incident row + all AgentAction rows attached."""
    incident_id = _int(incident_id, -1)
    if incident_id < 0: return {"error": "invalid incident_id"}
    with SessionLocal() as s:
        inc = s.get(Incident, incident_id)
        if not inc:
            return {"error": f"incident {incident_id} not found"}
        actions = [
            {
                "id": a.id, "timestamp": a.timestamp.isoformat(),
                "action_name": a.action_name, "tool_used": a.tool_used,
                "reasoning":   a.reasoning,   "result":    a.result,
                "success":     a.success,
            }
            for a in inc.actions
        ]
        return {
            "id":              inc.id,
            "opened_at":       inc.opened_at.isoformat(),
            "closed_at":       inc.closed_at.isoformat() if inc.closed_at else None,
            "worker_track_id": inc.worker_track_id,
            "violation_type":  inc.violation_type,
            "severity":        inc.severity,
            "zone_id":         inc.zone_id,
            "status":          inc.status,
            "actions":         actions,
        }


@audited("draft_incident_email")
def draft_incident_email(incident_id) -> dict:
    """
    Return a *simplified* incident summary plus a composition instruction.
    The agent's next turn (final synthesis) composes the email body from this data.
    Doing it this way avoids a nested LLM round-trip and keeps the audit trail clean.

    Note: we deliberately strip the full AgentAction history here. Smaller models
    (Llama 8B in particular) sometimes misread that verbose structure as evidence
    of errors. A simple list of action names is enough for the email body.
    """
    incident_id = _int(incident_id, -1)
    if incident_id < 0: return {"error": "invalid incident_id"}
    payload = get_incident(incident_id)
    if "error" in payload: return payload

    summary = {
        "id":              payload["id"],
        # Local-time strings the LLM should use verbatim in the email body.
        "opened_at_local": _iso_to_local_str(payload["opened_at"]),
        "closed_at_local": _iso_to_local_str(payload.get("closed_at")),
        "timezone":        get_user_tz_name(),
        # Keep raw UTC ISO too, in case the LLM wants it as a parenthetical.
        "opened_at_utc":   payload["opened_at"],
        "closed_at_utc":   payload.get("closed_at"),
        "worker":          payload.get("worker_track_id"),
        "violation_type":  payload["violation_type"],
        "severity":        payload["severity"],
        "zone":            payload.get("zone_id"),
        "status":          payload["status"],
        "escalation_actions_taken": [a["action_name"] for a in payload.get("actions", []) if a.get("success")],
    }
    return {
        "instruction": (
            "Compose a concise, professional incident-report email body (4-7 sentences) "
            "addressed to the site safety supervisor using the incident summary below. "
            "Be factual; quote `opened_at_local` (and `closed_at_local` if present) in "
            "the email — those are already in the supervisor's local timezone "
            f"({get_user_tz_name()}). Never use the raw UTC ISO strings in the body. "
            "Mention violation type, zone, severity, and worker if known. End with one "
            "concrete next step. The data is reliable and complete — do not say there "
            "are errors or missing information. If a field is missing, simply omit it "
            "from the email rather than mentioning its absence. Return ONLY the email "
            "body as your final answer — do not call more tools."
        ),
        "incident": summary,
    }


# ---------- function-call schemas ----------

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "query_violations",
            "description": (
                "Fetch raw violation **detection frames** (one row per detector "
                "frame, not per episode) within a time window. Use this ONLY when "
                "the user explicitly asks for raw rows / individual detection "
                "records / camera frames. For high-level numbers like 'how many "
                "violations today', use summarize_period instead — that returns "
                "incident episode counts, which is the supervisor-facing number."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_iso":      {"type": "string", "description": "ISO 8601 start time (UTC). Defaults to 24h before end."},
                    "end_iso":        {"type": "string", "description": "ISO 8601 end time (UTC). Defaults to now."},
                    "violation_type": {"type": "string", "description": "Filter to a single class, e.g. 'NO-Hardhat', 'NO-Mask', 'NO-Safety Vest'."},
                    "zone":           {"type": "string", "description": "Filter by zone id, e.g. 'zone_a' or 'default'."},
                    "worker_id":      {"type": "string", "description": "Filter by worker track id."},
                    "limit":          {"type": "integer", "description": "Max rows (1-500). Default 100."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_period",
            "description": (
                "Aggregate **incident episodes** within a time window (one continuous "
                "violation = one incident, not one row per frame). Returns counts by "
                "violation_type, zone, hour-of-day, status, severity, plus the top 3 "
                "workers. THIS IS THE GO-TO TOOL for almost every counting / overview "
                "question — 'how many violations today', 'how many hardhat violations', "
                "'which zone is worst', 'when do violations peak'. Use the optional "
                "violation_type / zone filters to answer narrow questions in a single "
                "call instead of chaining tools."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_iso":      {"type": "string", "description": "ISO 8601 start time (UTC). Defaults to 24h before end."},
                    "end_iso":        {"type": "string", "description": "ISO 8601 end time (UTC). Defaults to now."},
                    "violation_type": {"type": "string", "description": "Filter to one class, e.g. 'NO-Hardhat', 'NO-Mask', 'NO-Safety Vest'."},
                    "zone":           {"type": "string", "description": "Filter by zone id, e.g. 'zone_a' or 'default'."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "top_offenders",
            "description": (
                "Return workers ranked by number of **incident episodes** they were "
                "involved in over the last N days. Counts distinct incidents per "
                "worker, not raw detection frames."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max number of workers (1-50). Default 5."},
                    "days":  {"type": "integer", "description": "Look-back window in days. Default 7."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_incidents",
            "description": (
                "List incidents, defaulting to open ones. Always call this first to discover "
                "what incidents exist before calling get_incident or draft_incident_email. "
                "Returns an empty list if no incidents have been created yet (incidents are "
                "produced by the escalation agent, which is not active in the current build "
                "— in that case, tell the user no incidents exist yet)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Filter: 'open' (default), 'closed', 'escalated', 'acknowledged', or 'all'."},
                    "limit":  {"type": "integer", "description": "Max rows (1-100). Default 20."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_incident",
            "description": "Return one incident and the full audit trail of agent actions attached to it. Call list_incidents first to find a valid id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "incident_id": {"type": "integer", "description": "The incident's numeric id."},
                },
                "required": ["incident_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draft_incident_email",
            "description": (
                "Fetch the incident's data plus an explicit composition instruction. "
                "After calling this, your NEXT response should be the email body itself "
                "as plain text — do not call any more tools."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "incident_id": {"type": "integer", "description": "The incident's numeric id (from list_incidents)."},
                },
                "required": ["incident_id"],
            },
        },
    },
]


# ---------- dispatcher (used by analytics_agent.py) ----------

TOOL_REGISTRY: dict[str, callable] = {
    "query_violations":     query_violations,
    "summarize_period":     summarize_period,
    "top_offenders":        top_offenders,
    "list_incidents":       list_incidents,
    "get_incident":         get_incident,
    "draft_incident_email": draft_incident_email,
}
