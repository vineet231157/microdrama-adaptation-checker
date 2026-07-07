"""FastAPI application — thin HTTP layer over Celery + Redis state.

Endpoints
  POST /api/format                     standalone Formatter (Model 4)
  POST /api/start-pipeline             full 5-step pipeline
  GET  /api/task-status/{task_id}      one-shot status (polling)
  GET  /api/task-stream/{task_id}      Server-Sent Events live progress
  GET  /api/download/{task_id}/srts    SRTs zip
  GET  /api/download/{task_id}/screenplays  individual screenplays zip
  GET  /api/download/{task_id}/final   master PDF + evaluation report zip
  GET  /api/download/{task_id}/format  formatted PDF (Formatting-only mode)
  GET  /health
"""
from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from . import state
from .config import settings
from .schemas import TaskCreatedResponse, TaskStatusResponse
from .tasks import format_task, pipeline_task

app = FastAPI(title="Microdrama Adaptation Checker — Super Model API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _save_upload(upload: UploadFile, task_id: str) -> Path:
    wd = settings.WORK_ROOT / task_id
    wd.mkdir(parents=True, exist_ok=True)
    dest = wd / f"upload_{Path(upload.filename).name}"
    with dest.open("wb") as f:
        while chunk := upload.file.read(1024 * 1024):
            f.write(chunk)
    return dest


@app.get("/health")
def health():
    return {"ok": True}


# ── OPTION 1: Formatting only ──────────────────────────────────────────────
@app.post("/api/format", response_model=TaskCreatedResponse)
def start_format(file: UploadFile = File(...), show_title: str = Form("")):
    if not file.filename:
        raise HTTPException(400, "No file uploaded.")
    task_id = uuid.uuid4().hex
    state.create(task_id, mode="format", show_title=show_title)
    path = _save_upload(file, task_id)
    format_task.delay(task_id, str(path), show_title)
    return TaskCreatedResponse(task_id=task_id)


# ── OPTION 2: Full pipeline ────────────────────────────────────────────────
@app.post("/api/start-pipeline", response_model=TaskCreatedResponse)
def start_pipeline(
    drive_url: str = Form(...),
    access_token: str = Form(...),
    hindi_script: UploadFile = File(...),
    show_title: str = Form(""),
    max_episodes: int = Form(0),
):
    if not hindi_script.filename:
        raise HTTPException(400, "The Hindi OG script is required.")
    task_id = uuid.uuid4().hex
    state.create(task_id, mode="pipeline", show_title=show_title)
    hindi_path = _save_upload(hindi_script, task_id)
    pipeline_task.delay(task_id, drive_url, access_token, str(hindi_path),
                        show_title, max_episodes)
    return TaskCreatedResponse(task_id=task_id)


# ── Status (polling) ───────────────────────────────────────────────────────
@app.get("/api/task-status/{task_id}", response_model=TaskStatusResponse)
def task_status(task_id: str):
    st = state.get(task_id)
    if not st:
        raise HTTPException(404, "Unknown task_id.")
    return st


# ── Status (SSE live stream) ───────────────────────────────────────────────
@app.get("/api/task-stream/{task_id}")
async def task_stream(task_id: str):
    if not state.get(task_id):
        raise HTTPException(404, "Unknown task_id.")

    async def gen():
        pubsub = state.subscribe(task_id)
        loop = asyncio.get_event_loop()
        try:
            # Always send the current state first.
            st = state.get(task_id)
            yield f"data: {json.dumps(st)}\n\n"
            last_status = st.get("status") if st else None
            while True:
                # Wait for a publish (blocking redis call off the event loop),
                # with a timeout so we also send periodic keepalives.
                msg = await loop.run_in_executor(
                    None, lambda: pubsub.get_message(timeout=15.0,
                                                     ignore_subscribe_messages=True)
                )
                st = state.get(task_id)
                if st:
                    yield f"data: {json.dumps(st)}\n\n"
                    if st.get("status") in ("done", "error"):
                        break
                    last_status = st.get("status")
                if msg is None:
                    yield ": keepalive\n\n"  # comment line keeps the connection open
        finally:
            pubsub.close()

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Downloads ──────────────────────────────────────────────────────────────
_ARTIFACT_FILES = {
    "srts": ("SRT_Files.zip", "SRT_Files.zip"),
    "screenplays": ("Screenplays.zip", "Individual_Screenplays.zip"),
    "final": ("Final_Deliverables.zip", "Final_Deliverables.zip"),
    "format": ("Formatted.zip", "Formatted_Script.zip"),
}


@app.get("/api/download/{task_id}/{kind}")
def download(task_id: str, kind: str):
    if kind not in _ARTIFACT_FILES:
        raise HTTPException(404, "Unknown artifact.")
    filename, download_name = _ARTIFACT_FILES[kind]
    path = settings.WORK_ROOT / task_id / filename
    if not path.exists():
        raise HTTPException(404, "Artifact not ready yet.")
    return FileResponse(path, media_type="application/zip", filename=download_name)
