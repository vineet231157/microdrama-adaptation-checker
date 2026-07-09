"""STEP 5 — AI Adaptation Evaluator (Model 5).

Compares the human-written Hindi OG script against the AI-generated English
master screenplay, judged against the Scriptwriter Checker Bible. Gemini returns
strict JSON (see prompts.EVAL_SCHEMA); we render it into an aesthetically
pleasing, colour-coded PDF report.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .. import state
from ..config import settings
from .prompts import (EPISODE_EVAL_SCHEMA, EVAL_SYSTEM_INSTRUCTION, SERIES_SCHEMA,
                      build_episode_eval_prompt, build_series_prompt)
from .textextract import extract_text


def _safe_json(raw: str) -> dict:
    """Parse Gemini JSON tolerantly: strip code fences, and if the tail is
    truncated, trim to the last balanced brace so we still get usable data."""
    s = (raw or "").strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s).strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    # repair: cut to the last closing brace and balance
    end = s.rfind("}")
    if end != -1:
        frag = s[:end + 1]
        for _ in range(6):  # try closing a few open braces/brackets
            try:
                return json.loads(frag)
            except Exception:
                frag += "}"
    return {}

# Verdict → colour (mirrors the docx report's palette).
_VERDICT_COLOR = {
    "pass": "#2E7D32", "strong": "#2E7D32", "mostly ok": "#2E7D32",
    "mixed": "#B8860B", "expanded": "#B8860B",
    "flag": "#B22222",
}
NAVY, BLUE, GREY, RED = "#1F3864", "#2E75B6", "#666666", "#B22222"


def _verdict_color(v: str) -> str:
    return _VERDICT_COLOR.get((v or "").strip().lower(), "#0f172a")


def _truncate(text: str, limit: int = 120_000) -> str:
    """Keep prompts within model context; screenplays are large."""
    return text if len(text) <= limit else text[:limit] + "\n…[truncated]…"


def render_report_pdf(data: dict, out_pdf: Path, show_title: str) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_LEFT, TA_CENTER
    from reportlab.lib import colors
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                    TableStyle, ListFlowable, ListItem, PageBreak)
    from reportlab.lib.styles import ParagraphStyle

    S = {
        "title": ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=22, textColor=NAVY,
                                alignment=TA_LEFT, spaceAfter=4, leading=26),
        "sub": ParagraphStyle("s", fontName="Helvetica", fontSize=11, textColor=GREY,
                              spaceAfter=12, leading=14),
        "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=15, textColor=NAVY,
                             spaceBefore=16, spaceAfter=8, leading=18),
        "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=12, textColor=BLUE,
                             spaceBefore=10, spaceAfter=5, leading=15),
        "body": ParagraphStyle("b", fontName="Helvetica", fontSize=10, leading=14, spaceAfter=5),
        "small": ParagraphStyle("sm", fontName="Helvetica", fontSize=9, textColor=GREY, leading=12),
        "cell": ParagraphStyle("c", fontName="Helvetica", fontSize=9, leading=12),
        "cellb": ParagraphStyle("cb", fontName="Helvetica-Bold", fontSize=9, leading=12),
    }

    def esc(s: str) -> str:
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def bullets(items, empty="None."):
        items = items or [empty]
        return ListFlowable(
            [ListItem(Paragraph(esc(x), S["body"]), leftIndent=10) for x in items],
            bulletType="bullet", start="•", leftIndent=14,
        )

    flow = []
    score = data.get("overall_score", "—")
    verdict = data.get("overall_verdict", "—")
    flow += [
        Paragraph("ADAPTATION REVIEW REPORT", S["title"]),
        Paragraph(esc(f"{show_title}  ·  Overall: {verdict}  ·  Score: {score}/100"), S["sub"]),
        Paragraph("1. Executive summary", S["h1"]),
        Paragraph(esc(data.get("summary", "")), S["body"]),
    ]

    # Character / world map
    cmap = data.get("character_world_map") or []
    if cmap:
        flow.append(Paragraph("Source → Hindi character / world map", S["h2"]))
        rows = [[Paragraph("Source", S["cellb"]), Paragraph("Hindi", S["cellb"]),
                 Paragraph("Note", S["cellb"])]]
        for m in cmap:
            rows.append([Paragraph(esc(m.get("source", "")), S["cell"]),
                         Paragraph(esc(m.get("hindi", "")), S["cell"]),
                         Paragraph(esc(m.get("note", "")), S["cell"])])
        t = Table(rows, colWidths=[1.7 * inch, 1.7 * inch, 3.1 * inch])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(NAVY)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BBBBBB")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        flow += [t, Spacer(1, 6)]

    # Bible parameter table
    flow.append(Paragraph("2. Compliance with the Script Review Parameters", S["h1"]))
    rows = [[Paragraph("Parameter", S["cellb"]), Paragraph("Result", S["cellb"]),
             Paragraph("Notes", S["cellb"])]]
    for p in data.get("parameters", []):
        note = esc(p.get("note", ""))
        ex = p.get("examples") or []
        if ex:
            note += "<br/><i>" + esc(" · ".join(ex[:2])) + "</i>"
        rows.append([
            Paragraph(esc(p.get("code", "")), S["cell"]),
            Paragraph(f'<b><font color="{_verdict_color(p.get("verdict",""))}">'
                      f'{esc(p.get("verdict",""))}</font></b>', S["cell"]),
            Paragraph(note, S["cell"]),
        ])
    t = Table(rows, colWidths=[1.9 * inch, 1.1 * inch, 3.5 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(NAVY)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BBBBBB")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F7FA")]),
    ]))
    flow += [t]

    # Gaps + changes
    flow += [
        Paragraph("3. Genuine information gaps", S["h1"]),
        Paragraph("The only true &lsquo;missing information&rsquo; — plot points, motivations or facts "
                  "a Hindi viewer never receives.", S["small"]),
        bullets(data.get("information_gaps"), empty="None — no important story information is lost."),
        Paragraph("Notable adaptation changes", S["h2"]),
        bullets(data.get("adaptation_changes"), empty="None notable."),
    ]

    # Episode-by-episode
    eps = data.get("episodes") or []
    if eps:
        flow += [PageBreak(), Paragraph("4. Episode-by-episode (source episodes)", S["h1"])]
        for e in sorted(eps, key=lambda x: x.get("source_episode", 0)):
            flow.append(Paragraph(f"Episode {e.get('source_episode','?')}", S["h2"]))
            if e.get("maps_to"):
                flow.append(Paragraph(f'<b>Maps to:</b> <i>{esc(e["maps_to"])}</i>', S["small"]))
            changes = ["Added — " + a for a in (e.get("added") or [])] + (e.get("changes") or [])
            flow.append(Paragraph('<b><font color="%s">Adaptation changes</font></b>' % GREY, S["body"]))
            flow.append(bullets(changes, empty="None notable."))
            flow.append(Paragraph('<b><font color="%s">Missing information</font></b>' % RED, S["body"]))
            flow.append(bullets(e.get("gaps"), empty="None — no information missing."))
            flow.append(Paragraph(f'<b>Freeze / hook:</b> {esc(e.get("freeze",""))}', S["small"]))
            flow.append(Spacer(1, 8))

    # Recommendations
    flow += [Paragraph("5. Recommendations", S["h1"]),
             bullets(data.get("recommendations"), empty="No further recommendations.")]

    SimpleDocTemplate(str(out_pdf), pagesize=A4, leftMargin=0.9 * inch, rightMargin=0.9 * inch,
                      topMargin=0.9 * inch, bottomMargin=0.9 * inch,
                      title=f"Adaptation Review — {show_title}").build(flow)
    return out_pdf


def run(task_id: str, hindi_script_path: str, english_master_text: str,
        workdir: Path, show_title: str) -> dict:
    """Returns {'report_pdf', 'report_json'}."""
    from .. import gemini  # lazy — keeps the AI SDK out of the render-only path

    from . import enrich_director_ready  # reuse its episode splitter

    state.set_step(task_id, 5, "Evaluating the Hindi adaptation…", 82)

    hindi_text = extract_text(hindi_script_path)
    state.log(task_id, f"Extracted {len(hindi_text)} chars from the Hindi script.")

    # Prefer the configured model (pro reasons better); resolve_chain keeps only
    # models the key actually has.
    models = [settings.GEMINI_MODEL, *settings.GEMINI_FALLBACKS]
    english_ctx = _truncate(english_master_text, 200_000)   # full source as context

    # ── PASS 1: series-level verdict + Bible table + character map (one small call) ──
    state.set_step(task_id, 5, "Evaluating: series overview…", 82)
    series = _safe_json(gemini.generate_text(
        models, EVAL_SYSTEM_INSTRUCTION,
        [build_series_prompt(english_ctx, _truncate(hindi_text, 200_000), show_title)],
        temperature=0.3, max_output_tokens=8192, json_schema=SERIES_SCHEMA))

    # ── PASS 2: rigorous PER-EPISODE analysis (parallel, each a small JSON) ──
    episodes = [(n, t) for (n, t) in enrich_director_ready.split_episodes(hindi_text) if t.strip()]
    state.log(task_id, f"Evaluating {len(episodes)} Hindi episode(s) individually "
                       f"({settings.ENRICH_CONCURRENCY} in parallel)…")

    def _one_ep(item):
        ep_num, ep_text = item
        raw = gemini.generate_text(
            models, EVAL_SYSTEM_INSTRUCTION,
            [build_episode_eval_prompt(ep_num, ep_text, english_ctx, show_title)],
            temperature=0.3, max_output_tokens=8192, json_schema=EPISODE_EVAL_SCHEMA)
        d = _safe_json(raw)
        d["hindi_episode"] = ep_num
        d["source_episode"] = ep_num
        return d

    ep_results: list[dict] = [{} for _ in episodes]
    done = 0
    with ThreadPoolExecutor(max_workers=settings.ENRICH_CONCURRENCY) as pool:
        futs = {pool.submit(_one_ep, ep): i for i, ep in enumerate(episodes)}
        for fut in as_completed(futs):
            i = futs[fut]
            try:
                ep_results[i] = fut.result()
            except Exception as e:
                ep_results[i] = {"hindi_episode": episodes[i][0], "source_episode": episodes[i][0],
                                 "freeze": f"[evaluation failed: {e}]"}
                state.log(task_id, f"✗ Episode {episodes[i][0]} eval failed: {e}", level="error")
            done += 1
            state.set_step(task_id, 5, f"Evaluating episodes ({done}/{len(episodes)})…",
                           82 + int(done / max(len(episodes), 1) * 12))

    ep_results = [e for e in ep_results if e]

    # ── Assemble the combined findings object the renderers expect ──
    data = dict(series)
    data.setdefault("overall_verdict", "—")
    data.setdefault("overall_score", 0)
    data.setdefault("summary", "")
    data["episodes"] = ep_results
    data["hindi_episodes"] = ep_results
    # Fold per-episode genuine gaps into the series gap list if the series pass missed them.
    ep_gaps = [f"Ep {e.get('hindi_episode')}: {g}" for e in ep_results for g in (e.get("gaps") or [])]
    data["information_gaps"] = (series.get("information_gaps") or []) + ep_gaps

    report_json = workdir / "Adaptation_Report.json"
    report_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    report_pdf = workdir / "Adaptation_Report.pdf"
    render_report_pdf(data, report_pdf, show_title)

    # Annotated Hindi Script (PDF): the Hindi OG script returned VERBATIM with a grey
    # "ADAPTATION CHANGES" box + red "MISSING INFORMATION" box per episode, and the
    # actual ADDED passages highlighted green inline.
    annotated_pdf = workdir / "Annotated_Hindi_Script.pdf"
    try:
        from . import annotate_hindi
        hindi_ann = {
            int(e["hindi_episode"]): {
                "added": e.get("added") or [], "added_spans": e.get("added_spans") or [],
                "gaps": e.get("gaps") or [], "changes": e.get("changes") or [],
            }
            for e in (data.get("hindi_episodes") or []) if "hindi_episode" in e
        }
        annotate_hindi.build(hindi_text, str(annotated_pdf),
                             title=f"{show_title} — Annotated Hindi Script", hindi_ann=hindi_ann)
        state.log(task_id, f"Annotated Hindi script (PDF) written ({len(hindi_ann)} episode(s) flagged).")
    except Exception as e:
        annotated_pdf = None
        state.log(task_id, f"Annotated Hindi script skipped ({e}).", level="error")

    state.log(
        task_id,
        f"Step 5 complete — verdict {data.get('overall_verdict')}, "
        f"score {data.get('overall_score')}/100, "
        f"{len(data.get('information_gaps', []))} genuine gap(s).",
    )
    return {"report_pdf": report_pdf, "report_json": report_json,
            "annotated_pdf": annotated_pdf, "data": data}
