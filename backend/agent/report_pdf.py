# backend/agent/report_pdf.py
"""
Phase 5 — one-page PDF incident report.

Pure-server PDF generation via fpdf2 (no LaTeX, no headless browser). The
function returns raw bytes + a suggested filename; the FastAPI endpoint
wraps it in a StreamingResponse.

Times are rendered in the *site* timezone (policy.yaml -> site_timezone),
matching the convention webhook.py uses for server-initiated outputs. The
supervisor on-site cares about wall-clock time at the site, not UTC.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from .policy import load_policy
from .storage import SessionLocal, Incident, AgentAction

try:
    from zoneinfo import ZoneInfo
    _HAS_ZONEINFO = True
except ImportError:                  # pragma: no cover
    _HAS_ZONEINFO = False


SITE_NAME = "PPE Guard Demo Site"


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------

def build_incident_report(incident_id: int) -> tuple[bytes, str]:
    """
    Build a one-page incident report.

    Returns (pdf_bytes, filename).

    Raises:
        LookupError  if the incident_id doesn't exist.
        RuntimeError if fpdf2 isn't installed.
    """
    try:
        from fpdf import FPDF
    except ImportError as e:
        raise RuntimeError(
            "fpdf2 is not installed. Run `pip install fpdf2==2.7.9` in the "
            "backend venv and restart uvicorn."
        ) from e

    inc, actions = _load_incident(incident_id)
    if inc is None:
        raise LookupError(f"incident #{incident_id} not found")

    tz, tz_label = _site_tz()
    pdf = _PpePdf()
    pdf.add_page()
    _render_header(pdf)
    _render_summary(pdf, inc, tz, tz_label)
    _render_escalation_status(pdf, actions)
    _render_action_log(pdf, actions, tz, tz_label)
    _render_footer(pdf, tz, tz_label)

    # fpdf2 returns a bytearray when dest='S'; FastAPI wants bytes.
    raw = pdf.output(dest="S")
    if isinstance(raw, (bytes, bytearray)):
        pdf_bytes = bytes(raw)
    else:                            # very old fpdf returned str
        pdf_bytes = raw.encode("latin-1", errors="ignore")

    filename = f"ppe_incident_{incident_id:05d}.pdf"
    return pdf_bytes, filename


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------

def _load_incident(incident_id: int) -> tuple[Optional[Incident], list[AgentAction]]:
    """Fetch the incident row + its linked actions, oldest first."""
    with SessionLocal() as s:
        inc = s.get(Incident, incident_id)
        if inc is None:
            return None, []
        actions = list(s.scalars(
            select(AgentAction)
            .where(AgentAction.incident_id == incident_id)
            .order_by(AgentAction.timestamp.asc())
        ).all())
        # Detach so we can use them after the session closes.
        # SQLAlchemy 2.x: simple attribute reads after expire are fine here
        # because the session was created with expire_on_commit=False.
        return inc, actions


def _site_tz():
    name = (load_policy().site_timezone or "UTC").strip() or "UTC"
    if name == "UTC" or not _HAS_ZONEINFO:
        return timezone.utc, "UTC"
    try:
        return ZoneInfo(name), name
    except Exception:
        return timezone.utc, "UTC"


def _format_ts(dt: Optional[datetime], tz, tz_label: str) -> str:
    """UTC datetime -> 'YYYY-MM-DD HH:MM TZ' in site time. '—' if missing."""
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(tz)
    suffix = "UTC" if tz_label == "UTC" else tz_label
    return local.strftime("%Y-%m-%d %H:%M ") + suffix


def _duration_str(opened: datetime, closed: Optional[datetime]) -> str:
    """Human duration. If still open, falls back to 'ongoing'."""
    if closed is None:
        return "ongoing"
    if opened.tzinfo is None:
        opened = opened.replace(tzinfo=timezone.utc)
    if closed.tzinfo is None:
        closed = closed.replace(tzinfo=timezone.utc)
    seconds = max(0, int((closed - opened).total_seconds()))
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, mins = divmod(minutes, 60)
    return f"{hours}h {mins}m"


# fpdf2's default helvetica is Latin-1 only. We strip non-Latin-1 chars
# (em-dashes, smart quotes, etc.) before writing so the call doesn't raise.
def _safe(text: str) -> str:
    return text.encode("latin-1", errors="replace").decode("latin-1")


# ----------------------------------------------------------------------
# Layout
# ----------------------------------------------------------------------

class _PpePdf:
    """Thin wrapper over fpdf2 so render helpers stay readable."""
    def __init__(self):
        from fpdf import FPDF
        self.pdf = FPDF(orientation="P", unit="mm", format="A4")
        self.pdf.set_auto_page_break(auto=True, margin=15)
        self.pdf.set_margins(15, 15, 15)

    def add_page(self):
        self.pdf.add_page()

    def line(self, x1, y1, x2, y2):
        self.pdf.line(x1, y1, x2, y2)

    def set_font(self, family="helvetica", style="", size=10):
        self.pdf.set_font(family, style, size)

    def set_text_color(self, r, g, b):
        self.pdf.set_text_color(r, g, b)

    def set_fill_color(self, r, g, b):
        self.pdf.set_fill_color(r, g, b)

    def cell(self, w, h, text="", border=0, ln=0, align="L", fill=False):
        self.pdf.cell(w, h, _safe(text), border=border, ln=ln, align=align, fill=fill)

    def multi_cell(self, w, h, text=""):
        self.pdf.multi_cell(w, h, _safe(text))

    def ln(self, h=4):
        self.pdf.ln(h)

    def get_x(self): return self.pdf.get_x()
    def get_y(self): return self.pdf.get_y()
    def set_xy(self, x, y): self.pdf.set_xy(x, y)
    def output(self, dest="S"): return self.pdf.output(dest=dest)


def _render_header(pdf: _PpePdf) -> None:
    # Logo-mark stand-in: red shield-shaped rectangle on the left.
    pdf.set_fill_color(220, 38, 38)
    pdf.pdf.rect(15, 15, 8, 10, style="F")
    pdf.set_xy(26, 14)

    pdf.set_text_color(15, 23, 42)
    pdf.set_font("helvetica", "B", 16)
    pdf.cell(0, 7, "PPE Guard - Incident Report", ln=1)

    pdf.set_xy(26, 22)
    pdf.set_font("helvetica", "", 10)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(0, 5, SITE_NAME, ln=1)

    # Horizontal rule
    pdf.set_text_color(15, 23, 42)
    pdf.ln(4)
    y = pdf.get_y()
    pdf.line(15, y, 195, y)
    pdf.ln(4)


def _kv_row(pdf: _PpePdf, label: str, value: str) -> None:
    """Left-aligned key / value pair, label muted."""
    pdf.set_font("helvetica", "", 9)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(45, 6, label)
    pdf.set_font("helvetica", "B", 10)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 6, value, ln=1)


def _section_title(pdf: _PpePdf, text: str) -> None:
    pdf.ln(2)
    pdf.set_font("helvetica", "B", 11)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 6, text, ln=1)
    pdf.set_font("helvetica", "", 9)
    pdf.ln(1)


def _render_summary(pdf: _PpePdf, inc: Incident, tz, tz_label: str) -> None:
    _section_title(pdf, "Incident Summary")

    severity_color = {
        "high":   (220, 38, 38),
        "medium": (217, 119, 6),
        "low":    (5, 150, 105),
    }.get((inc.severity or "low").lower(), (100, 116, 139))

    status_color = (220, 38, 38) if inc.status == "open" else (5, 150, 105)

    _kv_row(pdf, "Incident ID",     f"#{inc.id}")
    _kv_row(pdf, "Violation",       inc.violation_type or "—")
    _kv_row(pdf, "Zone",            inc.zone_id or "default")

    # Severity with colored badge
    pdf.set_font("helvetica", "", 9)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(45, 6, "Severity")
    pdf.set_font("helvetica", "B", 9)
    pdf.set_text_color(*severity_color)
    pdf.cell(0, 6, (inc.severity or "low").upper(), ln=1)

    # Status with colored badge
    pdf.set_font("helvetica", "", 9)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(45, 6, "Status")
    pdf.set_font("helvetica", "B", 9)
    pdf.set_text_color(*status_color)
    pdf.cell(0, 6, (inc.status or "open").upper(), ln=1)

    pdf.set_text_color(15, 23, 42)
    _kv_row(pdf, "Opened at",       _format_ts(inc.opened_at, tz, tz_label))
    _kv_row(pdf, "Closed at",       _format_ts(inc.closed_at, tz, tz_label))
    _kv_row(pdf, "Duration",        _duration_str(inc.opened_at, inc.closed_at))


def _render_escalation_status(pdf: _PpePdf, actions: list[AgentAction]) -> None:
    _section_title(pdf, "Escalation Status")

    fired = {a.action_name for a in actions}
    items = [
        ("Dashboard notification", "dashboard_notify"  in fired),
        ("Audible warning",        "audible_warning"   in fired),
        ("Supervisor alert",       "supervisor_alert"  in fired),
        ("Auto-closed",            "auto_close"        in fired),
    ]
    for label, did in items:
        marker = "[YES]" if did else "[ -- ]"
        color  = (5, 150, 105) if did else (148, 163, 184)
        pdf.set_font("helvetica", "B", 9)
        pdf.set_text_color(*color)
        pdf.cell(15, 6, marker)
        pdf.set_font("helvetica", "", 9)
        pdf.set_text_color(15, 23, 42)
        pdf.cell(0, 6, label, ln=1)


def _render_action_log(pdf: _PpePdf, actions: list[AgentAction], tz, tz_label: str) -> None:
    _section_title(pdf, "Action Log")

    if not actions:
        pdf.set_text_color(148, 163, 184)
        pdf.set_font("helvetica", "I", 9)
        pdf.cell(0, 6, "No agent actions recorded for this incident.", ln=1)
        return

    # Header row
    pdf.set_fill_color(241, 245, 249)
    pdf.set_text_color(71, 85, 105)
    pdf.set_font("helvetica", "B", 8)
    pdf.cell(35, 6, "When",      border=0, fill=True)
    pdf.cell(40, 6, "Action",    border=0, fill=True)
    pdf.cell(0,  6, "Reasoning", border=0, ln=1, fill=True)

    pdf.set_font("helvetica", "", 8)
    pdf.set_text_color(15, 23, 42)
    for i, a in enumerate(actions):
        # Zebra stripes
        if i % 2 == 1:
            pdf.set_fill_color(250, 251, 252)
            fill = True
        else:
            fill = False
        when = _format_ts(a.timestamp, tz, tz_label).replace(f" {tz_label}", "")
        # Action and reasoning are clipped to the column width — fpdf2 cell()
        # doesn't word-wrap. Long reasoning still appears in the JSON-export
        # endpoint; this is a summary view.
        reasoning = (a.reasoning or "").strip()
        if len(reasoning) > 90:
            reasoning = reasoning[:87] + "..."
        pdf.cell(35, 5, when,           border=0, fill=fill)
        pdf.cell(40, 5, a.action_name,  border=0, fill=fill)
        pdf.cell(0,  5, reasoning,      border=0, ln=1, fill=fill)


def _render_footer(pdf: _PpePdf, tz, tz_label: str) -> None:
    pdf.ln(8)
    y = pdf.get_y()
    pdf.line(15, y, 195, y)
    pdf.ln(2)
    pdf.set_font("helvetica", "I", 8)
    pdf.set_text_color(148, 163, 184)
    gen_at = _format_ts(datetime.now(timezone.utc), tz, tz_label)
    pdf.cell(0, 5, f"Automated report. Generated by PPE Guard on {gen_at}.", ln=1, align="C")
