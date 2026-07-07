"""Pydantic request/response models."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class StartPipelineRequest(BaseModel):
    drive_url: str = Field(..., description="Google Drive folder URL/ID with the raw videos")
    access_token: str = Field(..., description="Google OAuth access token with Drive scope")
    show_title: str = Field("", description="Optional show title override")
    max_episodes: int = Field(0, description="0 = all episodes; >0 limits for a test run")
    # The Hindi OG script is uploaded as multipart; its server-side path is filled in
    # by the endpoint before the Celery task is dispatched.
    hindi_script_path: Optional[str] = None


class TaskCreatedResponse(BaseModel):
    task_id: str
    status: str = "queued"


class TaskStatusResponse(BaseModel):
    task_id: str
    mode: str
    status: str
    step: int
    step_label: str
    percent: int
    show_title: str
    log: list[dict[str, Any]]
    artifacts: dict[str, str]
    drive: dict[str, str]
    error: Optional[str] = None
