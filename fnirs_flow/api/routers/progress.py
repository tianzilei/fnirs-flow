"""Execution progress event cache and Server-Sent Events endpoint."""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

from fastapi import APIRouter, Request
from starlette.responses import StreamingResponse

router = APIRouter()
_MAX_PROJECTS = 100
_progress_events: dict[str, list[dict]] = {}
_progress_sequences: dict[tuple[str, str], int] = {}


class ProgressBuffer:
    """Bounded, attempt-scoped event buffer owned by an application instance."""

    def __init__(
        self,
        limit: int,
        *,
        events: dict[str, list[dict[str, Any]]] | None = None,
        sequences: dict[tuple[str, str], int] | None = None,
    ) -> None:
        self.limit = max(1, limit)
        self.events = events if events is not None else {}
        self.sequences = sequences if sequences is not None else {}
        self.lock = threading.Lock()

    def push(self, project_id: str, event: dict[str, Any]) -> None:
        with self.lock:
            attempt_id = str(event.get("attempt_id", ""))
            sequence_key = (project_id, attempt_id)
            sequence = self.sequences.get(sequence_key, 0) + 1
            self.sequences[sequence_key] = sequence
            enriched = {"project_id": project_id, "attempt_id": attempt_id, "sequence": sequence, **event}
            self.events.setdefault(project_id, []).append(enriched)
            if len(self.events[project_id]) > self.limit:
                self.events[project_id] = self.events[project_id][-self.limit:]
            if len(self.events) > _MAX_PROJECTS:
                oldest = next(iter(self.events))
                del self.events[oldest]
                for key in [item for item in self.sequences if item[0] == oldest]:
                    del self.sequences[key]


_compatibility_buffer = ProgressBuffer(
    1000,
    events=_progress_events,
    sequences=_progress_sequences,
)


def push_progress(project_id: str, event: dict) -> None:
    """Compatibility callback for callers outside an application composition root."""
    _compatibility_buffer.push(project_id, event)


@router.get("/api/projects/{project_id}/progress")
async def progress_stream(project_id: str, request: Request) -> StreamingResponse:
    """Stream cached and future execution progress events."""

    buffer: ProgressBuffer = getattr(request.app.state, "progress_buffer", _compatibility_buffer)

    async def generate():
        with buffer.lock:
            initial_events = list(buffer.events.get(project_id, []))
        for event in initial_events:
            yield f"data: {json.dumps(event)}\n\n"
        last_idx = len(initial_events)
        idle_ticks = 0
        try:
            while True:
                await asyncio.sleep(0.5)
                with buffer.lock:
                    events = buffer.events.get(project_id, [])
                    new_events = events[last_idx:]
                    last_idx = len(events)
                if new_events:
                    for event in new_events:
                        yield f"data: {json.dumps(event)}\n\n"
                    idle_ticks = 0
                else:
                    idle_ticks += 1
                if idle_ticks % 30 == 0:
                    yield ": heartbeat\n\n"
                if idle_ticks >= 600:
                    yield f"data: {json.dumps({'type': 'stream_closed', 'reason': 'idle_timeout'})}\n\n"
                    break
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
