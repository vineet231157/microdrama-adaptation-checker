"""STEP 3 — Merge & stitch individual episodes into one master document.

Episodes are joined with clear ``EPISODE N`` transitions. Because Step 2 already
instructs Gemini to restart scene numbers at Scene 1 per episode, we preserve
that; the deterministic formatter in Step 4 re-verifies and re-numbers if needed.
"""
from __future__ import annotations

import re
from pathlib import Path

from .. import state


_EP_HEADER = re.compile(r"^\s*EPISODE\s+\d+\b", re.IGNORECASE)


def _normalise_episode_body(ep_num: int, text: str) -> str:
    """Ensure the body starts with a single clean 'EPISODE N' header (no dupes)."""
    lines = text.strip().split("\n")
    # Drop a leading model-emitted 'EPISODE N' line — we add our own canonical one.
    while lines and _EP_HEADER.match(lines[0]):
        lines.pop(0)
    body = "\n".join(lines).strip()
    return f"# EPISODE {ep_num}\n\n{body}"


def run(task_id: str, episodes: list[dict], workdir: Path, show_title: str) -> dict:
    """Returns {'merged_text': str, 'merged_md': Path}."""
    state.set_step(task_id, 3, "Merging episodes into a master document…", 62)

    parts = [
        f"# {show_title} — MASTER SCREENPLAY\n\n"
        f"*Stitched from {len(episodes)} episode(s). Dialogue kept verbatim.*\n"
    ]
    for ep in sorted(episodes, key=lambda e: e["ep"]):
        parts.append(_normalise_episode_body(ep["ep"], ep["screenplay"]))

    merged_text = "\n\n".join(parts).strip() + "\n"
    merged_md = workdir / "Master_Screenplay.md"
    merged_md.write_text(merged_text, encoding="utf-8")

    state.log(task_id, f"Step 3 complete — merged {len(episodes)} episode(s).")
    return {"merged_text": merged_text, "merged_md": merged_md}
