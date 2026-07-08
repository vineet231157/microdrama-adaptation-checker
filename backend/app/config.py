"""Central configuration, loaded from environment variables.

Nothing secret is hard-coded. In production these come from the container's
environment (Render/Railway/Cloud Run secrets). Locally they come from a .env
file that docker-compose feeds in.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


class Settings:
    # ── Infrastructure ────────────────────────────────────────────────────
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
    CELERY_BROKER_URL: str = os.getenv("CELERY_BROKER_URL", os.getenv("REDIS_URL", "redis://redis:6379/0"))
    CELERY_RESULT_BACKEND: str = os.getenv("CELERY_RESULT_BACKEND", os.getenv("REDIS_URL", "redis://redis:6379/1"))

    # Root working directory. Each job gets a UUID subfolder underneath it so
    # concurrent jobs never see each other's files.
    WORK_ROOT: Path = Path(os.getenv("WORK_ROOT", "/tmp/adaptation_jobs"))

    # ── AI / ML ───────────────────────────────────────────────────────────
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    # Primary model + ordered fallbacks (first that works is cached for the job).
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")
    # Fallbacks span current model families; gemini.resolve_chain() drops any the
    # key doesn't have (e.g. retired 1.5-* models) and adds whatever IS available.
    GEMINI_FALLBACKS: list[str] = [
        m.strip()
        for m in os.getenv(
            "GEMINI_FALLBACKS",
            "gemini-2.5-pro,gemini-2.0-flash,gemini-2.5-flash,gemini-1.5-pro,gemini-1.5-flash",
        ).split(",")
        if m.strip()
    ]
    # Director-ready enrichment is a fast, mechanical transform → prefer a FAST
    # model and run episodes CONCURRENTLY. resolve_chain() adds an available pro
    # model as a safety net so enrichment can't die on "model not found".
    ENRICH_MODEL: str = os.getenv("ENRICH_MODEL", "gemini-2.0-flash")
    ENRICH_FALLBACKS: list[str] = [
        m.strip() for m in os.getenv("ENRICH_FALLBACKS", "gemini-2.5-flash,gemini-1.5-flash").split(",")
        if m.strip()
    ]
    ENRICH_CONCURRENCY: int = int(os.getenv("ENRICH_CONCURRENCY", "4"))

    # ── OCR (Step 1) ──────────────────────────────────────────────────────
    OCR_LANG: str = os.getenv("OCR_LANG", "en")
    OCR_USE_GPU: bool = os.getenv("OCR_USE_GPU", "true").lower() == "true"
    OCR_CONF_THRESHOLD: int = int(os.getenv("OCR_CONF_THRESHOLD", "75"))
    OCR_SIM_THRESHOLD: int = int(os.getenv("OCR_SIM_THRESHOLD", "80"))
    OCR_FRAMES_TO_SKIP: int = int(os.getenv("OCR_FRAMES_TO_SKIP", "1"))
    OCR_SAMPLE_FPS: float = float(os.getenv("OCR_SAMPLE_FPS", "2.0"))  # subtitle samples/sec
    # Auto-crop tuning
    AUTOCROP_SAMPLES: int = int(os.getenv("AUTOCROP_SAMPLES", "10"))
    AUTOCROP_LOWER_FRACTION: float = float(os.getenv("AUTOCROP_LOWER_FRACTION", "0.30"))
    AUTOCROP_MARGIN_PX: int = int(os.getenv("AUTOCROP_MARGIN_PX", "10"))

    # ── CORS / frontend ───────────────────────────────────────────────────
    ALLOWED_ORIGINS: list[str] = [
        o.strip()
        for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
        if o.strip()
    ]

    # Public base URL of THIS backend, used to build absolute download links
    # that the frontend can hand to the browser.
    PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")

    # How long finished jobs (and their /tmp files) live before cleanup, seconds.
    JOB_TTL_SECONDS: int = int(os.getenv("JOB_TTL_SECONDS", str(60 * 60 * 24)))


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.WORK_ROOT.mkdir(parents=True, exist_ok=True)
    return s


settings = get_settings()
