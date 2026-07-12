"""Gemini client wrapper: configuration, model fallback, tenacity-backed
retry against 429 rate limits, video File API upload/poll/delete, and a
JSON-mode generate for the evaluator.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import google.generativeai as genai
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from .config import settings

log = logging.getLogger(__name__)

_configured = False


def _configure() -> None:
    global _configured
    if not _configured:
        if not settings.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set.")
        genai.configure(api_key=settings.GEMINI_API_KEY)
        _configured = True


def _is_rate_limit(exc: Exception) -> bool:
    s = str(exc).lower()
    return any(k in s for k in ("429", "rate", "quota", "resource has been exhausted", "exhausted"))


def _is_unavailable(exc: Exception) -> bool:
    s = str(exc).lower()
    return any(k in s for k in ("not found", "not supported", "does not exist",
                                "deprecated", "unavailable", "404", "permission"))


def _resp_text(resp) -> str:
    """Extract text WITHOUT crashing when finish_reason != STOP.

    ``resp.text`` raises if the candidate has no text part (e.g. a thinking model
    that spent the whole budget, a SAFETY/MAX_TOKENS finish). We gather any text
    parts defensively and return '' if there truly are none, so the caller can
    fall back to the next model instead of the whole job dying.
    """
    try:
        return resp.text or ""
    except Exception:
        pass
    out = []
    try:
        for c in (getattr(resp, "candidates", None) or []):
            content = getattr(c, "content", None)
            for p in (getattr(content, "parts", None) or []):
                t = getattr(p, "text", None)
                if t:
                    out.append(t)
    except Exception:
        pass
    return "".join(out)


# Exponential backoff ONLY on 429/quota errors; everything else raises fast.
_retry = retry(
    reraise=True,
    stop=stop_after_attempt(6),
    wait=wait_exponential(multiplier=4, min=4, max=120),
    retry=retry_if_exception(_is_rate_limit),
)


_AVAILABLE: list[str] | None = None


def available_models() -> list[str]:
    """Model IDs this API key actually supports for generateContent (cached).

    Guards against 404s from deprecated/renamed models (e.g. gemini-1.5-* being
    retired) by adapting to whatever the key really has.
    """
    global _AVAILABLE
    if _AVAILABLE is None:
        _configure()
        try:
            _AVAILABLE = [
                m.name.split("/")[-1]
                for m in genai.list_models()
                if "generateContent" in getattr(m, "supported_generation_methods", [])
            ]
            log.info("Gemini models available to this key: %s", _AVAILABLE)
        except Exception as e:  # pragma: no cover
            log.warning("Could not list Gemini models (%s); using preferred names as-is.", e)
            _AVAILABLE = []
    return _AVAILABLE


def resolve_chain(preferred: list[str]) -> list[str]:
    """Return an ordered model chain guaranteed to contain models the key has.

    Keeps the caller's preference order, drops names the key doesn't have, then
    appends any available flash/pro models as a safety net so a call never fails
    just because every preferred name was renamed/deprecated.
    """
    avail = available_models()
    pref = [m for m in preferred if m]
    if not avail:
        return pref                       # couldn't query → try preferred as-is
    chain = [m for m in pref if m in avail]
    for m in avail:                       # safety net: prefer flash (fast), then pro
        if ("flash" in m or "pro" in m) and m not in chain:
            chain.append(m)
    return chain or avail[:3]


def _candidate_models() -> list[str]:
    return resolve_chain([settings.GEMINI_MODEL, *settings.GEMINI_FALLBACKS])


class GeminiSession:
    """Holds the resolved model for one job so fallback happens only once."""

    def __init__(self, system_instruction: str):
        _configure()
        self.system_instruction = system_instruction
        self._model = None
        self._model_name: str | None = None

    def _resolve(self):
        if self._model is not None:
            return self._model
        last = None
        for name in _candidate_models():
            try:
                mdl = genai.GenerativeModel(name, system_instruction=self.system_instruction)
                # Cheap liveness check happens on first real call; assume ok here.
                self._model, self._model_name = mdl, name
                log.info("Gemini model resolved: %s", name)
                return mdl
            except Exception as e:  # pragma: no cover
                last = e
                if _is_unavailable(e):
                    continue
                raise
        raise RuntimeError(f"No Gemini model available. Last error: {last}")

    @property
    def model_name(self) -> str | None:
        return self._model_name

    @_retry
    def generate(self, contents, *, temperature=0.6, max_output_tokens=8192, json_schema=None) -> str:
        cfg_kwargs = dict(temperature=temperature, max_output_tokens=max_output_tokens)
        if json_schema is not None:
            cfg_kwargs["response_mime_type"] = "application/json"
            cfg_kwargs["response_schema"] = json_schema
        cfg = genai.types.GenerationConfig(**cfg_kwargs)

        last = None
        for name in _candidate_models():
            try:
                mdl = self._model if self._model_name == name else genai.GenerativeModel(
                    name, system_instruction=self.system_instruction
                )
                resp = mdl.generate_content(contents, generation_config=cfg)
                text = _resp_text(resp)
                if not text:               # empty (MAX_TOKENS/SAFETY) → try next model
                    log.warning("Model %s returned no text; trying next…", name)
                    continue
                self._model, self._model_name = mdl, name
                return text
            except Exception as e:
                last = e
                if _is_unavailable(e):
                    log.warning("Model %s unavailable, trying next…", name)
                    continue
                raise  # rate-limit errors bubble to the @_retry wrapper
        raise RuntimeError(f"All Gemini models returned no usable text. Last error: {last}")

    def generate_json(self, contents, *, json_schema, **kw) -> dict:
        raw = self.generate(contents, json_schema=json_schema, **kw)
        return json.loads(raw)


# Fail-FAST retry for enrichment: a couple of quick retries on 429, then give up
# (so a low-quota key can't make the whole job hang for minutes on backoff).
_retry_fast = retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    retry=retry_if_exception(_is_rate_limit),
)


@_retry_fast
def generate_text(models: list[str], system_instruction: str, contents,
                  *, temperature=0.5, max_output_tokens=8192, json_schema=None) -> str:
    """Stateless generate over an ORDERED model list — SAFE for concurrent
    (multi-thread) calls (no shared mutable state). Used for enrichment + the
    chunked adaptation evaluation. ``models`` is tried in order; unavailable
    models are skipped, 429s retried a few times then raised (fail fast)."""
    _configure()
    cfg_kwargs = dict(temperature=temperature, max_output_tokens=max_output_tokens)
    if json_schema is not None:
        cfg_kwargs["response_mime_type"] = "application/json"
        cfg_kwargs["response_schema"] = json_schema
    cfg = genai.types.GenerationConfig(**cfg_kwargs)
    last = None
    # resolve_chain filters to models this key actually has, then adds available
    # flash/pro as a safety net — so enrichment never dies on "model not found".
    for name in resolve_chain(models):
        try:
            mdl = genai.GenerativeModel(name, system_instruction=system_instruction)
            text = _resp_text(mdl.generate_content(contents, generation_config=cfg))
            if not text:               # empty (MAX_TOKENS/SAFETY) → try next model
                continue
            return text
        except Exception as e:
            last = e
            if _is_unavailable(e):
                continue
            raise  # 429s bubble to @_retry_fast
    raise RuntimeError(f"All models returned no usable text. Last error: {last}")


# ── Video File API helpers ────────────────────────────────────────────────
def upload_video(local_path: Path, poll_seconds: int = 10, timeout_seconds: int = 900):
    """Upload a video to Gemini and block until it is ACTIVE."""
    _configure()
    vf = genai.upload_file(path=str(local_path))
    waited = 0
    while vf.state.name == "PROCESSING":
        if waited >= timeout_seconds:
            raise TimeoutError("Gemini video processing timed out.")
        time.sleep(poll_seconds)
        waited += poll_seconds
        vf = genai.get_file(vf.name)
    if vf.state.name != "ACTIVE":
        raise RuntimeError(f"Gemini video state = {vf.state.name}")
    return vf


def delete_video(name: str) -> None:
    try:
        genai.delete_file(name)
    except Exception:  # pragma: no cover — cleanup is best-effort
        pass
