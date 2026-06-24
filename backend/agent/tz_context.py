# backend/agent/tz_context.py
"""
Per-request user timezone, exposed as a contextvar so analytics tools can
render hours / dates in the user's local time without having to thread a tz
parameter through every function signature.

The frontend sends `tz` (an IANA timezone string like "Africa/Cairo") on
every `/agent/ask` request. The endpoint calls `set_user_tz(tz)` once before
running the agent loop; tools call `get_user_tz()` when they need to format.

Falls back to UTC if no tz was set or the value is unparseable.
"""
from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timezone, timedelta
from typing import Optional

try:
    from zoneinfo import ZoneInfo
    _HAS_ZONEINFO = True
except ImportError:                # pragma: no cover (Python 3.8)
    _HAS_ZONEINFO = False


_USER_TZ: ContextVar[Optional[str]] = ContextVar("ppe_user_tz", default=None)


def set_user_tz(tz_name: Optional[str]) -> None:
    """Store the request's tz on the current asyncio task context."""
    _USER_TZ.set((tz_name or "").strip() or None)


def get_user_tz_name() -> str:
    """Raw tz string the frontend sent (or 'UTC' fallback)."""
    return _USER_TZ.get() or "UTC"


# Names we've already warned about — keeps the log from getting noisy.
_WARNED_BAD_TZ: set[str] = set()


def get_user_tz():
    """Return a tzinfo object for the current request, falling back to UTC."""
    name = get_user_tz_name()
    if name == "UTC":
        return timezone.utc
    if not _HAS_ZONEINFO:
        if "_no_zoneinfo" not in _WARNED_BAD_TZ:
            _WARNED_BAD_TZ.add("_no_zoneinfo")
            print(
                "[agent] zoneinfo module not available; falling back to UTC. "
                "Upgrade to Python 3.9+."
            )
        return timezone.utc
    try:
        return ZoneInfo(name)
    except Exception as e:
        if name not in _WARNED_BAD_TZ:
            _WARNED_BAD_TZ.add(name)
            # On Windows, IANA tz data isn't shipped with Python; ZoneInfo
            # then raises ZoneInfoNotFoundError and hours stay in UTC. The
            # fix is `pip install tzdata` in the backend venv.
            print(
                f"[agent] ZoneInfo({name!r}) failed: {type(e).__name__}: {e}. "
                f"Falling back to UTC. On Windows, run: pip install tzdata"
            )
        return timezone.utc


def utc_to_local_hour(dt_utc: datetime) -> int:
    """Convert a UTC datetime to the hour-of-day in the user's local tz."""
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    return dt_utc.astimezone(get_user_tz()).hour


def local_now() -> datetime:
    """Now, expressed in the user's local timezone (aware datetime)."""
    return datetime.now(timezone.utc).astimezone(get_user_tz())


def local_window_to_utc(local_start: datetime, local_end: datetime) -> tuple[datetime, datetime]:
    """Treat the inputs as local-tz wall-clock times; return their UTC equivalents."""
    tz = get_user_tz()
    if local_start.tzinfo is None: local_start = local_start.replace(tzinfo=tz)
    if local_end.tzinfo   is None: local_end   = local_end.replace(tzinfo=tz)
    return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc)


def common_windows() -> dict[str, dict]:
    """
    Precompute the windows the agent most often asks about ("today", "yesterday",
    "this week", "last 24h"), expressed as UTC ISO strings but anchored to the
    user's local calendar day. Returned so the system prompt can inline them
    verbatim — the LLM doesn't have to do any tz math itself.
    """
    tz_now_local = local_now()
    midnight_today  = tz_now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight_tom    = midnight_today + timedelta(days=1)
    midnight_yest   = midnight_today - timedelta(days=1)
    # ISO-8601 week starts Monday; weekday() returns 0=Mon
    week_start_local = midnight_today - timedelta(days=tz_now_local.weekday())
    last_24h_start_local = tz_now_local - timedelta(hours=24)

    def _pair(local_start: datetime, local_end: datetime) -> dict:
        u_start, u_end = local_window_to_utc(local_start, local_end)
        return {
            "start_iso": u_start.isoformat(timespec="seconds"),
            "end_iso":   u_end.isoformat(timespec="seconds"),
        }

    return {
        "now_local":   tz_now_local.isoformat(timespec="seconds"),
        "now_utc":     datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "today":       _pair(midnight_today, midnight_tom),
        "yesterday":   _pair(midnight_yest,  midnight_today),
        "this_week":   _pair(week_start_local, midnight_tom),
        "last_24h":    _pair(last_24h_start_local, tz_now_local),
    }
