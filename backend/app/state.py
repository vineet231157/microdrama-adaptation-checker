"""Redis-backed job state + progress log.

The Celery worker WRITES progress here; the FastAPI web process READS it (for
the SSE stream and status polling). Redis is the shared blackboard between the
two processes.

State shape (stored as one JSON blob per job under key ``job:{task_id}``)::

    {
      "task_id": "...",
      "mode": "pipeline" | "format",
      "status": "queued" | "running" | "done" | "error",
      "step": 1..5,                      # current pipeline step (pipeline mode)
      "step_label": "Extracting subtitles…",
      "percent": 0..100,
      "show_title": "...",
      "log": [ {"ts": 1234.5, "level": "info", "msg": "..."} , ... ],
      "artifacts": {                     # populated progressively
          "srts_zip":        "/api/download/{id}/srts",
          "screenplays_zip": "/api/download/{id}/screenplays",
          "final_zip":       "/api/download/{id}/final",
          "format_pdf":      "/api/download/{id}/format"
      },
      "drive": { "srt_folder": "https://…", "screenplay_folder": "…" },
      "error": null
    }
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional

import redis

from .config import settings

_r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)

_KEY = "job:{}"
# A pub/sub channel per job so the SSE endpoint can react instantly instead of
# busy-polling. Polling is still available as a fallback.
_CHAN = "jobevents:{}"


def _key(task_id: str) -> str:
    return _KEY.format(task_id)


def create(task_id: str, mode: str, show_title: str = "") -> dict:
    state = {
        "task_id": task_id,
        "mode": mode,
        "status": "queued",
        "step": 0,
        "step_label": "Queued",
        "percent": 0,
        "show_title": show_title,
        "log": [],
        "artifacts": {},
        "drive": {},
        "error": None,
    }
    _save(task_id, state)
    return state


def get(task_id: str) -> Optional[dict]:
    raw = _r.get(_key(task_id))
    return json.loads(raw) if raw else None


def _save(task_id: str, state: dict) -> None:
    _r.set(_key(task_id), json.dumps(state), ex=settings.JOB_TTL_SECONDS)
    # Notify any SSE listeners that state changed.
    _r.publish(_CHAN.format(task_id), "1")


def update(task_id: str, **fields: Any) -> dict:
    state = get(task_id) or create(task_id, fields.get("mode", "pipeline"))
    state.update(fields)
    _save(task_id, state)
    return state


def set_step(task_id: str, step: int, label: str, percent: int) -> None:
    update(task_id, status="running", step=step, step_label=label, percent=percent)


def add_artifact(task_id: str, name: str, url: str) -> None:
    state = get(task_id)
    if not state:
        return
    state.setdefault("artifacts", {})[name] = url
    _save(task_id, state)


def set_drive_link(task_id: str, name: str, url: str) -> None:
    state = get(task_id)
    if not state:
        return
    state.setdefault("drive", {})[name] = url
    _save(task_id, state)


def log(task_id: str, msg: str, level: str = "info") -> None:
    state = get(task_id)
    if not state:
        return
    state.setdefault("log", []).append({"ts": round(time.time(), 2), "level": level, "msg": msg})
    # keep the log bounded
    state["log"] = state["log"][-400:]
    _save(task_id, state)


def finish(task_id: str) -> None:
    update(task_id, status="done", percent=100, step_label="Complete")


def fail(task_id: str, error: str) -> None:
    update(task_id, status="error", error=error, step_label="Failed")
    log(task_id, f"FATAL: {error}", level="error")


def subscribe(task_id: str):
    """Return a redis pubsub object already subscribed to this job's channel."""
    ps = _r.pubsub()
    ps.subscribe(_CHAN.format(task_id))
    return ps
