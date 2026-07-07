"""STEP 5 — AI Adaptation Evaluator (Model 5).

Compares the human-written Hindi OG script against the AI-generated English
master screenplay, judged against the Scriptwriter Checker Bible. Gemini returns
strict JSON (see prompts.EVAL_SCHEMA); we render it into an aesthetically
pleasing, colour-coded PDF report.
"""
from __future__ import annotations

from pathlib import Path

from .. import state
from .prompts import EVAL_SCHEMA, EVAL_SYSTEM_INSTRUCTION, build_eval_prompt
from .textextract import extract_text

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

    state.set_step(task_id, 5, "Evaluating the Hindi adaptation…", 82)

    hindi_text = extract_text(hindi_script_path)
    state.log(task_id, f"Extracted {len(hindi_text)} chars from the Hindi script.")

    session = gemini.GeminiSession(EVAL_SYSTEM_INSTRUCTION)
    prompt = build_eval_prompt(_truncate(hindi_text), _truncate(english_master_text), show_title)
    state.log(task_id, "Running adaptation evaluation against the Bible rules…")
    data = session.generate_json([prompt], json_schema=EVAL_SCHEMA,
                                 temperature=0.3, max_output_tokens=8192)

    report_json = workdir / "Adaptation_Report.json"
    import json
    report_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    report_pdf = workdir / "Adaptation_Report.pdf"
    render_report_pdf(data, report_pdf, show_title)

    state.log(
        task_id,
        f"Step 5 complete — verdict {data.get('overall_verdict')}, "
        f"score {data.get('overall_score')}/100, "
        f"{len(data.get('information_gaps', []))} genuine gap(s).",
    )
    return {"report_pdf": report_pdf, "report_json": report_json, "data": data}
