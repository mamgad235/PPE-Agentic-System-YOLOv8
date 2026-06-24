# backend/agent/bus.py
"""
In-process async event bus. Two channels:
- detections: every detection event from any inference path
- agent_events: broadcasts from the escalation agent to subscribed websockets

Subscribers are asyncio.Queue per subscription. Publishers fan-out.
"""
from __future__ import annotations

import asyncio
from typing import Any


class _Channel:
    def __init__(self) -> None:
        self._subs: list[asyncio.Queue] = []

    def subscribe(self, maxsize: int = 200) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._subs.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try: self._subs.remove(q)
        except ValueError: pass

    def publish(self, event: Any) -> None:
        # Non-blocking: if a subscriber is too slow, drop the oldest item for that sub.
        for q in list(self._subs):
            if q.full():
                try: q.get_nowait()
                except Exception: pass
            try: q.put_nowait(event)
            except Exception: pass


class _Bus:
    def __init__(self) -> None:
        self.detections   = _Channel()
        self.agent_events = _Channel()


bus = _Bus()
