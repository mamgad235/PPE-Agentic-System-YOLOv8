# backend/agent/__init__.py
"""
Agentic layer for PPE Guard.

Additive only — does not modify existing detection, NMS, or spatial filtering.
Provides: persistence, policy-as-code, audit trail, in-process event bus,
zone geometry, and (in later phases) analytics + escalation agents.
"""

from .storage import (
    init_db,
    log_detection,
    open_incident,
    close_incident,
    log_action,
    recent_violations,
    incidents_by_status,
)
from .policy import load_policy, Policy
from .audit import audited
from .bus import bus
from .analytics_agent import ask as agent_ask

__all__ = [
    "init_db",
    "log_detection",
    "open_incident",
    "close_incident",
    "log_action",
    "recent_violations",
    "incidents_by_status",
    "load_policy",
    "Policy",
    "audited",
    "bus",
    "agent_ask",
]
