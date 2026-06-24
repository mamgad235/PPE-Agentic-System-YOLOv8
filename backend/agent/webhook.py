# backend/agent/webhook.py
"""
Supervisor webhook POST. Reads the URL from policy.yaml (supervisors[0]).
Swallows all network errors so the escalation loop never blocks.

The webhook body is shaped to look like a polished supervisor alert when
rendered by webhook.site (or any inspector): a one-line headline, a
human-readable message paragraph, a structured `details` block, and a
checklist of recommended actions.

For the defense demo: generate a free URL at https://webhook.site/, paste it
into policy.yaml under `supervisors[0].contact_webhook`, then keep that
webhook.site browser tab open during the demo to show the live POST landing.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .policy import load_policy

try:
    from zoneinfo import ZoneInfo
    _HAS_ZONEINFO = True
except ImportError:                  # pragma: no cover
    _HAS_ZONEINFO = False

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:                  # pragma: no cover
    _HAS_HTTPX = False


SITE_NAME = "PPE Guard Demo Site"

# Friendly phrases for the violation_type strings the detector emits.
# These slot into "A <phrase> violation has been observed ...".
_FRIENDLY_VIOLATION = {
    "NO-Hardhat":     "missing-hardhat",
    "NO-Mask":        "missing-mask",
    "NO-Safety Vest": "missing-safety-vest",
    "NO-Glove":       "missing-gloves",
    "NO-Goggles":     "missing-goggles",
}

# Per-violation recommended actions a supervisor would actually run through.
_ACTION_PLAYBOOK = {
    "NO-Hardhat": [
        "Dispatch a safety officer to the affected zone immediately.",
        "Verify the worker is fitted with a hardhat before resuming work.",
        "Log a verbal warning in the worker's safety record.",
    ],
    "NO-Mask": [
        "Stop work in the affected zone and check ambient air-quality readings.",
        "Confirm respirator stock is available at the site entrance.",
        "Brief the worker on the mask requirement before letting them re-enter.",
    ],
    "NO-Safety Vest": [
        "Dispatch a safety officer to the affected zone immediately.",
        "Confirm high-visibility vest stock at the zone gate.",
        "Re-orient the worker on visibility-zone rules.",
    ],
}

_DEFAULT_ACTIONS = [
    "Dispatch a safety officer to the affected zone.",
    "Confirm required PPE is available on site.",
    "Brief the worker on the policy and re-authorize them to return to work.",
]


def _humanize_violation(vt: str) -> str:
    """'NO-Hardhat' -> 'missing-hardhat'. Slots into 'A <x> violation ...'."""
    return _FRIENDLY_VIOLATION.get(vt, vt.replace("NO-", "missing-").lower())


def _site_tz():
    """Resolve the site timezone configured in policy.yaml (falls back to UTC)."""
    name = (load_policy().site_timezone or "UTC").strip() or "UTC"
    if name == "UTC" or not _HAS_ZONEINFO:
        return timezone.utc, "UTC"
    try:
        return ZoneInfo(name), name
    except Exception as e:
        print(f"[agent] webhook: ZoneInfo({name!r}) failed: {e}. Falling back to UTC.")
        return timezone.utc, "UTC"


def _format_ts(iso_str: str) -> str:
    """
    '2026-05-22T16:09:52.861792+00:00' -> '2026-05-22 19:09 Africa/Cairo (UTC+03:00)'.
    Uses policy.yaml's `site_timezone` so the supervisor sees the time their
    workers were actually at — never raw UTC.
    """
    try:
        dt_utc = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt_utc.tzinfo is None:
            dt_utc = dt_utc.replace(tzinfo=timezone.utc)
        tzinfo, tz_label = _site_tz()
        local = dt_utc.astimezone(tzinfo)
        offset = local.utcoffset()
        if offset is None or tz_label == "UTC":
            return local.strftime("%Y-%m-%d %H:%M UTC")
        total_min = int(offset.total_seconds() // 60)
        sign      = "+" if total_min >= 0 else "-"
        hh, mm    = divmod(abs(total_min), 60)
        return local.strftime("%Y-%m-%d %H:%M") + f" {tz_label} (UTC{sign}{hh:02d}:{mm:02d})"
    except Exception:
        return iso_str


def _payload_from_event(event: dict) -> dict:
    """Translate an internal `agent_events` event into a polished webhook body."""
    incident_id  = event.get("incident_id")
    violation    = event.get("violation_type") or "PPE violation"
    zone_name    = event.get("zone_name")  or "General site"
    zone_id      = event.get("zone_id")    or "default"
    severity_raw = (event.get("severity") or "low")
    severity     = severity_raw.upper()
    repeats      = int(event.get("repeat_count") or 1)
    triggered_at = event.get("ts") or datetime.now(timezone.utc).isoformat()
    triggered_h  = _format_ts(triggered_at)
    friendly     = _humanize_violation(violation)
    actions      = _ACTION_PLAYBOOK.get(violation, _DEFAULT_ACTIONS)

    headline = (
        f"[{severity}] Repeated {violation} in {zone_name} "
        f"(incident #{incident_id})"
    )

    message = (
        f"Supervisor alert from {SITE_NAME}. "
        f"A {friendly} violation has been observed {repeats} times within the "
        f"escalation window in the {zone_name} zone ({zone_id}). "
        f"Severity is rated {severity}. "
        f"Incident #{incident_id} was opened at {triggered_h} and the "
        f"escalation rule 'escalate_supervisor_after_repeats' has been triggered. "
        f"Immediate on-site verification is required."
    )

    return {
        "event":               "ppe_incident_supervisor_alert",
        "site":                SITE_NAME,
        "severity":            severity,
        "headline":            headline,
        "message":             message,
        "details": {
            "incident_id":     incident_id,
            "violation_type":  violation,
            "zone": {
                "id":          zone_id,
                "name":        zone_name,
            },
            "repeat_count":    repeats,
            "triggered_at":    triggered_at,
            "triggered_at_human": triggered_h,
            "policy_rule":     "escalate_supervisor_after_repeats",
        },
        "recommended_actions": actions,
        "source": {
            "system":          "PPE Guard",
            "component":       "EscalationEngine",
            "version":         "phase-5",
        },
    }


async def notify_supervisor(event: dict) -> dict:
    """
    POST the event to the configured supervisor webhook. Returns a structured
    result (never raises) so callers can also expose it via an HTTP diagnostic.

    Return shape:
        {"ok": bool, "url": str | None, "status": int | None,
         "error": str | None, "body": dict | None, "skipped": str | None}
    """
    pol = load_policy()
    if not pol.supervisors:
        msg = "no supervisors configured in policy.yaml"
        print(f"[agent] supervisor webhook skipped: {msg}")
        return {"ok": False, "url": None, "status": None, "error": None,
                "body": None, "skipped": msg}
    url = (pol.supervisors[0].contact_webhook or "").strip()
    if not url or "REPLACE-ME" in url:
        msg = "placeholder URL. Generate one at https://webhook.site/ and paste it into policy.yaml."
        print(f"[agent] supervisor webhook skipped: {msg}")
        return {"ok": False, "url": url, "status": None, "error": None,
                "body": None, "skipped": msg}
    if not _HAS_HTTPX:
        msg = "httpx not installed (pip install httpx)"
        print(f"[agent] supervisor webhook skipped: {msg}")
        return {"ok": False, "url": url, "status": None, "error": None,
                "body": None, "skipped": msg}

    body = _payload_from_event(event)
    inc_id = body["details"]["incident_id"]
    # Pre-flight log so it's obvious from uvicorn output that the task started.
    # The actual response code follows.
    print(f"[agent] supervisor webhook POST -> {url}  (incident #{inc_id})")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=body)
        ok = resp.status_code < 400
        if ok:
            print(f"[agent] supervisor webhook OK   incident #{inc_id} -> HTTP {resp.status_code}")
        else:
            print(f"[agent] supervisor webhook FAIL incident #{inc_id} -> HTTP {resp.status_code}: {resp.text[:200]}")
        return {"ok": ok, "url": url, "status": resp.status_code,
                "error": None if ok else resp.text[:300],
                "body": body, "skipped": None}
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        print(f"[agent] supervisor webhook ERROR incident #{inc_id}: {err}")
        return {"ok": False, "url": url, "status": None, "error": err,
                "body": body, "skipped": None}
