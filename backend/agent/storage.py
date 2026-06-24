# backend/agent/storage.py
"""
SQLAlchemy 2.x storage layer for the agentic system.
SQLite DB at backend/agent/ppe_guard.db. Auto-created on init_db().
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer, String, Text,
    create_engine, select, func,
)
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker, Session,
)

DB_PATH = Path(__file__).parent / "ppe_guard.db"
_ENGINE = create_engine(f"sqlite:///{DB_PATH}", future=True, echo=False)
SessionLocal = sessionmaker(bind=_ENGINE, autoflush=False, expire_on_commit=False)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Detection(Base):
    __tablename__ = "detections"
    id:               Mapped[int]       = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp:        Mapped[datetime]  = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    source:           Mapped[str]       = mapped_column(String(16))   # image|video|live
    camera_id:        Mapped[str]       = mapped_column(String(64), default="cam_0", index=True)
    class_name:       Mapped[str]       = mapped_column(String(64), index=True)
    confidence:       Mapped[float]     = mapped_column(Float)
    box_x1:           Mapped[int]       = mapped_column(Integer)
    box_y1:           Mapped[int]       = mapped_column(Integer)
    box_x2:           Mapped[int]       = mapped_column(Integer)
    box_y2:           Mapped[int]       = mapped_column(Integer)
    is_violation:     Mapped[bool]      = mapped_column(Boolean, default=False, index=True)
    worker_track_id:  Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    zone_id:          Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)


class Incident(Base):
    __tablename__ = "incidents"
    id:               Mapped[int]       = mapped_column(Integer, primary_key=True, autoincrement=True)
    opened_at:        Mapped[datetime]  = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    closed_at:        Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_track_id:  Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    violation_type:   Mapped[str]       = mapped_column(String(64), index=True)
    severity:         Mapped[str]       = mapped_column(String(16), default="low")  # low|medium|high
    zone_id:          Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    status:           Mapped[str]       = mapped_column(String(16), default="open", index=True)
    actions:          Mapped[list["AgentAction"]] = relationship(back_populates="incident", cascade="all, delete-orphan")


class AgentAction(Base):
    __tablename__ = "agent_actions"
    id:           Mapped[int]       = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp:    Mapped[datetime]  = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    incident_id:  Mapped[Optional[int]] = mapped_column(ForeignKey("incidents.id"), nullable=True, index=True)
    action_name:  Mapped[str]       = mapped_column(String(64), index=True)
    tool_used:    Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reasoning:    Mapped[str]       = mapped_column(Text, default="")
    payload_json: Mapped[str]       = mapped_column(Text, default="{}")
    result:       Mapped[str]       = mapped_column(Text, default="")
    success:      Mapped[bool]      = mapped_column(Boolean, default=True)
    incident:     Mapped[Optional[Incident]] = relationship(back_populates="actions")


class Worker(Base):
    __tablename__ = "workers"
    id:             Mapped[int]       = mapped_column(Integer, primary_key=True, autoincrement=True)
    track_id:       Mapped[str]       = mapped_column(String(64), unique=True, index=True)
    display_name:   Mapped[str]       = mapped_column(String(128))
    registered_at:  Mapped[datetime]  = mapped_column(DateTime(timezone=True), default=utcnow)


class Zone(Base):
    __tablename__ = "zones"
    id:                   Mapped[str]    = mapped_column(String(64), primary_key=True)
    name:                 Mapped[str]    = mapped_column(String(128))
    polygon_json:         Mapped[str]    = mapped_column(Text, default="null")
    required_ppe_json:    Mapped[str]    = mapped_column(Text, default="[]")
    severity_multiplier:  Mapped[float]  = mapped_column(Float, default=1.0)


# ---------- helpers ----------

def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(_ENGINE)


def _session() -> Session:
    return SessionLocal()


def log_detection(
    source: str,
    detections: list[dict],
    camera_id: str = "cam_0",
    worker_track_ids: Optional[dict[int, str]] = None,
    zone_id: Optional[str] = None,
) -> int:
    """
    Persist a list of detection dicts (from run_inference_basic/advanced).
    `detections` items shape: {class, confidence, box: [x1,y1,x2,y2], is_violation,
                               zone_id (optional)}
    Per-detection `zone_id` (if present in the dict) wins over the batch-level
    `zone_id` argument — that lets the live-camera path tag every box with the
    zone its center falls in, while image/video paths can pass a single batch
    zone or leave it None.
    `worker_track_ids` maps detection index -> track_id (optional, for Phase 4).
    Returns count of rows written.
    """
    if not detections: return 0
    written = 0
    with _session() as s:
        for i, d in enumerate(detections):
            box = d.get("box") or [0, 0, 0, 0]
            row = Detection(
                source          = source,
                camera_id       = camera_id,
                class_name      = d.get("class", "unknown"),
                confidence      = float(d.get("confidence", 0.0)),
                box_x1          = int(box[0]), box_y1 = int(box[1]),
                box_x2          = int(box[2]), box_y2 = int(box[3]),
                is_violation    = bool(d.get("is_violation", False)),
                worker_track_id = (worker_track_ids or {}).get(i),
                zone_id         = d.get("zone_id") or zone_id,
            )
            s.add(row)
            written += 1
        s.commit()
    return written


def open_incident(
    violation_type: str,
    worker_track_id: Optional[str] = None,
    zone_id: Optional[str] = None,
    severity: str = "low",
) -> int:
    with _session() as s:
        inc = Incident(
            violation_type  = violation_type,
            worker_track_id = worker_track_id,
            zone_id         = zone_id,
            severity        = severity,
            status          = "open",
        )
        s.add(inc)
        s.commit()
        return inc.id


def close_incident(incident_id: int) -> bool:
    with _session() as s:
        inc = s.get(Incident, incident_id)
        if not inc: return False
        inc.closed_at = utcnow()
        inc.status    = "closed"
        s.commit()
        return True


def reopen_recent_incident(
    violation_type: str,
    zone_id: Optional[str],
    within_seconds: int = 10,
) -> Optional[int]:
    """
    If a CLOSED incident with the same (violation_type, zone_id) was closed
    within the last `within_seconds`, reopen it (status='open', closed_at=None)
    and return its id. Otherwise return None.

    Used by the escalation engine so a worker who keeps cycling in and out of
    the camera frame doesn't keep racking up brand-new incident rows. Same
    underlying event => same incident id.
    """
    cutoff = utcnow() - timedelta(seconds=within_seconds)
    with _session() as s:
        stmt = (
            select(Incident)
            .where(
                Incident.violation_type == violation_type,
                Incident.zone_id        == zone_id,
                Incident.status         == "closed",
                Incident.closed_at      >= cutoff,
            )
            .order_by(Incident.closed_at.desc())
            .limit(1)
        )
        inc = s.scalars(stmt).first()
        if inc is None:
            return None
        inc.status    = "open"
        inc.closed_at = None
        s.commit()
        return inc.id


def log_action(
    action_name: str,
    incident_id: Optional[int] = None,
    tool_used: Optional[str] = None,
    reasoning: str = "",
    payload: Optional[dict] = None,
    result: str = "",
    success: bool = True,
) -> int:
    with _session() as s:
        row = AgentAction(
            action_name  = action_name,
            incident_id  = incident_id,
            tool_used    = tool_used,
            reasoning    = reasoning,
            payload_json = json.dumps(payload or {}, default=str),
            result       = result,
            success      = success,
        )
        s.add(row)
        s.commit()
        return row.id


def recent_violations(window_minutes: int = 60) -> list[dict]:
    cutoff = utcnow() - timedelta(minutes=window_minutes)
    with _session() as s:
        stmt = (
            select(Detection)
            .where(Detection.is_violation == True, Detection.timestamp >= cutoff)
            .order_by(Detection.timestamp.desc())
        )
        rows = s.scalars(stmt).all()
        return [
            {
                "id": r.id, "timestamp": r.timestamp.isoformat(),
                "source": r.source, "camera_id": r.camera_id,
                "class": r.class_name, "confidence": r.confidence,
                "box": [r.box_x1, r.box_y1, r.box_x2, r.box_y2],
                "worker_track_id": r.worker_track_id, "zone_id": r.zone_id,
            } for r in rows
        ]


def incidents_by_status(status: str = "open") -> list[dict]:
    with _session() as s:
        stmt = select(Incident).where(Incident.status == status).order_by(Incident.opened_at.desc())
        rows = s.scalars(stmt).all()
        return [
            {
                "id": r.id, "opened_at": r.opened_at.isoformat(),
                "closed_at": r.closed_at.isoformat() if r.closed_at else None,
                "worker_track_id": r.worker_track_id,
                "violation_type": r.violation_type, "severity": r.severity,
                "zone_id": r.zone_id, "status": r.status,
            } for r in rows
        ]


def counts_by_class(window_minutes: int = 1440) -> dict[str, int]:
    cutoff = utcnow() - timedelta(minutes=window_minutes)
    with _session() as s:
        stmt = (
            select(Detection.class_name, func.count(Detection.id))
            .where(Detection.timestamp >= cutoff, Detection.is_violation == True)
            .group_by(Detection.class_name)
        )
        return {name: int(n) for name, n in s.execute(stmt).all()}
