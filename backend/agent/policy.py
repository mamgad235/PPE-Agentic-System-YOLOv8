# backend/agent/policy.py
"""
Policy-as-code loader. Reads backend/agent/policy.yaml, validates with Pydantic,
and exposes a singleton Policy object.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel, Field, field_validator

POLICY_PATH = Path(__file__).parent / "policy.yaml"


class EscalationPolicy(BaseModel):
    notify_dashboard_after:            int = 1
    audible_warning_after_seconds:     int = 5
    escalate_supervisor_after_repeats: int = 3
    repeat_window_minutes:             int = 10
    auto_close_seconds:                int = 30
    # How long after an incident auto-closes a re-violation of the same
    # (zone, violation) will reopen the SAME incident instead of creating a
    # new one. Should be slightly larger than `auto_close_seconds` so a
    # worker bouncing in and out of frame keeps the same incident id.
    reopen_window_seconds:             int = 10


class ZonePolicy(BaseModel):
    id:                   str
    name:                 str
    polygon:              Optional[list[list[float]]] = None  # None = full frame
    required_ppe:         list[str] = Field(default_factory=list)
    severity_multiplier:  float = 1.0

    @field_validator("polygon")
    @classmethod
    def _validate_polygon(cls, v):
        if v is None: return v
        if len(v) < 3: raise ValueError("polygon needs at least 3 points")
        for pt in v:
            if len(pt) != 2: raise ValueError("each point must be [x, y]")
        return v


class SupervisorPolicy(BaseModel):
    name:             str
    contact_webhook:  str


class LLMPolicy(BaseModel):
    provider:        str = "groq"
    model:           str = "llama-3.3-70b-versatile"
    max_tool_turns:  int = 5


class Policy(BaseModel):
    escalation:   EscalationPolicy = Field(default_factory=EscalationPolicy)
    zones:        list[ZonePolicy] = Field(default_factory=list)
    supervisors:  list[SupervisorPolicy] = Field(default_factory=list)
    llm:          LLMPolicy = Field(default_factory=LLMPolicy)
    # IANA timezone used for any *server-initiated* output (webhook bodies,
    # background-task logs). /agent/ask requests use the browser's tz instead.
    site_timezone: str = "UTC"

    def zone(self, zone_id: str) -> Optional[ZonePolicy]:
        for z in self.zones:
            if z.id == zone_id: return z
        return None

    def default_zone(self) -> Optional[ZonePolicy]:
        return self.zone("default") or (self.zones[0] if self.zones else None)


_cached: Optional[Policy] = None


def load_policy(path: Optional[Path] = None, force_reload: bool = False) -> Policy:
    global _cached
    if _cached is not None and not force_reload: return _cached
    p = path or POLICY_PATH
    if not p.exists():
        _cached = Policy()  # ship with empty defaults if file missing
        return _cached
    with open(p, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    _cached = Policy(**raw)
    return _cached
