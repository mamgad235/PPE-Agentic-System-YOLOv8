# backend/agent/escalation.py
"""
Phase 3 — Autonomous escalation agent.

Consumes detection events from `bus.detections` (live source only) and drives
the escalation state machine defined in policy.yaml:

  1. First violation in (zone, violation_type) -> open incident + dashboard_notify
  2. After audible_warning_after_seconds        -> audible_warning  (TTS on frontend)
  3. After N repeats within repeat_window       -> supervisor_alert (webhook POST)
  4. After auto_close_seconds of silence        -> close incident   + incident_closed

State is in-memory only — restarting uvicorn resets it. That's fine for a demo
system since persistent incident rows still live in SQLite, and the audit trail
records every transition via `log_action`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from .policy import load_policy
from .storage import open_incident, close_incident, log_action, reopen_recent_incident
from .zones import find_zone_for_box


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class _ActiveIncident:
    incident_id:     int
    first_seen:      datetime
    last_seen:       datetime
    warned:          bool = False        # audible_warning fired?
    escalated:       bool = False        # supervisor_alert fired?
    severity:        str  = "low"
    zone_id:         Optional[str] = None
    zone_name:       str  = ""
    repeat_count:    int  = 1            # how many incidents in this bucket within the rolling window


# (zone_id, violation_type). Phase 4's worker re-identification was rolled
# back, so worker identity is no longer part of (or stamped on) incidents.
# Two simultaneously-violating workers in the same zone still share one
# incident — that matches the ops-room mental model ("there's a hardhat
# issue in zone A") better than "open a new ticket per face".
_IncidentKey = tuple[Optional[str], str]


class EscalationEngine:
    def __init__(self) -> None:
        self._active:  dict[_IncidentKey, _ActiveIncident] = {}
        self._repeats: dict[_IncidentKey, list[datetime]]  = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_detection_batch(self, detections: list[dict]) -> list[dict]:
        """
        Inspect a batch of detections from one inference call. Open new incidents
        or extend existing ones. Returns the events to broadcast on
        `bus.agent_events`.
        """
        if not detections: return []
        pol = load_policy()
        events: list[dict] = []
        # One event per (zone, violation_type) per batch.
        seen_keys: set[_IncidentKey] = set()
        for d in detections:
            if not d.get("is_violation"): continue
            box  = d.get("box") or [0, 0, 0, 0]
            zid  = find_zone_for_box(box, pol.zones)
            zone = pol.zone(zid) if zid else None
            viol = d.get("class", "unknown")
            key  = (zid, viol)
            if key in seen_keys: continue
            seen_keys.add(key)
            events.extend(self._open_or_extend(key, zid, zone, viol, pol))
        return events

    def tick(self) -> list[dict]:
        """
        Periodic check (call ~1Hz) for time-based transitions: audible warnings
        and auto-close. Returns the events to broadcast.
        """
        pol         = load_policy()
        warn_after  = pol.escalation.audible_warning_after_seconds
        close_after = pol.escalation.auto_close_seconds
        events: list[dict] = []
        now = _now()
        for key, st in list(self._active.items()):
            # 1) audible warning after sustained violation
            if not st.warned and (now - st.first_seen).total_seconds() >= warn_after:
                st.warned = True
                log_action(
                    "audible_warning",
                    incident_id = st.incident_id,
                    reasoning   = f"Continuous violation >= {warn_after}s",
                    payload     = {"zone_id": st.zone_id, "violation_type": key[1]},
                    result      = "speech synthesis dispatched to dashboard",
                )
                events.append(self._event("audible_warning", st, key[1]))
            # 2) auto-close after silence
            if (now - st.last_seen).total_seconds() >= close_after:
                close_incident(st.incident_id)
                log_action(
                    "auto_close",
                    incident_id = st.incident_id,
                    reasoning   = f"No detections for {close_after}s",
                    payload     = {"zone_id": st.zone_id, "violation_type": key[1]},
                    result      = "incident closed",
                )
                events.append(self._event("incident_closed", st, key[1]))
                del self._active[key]
        return events

    def snapshot(self) -> list[dict]:
        """Debug helper — current in-memory state for /agent/escalation/status."""
        return [
            {
                "incident_id":     st.incident_id,
                "key":             {"zone_id": k[0], "violation_type": k[1]},
                "first_seen":      st.first_seen.isoformat(),
                "last_seen":       st.last_seen.isoformat(),
                "warned":          st.warned,
                "escalated":       st.escalated,
                "severity":        st.severity,
                "zone_name":       st.zone_name,
                "repeat_count":    st.repeat_count,
            } for k, st in self._active.items()
        ]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _open_or_extend(
        self, key, zid: Optional[str], zone, viol: str, pol,
    ) -> list[dict]:
        now = _now()
        st = self._active.get(key)
        if st is not None:
            st.last_seen = now
            return []

        sev = self._severity_from_zone(zone)

        # Rolling repeat counter: prune entries older than the window, append now
        repeats = self._repeats.setdefault(key, [])
        window  = timedelta(minutes=pol.escalation.repeat_window_minutes)
        repeats[:] = [t for t in repeats if (now - t) <= window]
        repeats.append(now)
        repeat_count = len(repeats)

        zone_name = zone.name if zone else "Unzoned"

        # Before inserting a brand-new row, see if the SAME (zone, violation)
        # was just closed seconds ago — that's a worker walking out of frame
        # and right back in. If so, reopen the closed incident instead of
        # generating a fresh id. Keeps the incident timeline coherent during
        # the demo. The window comes from policy.yaml; set it slightly
        # larger than auto_close_seconds so reopens trigger reliably.
        reopened_id = reopen_recent_incident(
            violation_type = viol,
            zone_id        = zid,
            within_seconds = pol.escalation.reopen_window_seconds,
        )

        if reopened_id is not None:
            inc_id  = reopened_id
            log_action(
                "reopen_incident",
                incident_id = inc_id,
                reasoning   = (
                    f"{viol} violation recurred in {zone_name} within the "
                    f"escalation window — reopening incident #{inc_id} instead "
                    f"of creating a new one."
                ),
                payload     = {"zone_id": zid, "violation_type": viol,
                               "severity": sev, "repeat_count": repeat_count},
                result      = f"incident #{inc_id} reopened",
            )
        else:
            inc_id = open_incident(
                violation_type = viol,
                zone_id        = zid,
                severity       = sev,
            )
            log_action(
                "open_incident",
                incident_id = inc_id,
                reasoning   = f"{viol} violation observed in {zone_name}",
                payload     = {"zone_id": zid, "violation_type": viol,
                               "severity": sev, "repeat_count": repeat_count},
                result      = f"incident #{inc_id} opened",
            )

        st = _ActiveIncident(
            incident_id  = inc_id,
            first_seen   = now,
            last_seen    = now,
            severity     = sev,
            zone_id      = zid,
            zone_name    = zone_name,
            repeat_count = repeat_count,
        )
        self._active[key] = st
        log_action(
            "dashboard_notify",
            incident_id = inc_id,
            reasoning   = "notify_dashboard_after threshold met",
            payload     = {"zone_id": zid, "violation_type": viol},
            result      = "dashboard event broadcast",
        )
        events: list[dict] = [self._event("dashboard_notify", st, viol)]

        # Supervisor escalation when the rolling repeat count crosses the
        # threshold. Fires on incident open (not via tick) so it's deterministic.
        if (
            repeat_count >= pol.escalation.escalate_supervisor_after_repeats
            and not st.escalated
        ):
            st.escalated = True
            log_action(
                "supervisor_alert",
                incident_id = inc_id,
                reasoning   = (
                    f"{repeat_count} repeats in last "
                    f"{pol.escalation.repeat_window_minutes}min >= threshold "
                    f"({pol.escalation.escalate_supervisor_after_repeats})"
                ),
                payload     = {"zone_id": zid, "violation_type": viol},
                result      = "supervisor webhook POST queued",
            )
            events.append(self._event("supervisor_alert", st, viol))

        return events

    def _event(self, etype: str, st: _ActiveIncident, viol: str) -> dict:
        return {
            "type":           etype,
            "incident_id":    st.incident_id,
            "violation_type": viol,
            "zone_id":        st.zone_id,
            "zone_name":      st.zone_name,
            "severity":       st.severity,
            "repeat_count":   st.repeat_count,
            "ts":             _now().isoformat(),
        }

    @staticmethod
    def _severity_from_zone(zone) -> str:
        # Severity inherits from the zone's policy.yaml severity_multiplier.
        mult = zone.severity_multiplier if zone else 1.0
        if mult >= 2.0: return "high"
        if mult >= 1.5: return "medium"
        return "low"
