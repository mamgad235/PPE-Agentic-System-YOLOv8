# backend/agent/audit.py
"""
Append-only audit trail. Every agent action passes through @audited so the
reasoning, payload, and outcome land in the agent_actions table.
"""
from __future__ import annotations

import functools
import inspect
from typing import Any, Callable, Optional

from .storage import log_action


def audited(action_name: str, tool_used: Optional[str] = None) -> Callable:
    """
    Decorator that records every call to a tool function as an AgentAction row.

    The wrapped function may accept (or not) two reserved kwargs, which are
    popped before the underlying function is called so they never collide
    with the tool's real parameter names:
      - _audit_reasoning: str             (caller-supplied justification)
      - _audit_incident_id: Optional[int] (associate this action with an open incident)
    (Legacy alias `reasoning` is still honored if `_audit_reasoning` is absent.)
    """
    def deco(fn: Callable) -> Callable:
        is_coro = inspect.iscoroutinefunction(fn)

        def _payload(args, kwargs):
            try:
                sig = inspect.signature(fn)
                bound = sig.bind_partial(*args, **kwargs)
                return {k: _safe_repr(v) for k, v in bound.arguments.items()}
            except Exception:
                return {"args": _safe_repr(args), "kwargs": _safe_repr(kwargs)}

        if is_coro:
            @functools.wraps(fn)
            async def awrap(*args, **kwargs):
                reasoning   = kwargs.pop("reasoning", "")
                incident_id = kwargs.pop("incident_id", None)
                payload     = _payload(args, kwargs)
                try:
                    res = await fn(*args, **kwargs)
                    log_action(
                        action_name = action_name, incident_id = incident_id,
                        tool_used   = tool_used or fn.__name__,
                        reasoning   = reasoning, payload = payload,
                        result      = _safe_repr(res), success = True,
                    )
                    return res
                except Exception as e:
                    log_action(
                        action_name = action_name, incident_id = incident_id,
                        tool_used   = tool_used or fn.__name__,
                        reasoning   = reasoning, payload = payload,
                        result      = f"ERROR: {type(e).__name__}: {e}", success = False,
                    )
                    raise
            return awrap

        @functools.wraps(fn)
        def wrap(*args, **kwargs):
            reasoning   = kwargs.pop("_audit_reasoning", kwargs.pop("reasoning", ""))
            incident_id = kwargs.pop("_audit_incident_id", None)
            payload     = _payload(args, kwargs)
            try:
                res = fn(*args, **kwargs)
                log_action(
                    action_name = action_name, incident_id = incident_id,
                    tool_used   = tool_used or fn.__name__,
                    reasoning   = reasoning, payload = payload,
                    result      = _safe_repr(res), success = True,
                )
                return res
            except Exception as e:
                log_action(
                    action_name = action_name, incident_id = incident_id,
                    tool_used   = tool_used or fn.__name__,
                    reasoning   = reasoning, payload = payload,
                    result      = f"ERROR: {type(e).__name__}: {e}", success = False,
                )
                raise
        return wrap
    return deco


def _safe_repr(obj: Any, limit: int = 2000) -> str:
    try:
        s = repr(obj)
    except Exception:
        s = f"<unrepresentable {type(obj).__name__}>"
    return s if len(s) <= limit else s[: limit - 3] + "..."
