"""Director-Ready Enrichment (Formatting Stage 2).

Takes the Stage-1 corrected script and produces a director-ready screenplay —
Scene Profiles (character age/build/state-of-mind), grounded action, and an
emotional bracket on every dialogue cue — with dialogue kept VERBATIM. Renders
to a styled PDF via render_director_ready.

Flow (per ENRICHMENT_MODEL.md):
  1. Build a Character Bible over the whole script (continuity).
  2. Split into episodes; enrich each into @-markup (Gemini).
  3. Concatenate markup → render the director-ready PDF.
"""
from __future__ import annotations

from pathlib import Path

from .. import state
from . import format_check as FC
from . import render_director_ready
from .prompts import (ENRICH_SYSTEM_INSTRUCTION, build_bible_prompt,
                      build_enrich_prompt)

_MAX_BIBLE_CHARS = 60_000   # keep the bible prompt within context


def split_episodes(text: str) -> list[tuple[int, str]]:
    """Split corrected text into (episode_number, episode_body) using FC headers."""
    eps: list[dict] = []
    cur = None
    for ln in text.split("\n"):
        n = FC.episode_num(ln.strip())
        if n is not None:
            cur = {"num": n, "lines": []}
            eps.append(cur)
        elif cur is not None:
            cur["lines"].append(ln)
    if not eps:  # no explicit episode headers → treat the whole script as Episode 1
        return [(1, text.strip())]
    return [(e["num"], "\n".join(e["lines"]).strip()) for e in eps]


def _markup_only(text: str) -> str:
    """Keep only valid @-markup lines (drop any stray prose / code fences)."""
    out = [ln for ln in text.split("\n") if ln.lstrip().startswith("@")]
    return "\n".join(out)


def run(task_id: str, corrected_text: str, workdir: Path, title: str,
        base: str = "script") -> dict:
    """Returns {'director_pdf', 'bible_md', 'markup'} or raises."""
    from .. import gemini  # lazy — AI SDK only needed here

    episodes = split_episodes(corrected_text)
    state.log(task_id, f"Director-ready enrichment: {len(episodes)} episode(s).")

    session = gemini.GeminiSession(ENRICH_SYSTEM_INSTRUCTION)

    # 1) Character Bible (continuity across episodes)
    state.log(task_id, "Building character bible…")
    bible = session.generate([build_bible_prompt(corrected_text[:_MAX_BIBLE_CHARS])],
                             temperature=0.3, max_output_tokens=2048).strip()
    bible_md = workdir / f"{base}_character_bible.md"
    bible_md.write_text(f"# Character Bible — {title}\n\n{bible}\n", encoding="utf-8")

    # 2) Enrich each episode → @-markup
    parts: list[str] = []
    for i, (ep_num, ep_text) in enumerate(episodes, 1):
        pct = 30 + int(i / max(len(episodes), 1) * 60)
        state.set_step(task_id, 2, f"Enriching episode {ep_num} ({i}/{len(episodes)})…", pct)
        if not ep_text.strip():
            continue
        markup = session.generate([build_enrich_prompt(ep_num, ep_text, bible)],
                                  temperature=0.5, max_output_tokens=8192)
        markup = _markup_only(markup)
        if not markup.strip().startswith("@EP"):
            markup = f"@EP|EPISODE {ep_num}\n" + markup
        parts.append(markup)
        state.log(task_id, f"✓ Episode {ep_num} enriched.")

    full_markup = "\n".join(parts)
    markup_file = workdir / f"{base}_director_ready.markup.txt"
    markup_file.write_text(full_markup, encoding="utf-8")

    # 3) Render the director-ready PDF
    director_pdf = workdir / f"{base}_director_ready.pdf"
    render_director_ready.build_from_text(
        full_markup, str(director_pdf), title,
        subtitle="Director-Ready Screenplay — Scene Profiles, grounded action & "
                 "emotional cues (dialogue kept verbatim)",
    )
    state.log(task_id, "Director-ready PDF rendered.")
    return {"director_pdf": director_pdf, "bible_md": bible_md, "markup": full_markup}
