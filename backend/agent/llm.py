# backend/agent/llm.py
"""
Thin LLM wrapper with function-calling support.

Single entry point: `chat(messages, tools=None)` returns:
    {
        "content":   str | None,       # final assistant text, or None if it wants a tool call
        "tool_calls": [{"id", "name", "args"}, ...],
        "finish_reason": str,
    }

Default provider is Groq (OpenAI-compatible API shape). Gemini is also
supported via its OpenAI-compat endpoint. Swap via LLM_PROVIDER env var,
policy.yaml, or the runtime override set by POST /agent/provider.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, Optional

from dotenv import load_dotenv

from .policy import load_policy

# Per-attempt threshold: a retry-after up to this long is worth waiting for.
# Free-tier TPM hints are almost always under 500ms; anything bigger means
# the user has actually run out of quota and we should surface the error so
# they can switch model/provider.
_AUTO_RETRY_THRESHOLD_S = 1.5

# Total wall-clock budget across all retries on a single LLM call. Capped low
# so a single answer never feels sluggish — at worst, ~2s of extra wait
# before we give up and show the friendly rate-limit message.
_AUTO_RETRY_BUDGET_S = 2.0

# 1 initial attempt + up to 2 retries.
_MAX_ATTEMPTS = 3


def _parse_retry_seconds(retry_str: str) -> Optional[float]:
    """Parse '230ms' / '1.5s' / '1m30s' into seconds. None if unparseable."""
    s = retry_str.strip().lower()
    m = re.match(r"^(\d+)m(\d+(?:\.\d+)?)s?$", s)               # 1m30s
    if m: return int(m.group(1)) * 60 + float(m.group(2))
    m = re.match(r"^(\d+(?:\.\d+)?)ms$", s)                     # 230ms
    if m: return float(m.group(1)) / 1000.0
    m = re.match(r"^(\d+(?:\.\d+)?)s?$", s)                     # 1.5s
    if m: return float(m.group(1))
    return None


def _retry_seconds_from_error(exc: Exception) -> Optional[float]:
    """Pull the retry-after duration out of a rate-limit exception, in seconds."""
    msg = str(exc)
    m = re.search(r"try again in ([\dms.]+(?:m[\dms.]+)?)", msg)
    if not m: return None
    return _parse_retry_seconds(m.group(1))


async def _call_with_retry(client, kwargs: dict, provider_name: str):
    """
    Call client.chat.completions.create(**kwargs), transparently retrying on
    short rate-limits. Returns (response, friendly_error). Exactly one is None.
    """
    spent = 0.0
    last_exc: Optional[Exception] = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = await client.chat.completions.create(**kwargs)
            return resp, None
        except Exception as e:
            last_exc = e
            friendly = _friendly_provider_error(e)
            if friendly is None:
                raise
            if friendly["finish_reason"] != "rate_limit" or attempt == _MAX_ATTEMPTS:
                print(f"[agent] {provider_name} error -> {friendly['finish_reason']}: {str(e)[:300]}")
                return None, friendly
            # Rate-limit and we still have attempts left. See if it's short.
            retry_s = _retry_seconds_from_error(e)
            if retry_s is None or retry_s > _AUTO_RETRY_THRESHOLD_S:
                print(f"[agent] {provider_name} error -> rate_limit (retry too long): {str(e)[:200]}")
                return None, friendly
            if spent + retry_s + 0.1 > _AUTO_RETRY_BUDGET_S:
                print(f"[agent] {provider_name} rate-limit budget exhausted ({spent:.2f}s spent)")
                return None, friendly
            sleep_s = retry_s + 0.1   # small safety margin past the provider's hint
            print(f"[agent] {provider_name} rate-limited, retry {attempt}/{_MAX_ATTEMPTS-1} in {sleep_s:.2f}s")
            await asyncio.sleep(sleep_s)
            spent += sleep_s
    # Should be unreachable, but stay defensive.
    return None, _friendly_provider_error(last_exc) or {"content": "Unknown error", "tool_calls": [], "finish_reason": "unknown"}

load_dotenv()  # picks up .env in CWD when uvicorn starts


# Catalog of provider → list of usable model ids. The frontend renders these
# in the dropdowns. Edit this dict if you want to expose more or fewer models.
PROVIDER_MODELS: dict[str, list[str]] = {
    "groq": [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
    ],
    "gemini": [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
    ],
    # OpenAI removed — not in use.
}


# Runtime override (set via POST /agent/provider). When set, takes priority
# over LLM_PROVIDER env var and policy.yaml — lets the user flip provider/model
# from the chat UI without restarting uvicorn.
_RUNTIME_OVERRIDE: dict = {"provider": None, "model": None}


def set_runtime_override(provider: Optional[str], model: Optional[str]) -> None:
    _RUNTIME_OVERRIDE["provider"] = (provider or None)
    _RUNTIME_OVERRIDE["model"]    = (model or None)


def get_runtime_override() -> dict:
    return dict(_RUNTIME_OVERRIDE)


def current_provider_and_model() -> dict:
    """Public read of what chat() would actually use right now."""
    provider, model = _provider_and_model()
    return {"provider": provider, "model": model}


def _provider_and_model() -> tuple[str, str]:
    """Resolve provider+model with priority: runtime override > env > policy."""
    if _RUNTIME_OVERRIDE["provider"]:
        return (
            _RUNTIME_OVERRIDE["provider"].lower(),
            _RUNTIME_OVERRIDE["model"] or load_policy().llm.model,
        )
    pol = load_policy()
    provider = (os.getenv("LLM_PROVIDER") or pol.llm.provider).lower()
    model    = pol.llm.model
    return provider, model


# Pretty-print provider exceptions into a chat-bubble-friendly message.
# Returns a `chat()`-shaped dict the agent loop will treat as a final answer,
# or None if the exception isn't one we recognize (caller should re-raise).

def _friendly_provider_error(exc: Exception) -> Optional[dict]:
    msg = str(exc)
    msg_lower = msg.lower()

    # Rate limits / quota exhaustion (Groq, Gemini, OpenAI all hit this path)
    if any(s in msg for s in ("RateLimitError", "rate_limit_exceeded", "RESOURCE_EXHAUSTED")) \
       or " 429" in msg or "code: 429" in msg:
        retry = ""
        m = re.search(r"try again in ([\dms.]+(?:m[\dms.]+)?)", msg)
        if m: retry = f" Please retry in about {m.group(1).strip()}."
        # Tease out the actual numeric quota if the provider exposed it
        kind = "request"
        if "tokens per day"     in msg_lower: kind = "daily-token"
        elif "tokens per minute" in msg_lower: kind = "per-minute-token"
        elif "generate_content_free_tier_requests" in msg_lower: kind = "request"
        return {
            "content": (
                f"The LLM provider is rate-limited right now ({kind} quota exceeded)."
                f"{retry} This is a free-tier limit, not a bug in the system. "
                f"Wait a moment and try again, or switch to another provider/model "
                f"using the dropdown above the chat."
            ),
            "tool_calls":    [],
            "finish_reason": "rate_limit",
        }

    # Malformed tool calls — Groq tends to return these as 400 / tool_use_failed
    if any(s in msg for s in ("tool_use_failed", "BadRequestError")) or " 400" in msg:
        return {
            "content": (
                "I had trouble forming a valid tool call. Try rephrasing the "
                "question — for example, ask one thing at a time, or give me "
                "an explicit incident id if you know one."
            ),
            "tool_calls":    [],
            "finish_reason": "tool_use_failed",
        }

    # Model not available on this account/region
    if any(s in msg for s in ("NotFoundError", "is not found", "NOT_FOUND")):
        return {
            "content": (
                "This model isn't available on the current provider account. "
                "Pick another model from the dropdown above."
            ),
            "tool_calls":    [],
            "finish_reason": "model_not_found",
        }

    # Provider outage / temporary unavailable
    if any(s in msg for s in ("InternalServerError", "UNAVAILABLE")) or " 503" in msg:
        return {
            "content": (
                "The LLM provider is temporarily unavailable (high demand or "
                "transient outage). Try again in a few seconds, or switch to "
                "another provider/model using the dropdown above."
            ),
            "tool_calls":    [],
            "finish_reason": "provider_unavailable",
        }

    return None


async def chat(messages: list[dict], tools: Optional[list[dict]] = None) -> dict:
    provider, model = _provider_and_model()
    if provider == "groq":
        return await _chat_groq(messages, tools, model)
    if provider == "gemini":
        # Gemini's default model name differs from the policy default — auto-pick a Gemini
        # model if the configured model still looks like a Groq one.
        if "llama" in (model or "").lower(): model = "gemini-2.5-flash"
        return await _chat_openai_compat(
            messages, tools, model,
            api_key=os.getenv("GEMINI_API_KEY"),
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            provider_name="gemini",
            key_env="GEMINI_API_KEY",
            console_url="https://aistudio.google.com/apikey",
        )
    raise ValueError(f"Unknown LLM provider: {provider!r} (supported: groq, gemini)")


async def _chat_openai_compat(
    messages: list[dict], tools: Optional[list[dict]], model: str,
    *, api_key: Optional[str], base_url: Optional[str],
    provider_name: str, key_env: str, console_url: str,
) -> dict:
    """Shared implementation for OpenAI-style endpoints (Gemini via compat, OpenAI native)."""
    if not api_key:
        raise RuntimeError(
            f"{key_env} is not set. Get a free key at {console_url} and put it in backend/.env."
        )
    try:
        from openai import AsyncOpenAI
    except ImportError as e:
        raise RuntimeError("openai package not installed. Run: pip install openai") from e

    client_kwargs: dict[str, Any] = {"api_key": api_key, "timeout": 30.0, "max_retries": 1}
    if base_url: client_kwargs["base_url"] = base_url
    client = AsyncOpenAI(**client_kwargs)

    kwargs: dict[str, Any] = {
        "model":    model,
        "messages": messages,
        "temperature": 0.2,
    }
    if tools:
        kwargs["tools"]      = tools
        kwargs["tool_choice"] = "auto"

    resp, friendly = await _call_with_retry(client, kwargs, provider_name)
    if friendly is not None: return friendly

    msg  = resp.choices[0].message
    finish_reason = resp.choices[0].finish_reason

    tool_calls: list[dict] = []
    if getattr(msg, "tool_calls", None):
        for tc in msg.tool_calls:
            args = tc.function.arguments
            if isinstance(args, str):
                try: args = json.loads(args or "{}")
                except json.JSONDecodeError: args = {"_raw": args}
            tool_calls.append({"id": tc.id, "name": tc.function.name, "args": args})

    return {
        "content":       (msg.content or None),
        "tool_calls":    tool_calls,
        "finish_reason": finish_reason,
    }


async def _chat_groq(messages: list[dict], tools: Optional[list[dict]], model: str) -> dict:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Get a free key at https://console.groq.com "
            "and put it in backend/.env as GROQ_API_KEY=...."
        )

    # Import lazily so the rest of the app doesn't crash if `groq` isn't installed yet.
    try:
        from groq import AsyncGroq
    except ImportError as e:
        raise RuntimeError(
            "groq package not installed. Run: pip install groq"
        ) from e

    # 30s ceiling per individual LLM call so one slow Groq response doesn't hang the whole agent loop
    client = AsyncGroq(api_key=api_key, timeout=30.0, max_retries=1)

    kwargs: dict[str, Any] = {
        "model":    model,
        "messages": messages,
        "temperature": 0.2,
    }
    if tools:
        kwargs["tools"]      = tools
        kwargs["tool_choice"] = "auto"

    resp, friendly = await _call_with_retry(client, kwargs, "groq")
    if friendly is not None: return friendly

    msg  = resp.choices[0].message
    finish_reason = resp.choices[0].finish_reason

    tool_calls: list[dict] = []
    if getattr(msg, "tool_calls", None):
        for tc in msg.tool_calls:
            args = tc.function.arguments
            if isinstance(args, str):
                try: args = json.loads(args or "{}")
                except json.JSONDecodeError: args = {"_raw": args}
            tool_calls.append({"id": tc.id, "name": tc.function.name, "args": args})

    return {
        "content":       (msg.content or None),
        "tool_calls":    tool_calls,
        "finish_reason": finish_reason,
    }
