"""Celery application.

Long-running (15+ minute) video processing MUST NOT run inside the HTTP
request. FastAPI enqueues a Celery task and returns a task_id immediately;
the worker container does the heavy lifting.
"""
from __future__ import annotations

from celery import Celery

from .config import settings

celery_app = Celery(
    "adaptation_checker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks"],
)

celery_app.conf.update(
    task_track_started=True,
    task_acks_late=True,                 # re-queue if a worker dies mid-job
    worker_prefetch_multiplier=1,        # one long job at a time per worker slot
    task_time_limit=60 * 60 * 3,         # hard 3h cap per job
    task_soft_time_limit=60 * 60 * 3 - 120,
    worker_max_tasks_per_child=4,        # recycle workers to release native OCR/GPU memory
    broker_connection_retry_on_startup=True,
)
