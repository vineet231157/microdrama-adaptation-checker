"""Shared helpers used across pipeline steps: episode numbering, SRT parsing,
filename sanitising. Ported verbatim in behaviour from the notebooks so the
matching logic is identical to what you validated in Colab.
"""
from __future__ import annotations

import re
from pathlib import Path

import pysrt


def sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")


def episode_number(name: str) -> int | None:
    """Best-effort episode number from a filename (identical to the notebook)."""
    stem = Path(name).stem
    for pat in [
        r"s\d+[\s_.-]*e0*(\d+)", r"episode[\s_-]*0*(\d+)",
        r"\bep[\s_.-]*0*(\d+)", r"\be0*(\d+)\b",
        r"[_\-\s]0*(\d+)\b", r"(\d+)",
    ]:
        m = re.search(pat, stem, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


def parse_srt_text(local_srt: str | Path) -> str:
    """Return a clean '[HH:MM:SS] Text' transcript, dialogue verbatim & in order.

    Tries multiple encodings because OCR'd/Chinese-origin SRTs are inconsistent.
    """
    subs = None
    for enc in ("utf-8", "utf-8-sig", "gbk", "gb18030", "latin-1"):
        try:
            subs = pysrt.open(str(local_srt), encoding=enc)
            break
        except Exception:
            continue
    if subs is None:
        raise RuntimeError(f"Could not parse SRT: {local_srt}")

    lines: list[str] = []
    for cue in subs:
        text = re.sub(r"<[^>]+>", "", cue.text)
        text = re.sub(r"\{[^}]*\}", "", text)
        text = re.sub(r"\s+", " ", text.replace("\n", " ")).strip()
        if text:
            t = cue.start
            lines.append(f"[{t.hours:02d}:{t.minutes:02d}:{t.seconds:02d}] {text}")
    return "\n".join(lines)


def match_srt(video_name: str, srts: list[dict]) -> dict | None:
    """Find the SRT that belongs to a video: exact stem first, then ep number."""
    by_stem = {Path(s["name"]).stem.lower(): s for s in srts}
    stem = Path(video_name).stem.lower()
    if stem in by_stem:
        return by_stem[stem]
    n = episode_number(video_name)
    if n is None:
        return None
    for s in srts:
        if episode_number(s["name"]) == n:
            return s
    return None
