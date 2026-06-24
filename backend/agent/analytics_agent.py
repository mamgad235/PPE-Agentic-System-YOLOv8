# backend/agent/analytics_agent.py
"""
Analytics agent loop.

The agent receives a natural-language question, gives the LLM a system prompt
that explains the schema + tools, and runs a tool-calling loop until the LLM
returns a final answer or we hit max_tool_turns.

Public:
    ask(question: str) -> {"answer": str, "tool_calls": list, "trace_id": str}
"""
from __future__ import annotations

import asyncio
import inspect
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from .llm import chat as llm_chat
from .policy import load_policy
from .tools import TOOL_SCHEMAS, TOOL_REGISTRY
from .tz_context import set_user_tz, get_user_tz_name, common_windows, local_now


SYSTEM_PROMPT_TEMPLATE = """\
You are PPE Guard's analytics agent.

TIME REFERENCE (copy verbatim, no tz math):
- Local now ({tz}): {now_local}
- today:     {today_start}..{today_end}
- yesterday: {yest_start}..{yest_end}
- this week: {week_start}..{week_end}
Hours in tool results are already local ({tz}); state them as local time
(e.g. "16:00 local"), never as UTC.

TOOL PICKER — pick ONE, that's almost always enough:
- "how many X violations today / this week / yesterday"
- "which zone is worst", "when do violations peak", "what's the breakdown"
- "how many hardhat / mask / vest violations"
  → summarize_period (use violation_type / zone filters for narrow questions)

- "who is the top offender", "worst worker", "who violates the most"
  → top_offenders

- "list incidents", "show open incidents", "any incidents today"
  → list_incidents

- user explicitly names an incident id ("incident 7", "incident #12")
  → get_incident

- user explicitly asks for an email / report draft
  → draft_incident_email   (after list_incidents if no id given)

- user explicitly asks for raw frames / individual detection records
  → query_violations   (this is the ONLY tool that returns frames; otherwise
                        the answer is in incident episodes, not frames)

STRICT RULES:
1. Call ONE tool, read the result, then write a 1-3 sentence answer and STOP.
   Only chain a second tool if the first result genuinely does not contain
   the answer. Most questions are answered in one tool call.
2. NEVER call get_incident or draft_incident_email unless the user explicitly
   mentions a specific incident id or asks for an email. They are not
   exploration tools — calling them on a guessed id will return errors.
3. Always describe results from summarize_period / top_offenders as
   "incidents" or "violation episodes". Never say "frames" or "detections".
4. Pass tool arguments as a JSON object with the right types — integers as
   100 not "100", strings in double quotes. Never nest tool calls.
5. For conceptual questions ("explain the escalation policy") answer from the
   Site policy block below without calling any tools — do NOT mix in data
   from previous queries or invent timestamps.

Site policy:
- Zones configured: {zones}
- Audible warning after {audible_secs}s of continuous violation
- Supervisor notified after {escalate_repeats} repeats within {repeat_window_min} min

Schema (read-only):
- Incident(id, opened_at, closed_at, worker_track_id, violation_type,
           severity, zone_id, status[open|acknowledged|escalated|closed])
- Detection(id, timestamp, class_name, is_violation, worker_track_id, zone_id)
- AgentAction(id, timestamp, incident_id, action_name, reasoning, result, success)
"""


def _build_system_prompt() -> str:
    pol  = load_policy()
    win  = common_windows()
    return SYSTEM_PROMPT_TEMPLATE.format(
        tz                 = get_user_tz_name(),
        now_local          = win["now_local"],
        now_utc            = win["now_utc"],
        today_start        = win["today"]["start_iso"],
        today_end          = win["today"]["end_iso"],
        yest_start         = win["yesterday"]["start_iso"],
        yest_end           = win["yesterday"]["end_iso"],
        week_start         = win["this_week"]["start_iso"],
        week_end           = win["this_week"]["end_iso"],
        l24_start          = win["last_24h"]["start_iso"],
        l24_end            = win["last_24h"]["end_iso"],
        zones              = ", ".join(z.id for z in pol.zones) or "(none configured)",
        escalate_repeats   = pol.escalation.escalate_supervisor_after_repeats,
        repeat_window_min  = pol.escalation.repeat_window_minutes,
        audible_secs       = pol.escalation.audible_warning_after_seconds,
    )


async def _dispatch(name: str, args: dict) -> Any:
    fn = TOOL_REGISTRY.get(name)
    if fn is None: return {"error": f"unknown tool {name!r}"}
    if inspect.iscoroutinefunction(fn):
        return await fn(**args)
    # Run sync tool in a thread so we don't block the event loop on SQLite.
    return await asyncio.to_thread(fn, **args)


def _trim(value: Any, limit: int = 8000) -> str:
    """Tool results go back to the LLM as strings; cap size so we don't blow context."""
    s = json.dumps(value, default=str, ensure_ascii=False)
    return s if len(s) <= limit else s[: limit - 3] + "..."


async def ask(question: str, tz: str | None = None) -> dict:
    # Stash the user's tz on this asyncio task's context so tools (running via
    # asyncio.to_thread) can read it and format hours in local time.
    set_user_tz(tz)
    # Visible breadcrumb in the uvicorn console so it's easy to tell whether
    # the frontend successfully forwarded the browser timezone.
    print(f"[agent] /agent/ask tz={tz!r} -> effective={get_user_tz_name()!r}")

    trace_id = uuid.uuid4().hex[:12]
    pol      = load_policy()
    max_turns = max(1, pol.llm.max_tool_turns)

    messages: list[dict] = [
        {"role": "system", "content": _build_system_prompt()},
        {"role": "user",   "content": question.strip()},
    ]
    tool_trace: list[dict] = []

    for turn in range(max_turns):
        resp = await llm_chat(messages, tools=TOOL_SCHEMAS)
        tcs  = resp.get("tool_calls") or []

        if not tcs:
            return {
                "answer":     (resp.get("content") or "").strip() or "(no answer)",
                "tool_calls": tool_trace,
                "trace_id":   trace_id,
                "turns":      turn + 1,
            }

        # Record the assistant's tool_call message exactly as the LLM expects it back.
        messages.append({
            "role": "assistant",
            "content": resp.get("content") or "",
            "tool_calls": [
                {"id": tc["id"], "type": "function",
                 "function": {"name": tc["name"], "arguments": json.dumps(tc["args"])}}
                for tc in tcs
            ],
        })

        # Run each tool and feed results back as `tool` messages.
        for tc in tcs:
            try:
                result = await _dispatch(tc["name"], tc["args"] or {})
                ok     = True
            except Exception as e:
                result = {"error": f"{type(e).__name__}: {e}"}
                ok     = False
            tool_trace.append({"name": tc["name"], "args": tc["args"], "result": result, "ok": ok})
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "name": tc["name"],
                "content": _trim(result),
            })

    # Ran out of turns. Ask for a final synthesis with tools disabled.
    final = await llm_chat(messages + [
        {"role": "user", "content": "Summarize the above tool results in 1-3 sentences. Do not call any more tools."}
    ])
    return {
        "answer":     (final.get("content") or "").strip() or "(turn limit reached)",
        "tool_calls": tool_trace,
        "trace_id":   trace_id,
        "turns":      max_turns,
        "note":       "max_tool_turns reached",
    }
