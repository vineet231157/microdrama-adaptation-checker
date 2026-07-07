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

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .. import state
from ..config import settings
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

    model = settings.ENRICH_MODEL  # fast model (Flash) for this mechanical transform
    episodes = [(n, t) for (n, t) in split_episodes(corrected_text) if t.strip()]
    state.log(task_id, f"Director-ready enrichment: {len(episodes)} episode(s) "
                       f"on {model}, {settings.ENRICH_CONCURRENCY} in parallel.")

    # 1) Character Bible (continuity across episodes) — one quick call
    state.set_step(task_id, 2, "Building character bible…", 30)
    bible = gemini.generate_text(model, ENRICH_SYSTEM_INSTRUCTION,
                                 [build_bible_prompt(corrected_text[:_MAX_BIBLE_CHARS])],
                                 temperature=0.3, max_output_tokens=2048).strip()
    bible_md = workdir / f"{base}_character_bible.md"
    bible_md.write_text(f"# Character Bible — {title}\n\n{bible}\n", encoding="utf-8")

    # 2) Enrich every episode CONCURRENTLY → @-markup (order preserved on collect)
    def _one(item):
        ep_num, ep_text = item
        markup = gemini.generate_text(model, ENRICH_SYSTEM_INSTRUCTION,
                                      [build_enrich_prompt(ep_num, ep_text, bible)],
                                      temperature=0.5, max_output_tokens=8192)
        markup = _markup_only(markup)
        if not markup.strip().startswith("@EP"):
            markup = f"@EP|EPISODE {ep_num}\n" + markup
        return markup

    results: list[str] = [""] * len(episodes)
    done = 0
    with ThreadPoolExecutor(max_workers=settings.ENRICH_CONCURRENCY) as pool:
        futures = {pool.submit(_one, ep): i for i, ep in enumerate(episodes)}
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                results[i] = fut.result()
            except Exception as e:
                results[i] = f"@EP|EPISODE {episodes[i][0]}\n@AC|[enrichment failed for this episode: {e}]"
                state.log(task_id, f"✗ Episode {episodes[i][0]} enrichment failed: {e}", level="error")
            done += 1
            state.set_step(task_id, 2, f"Enriching episodes ({done}/{len(episodes)})…",
                           30 + int(done / max(len(episodes), 1) * 60))

    full_markup = "\n".join(m for m in results if m)
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
