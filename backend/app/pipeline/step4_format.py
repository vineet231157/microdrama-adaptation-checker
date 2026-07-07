"""STEP 4 — Total screenplay formatting (Model 4).

Runs the deterministic checker/auto-corrector (``format_check.py``) on the merged
markdown, then renders a clean, director-ready Master PDF whose layout follows the
house rules exactly:

  • Scene headings — left aligned, fully capitalised
  • Action        — left aligned, standard width
  • Character cue — centred (~3.7in indent), fully capitalised
  • Dialogue      — centred block (~2.5in indent), tighter right margin
  • Parenthetical — bracketed emotion, nested under the character name

Also returns the checker report (used to enrich the pipeline log) and the
corrected plain text.
"""
from __future__ import annotations

import re
from pathlib import Path

from .. import state
from . import format_check as FC


_TRANS = re.compile(r"(TO:|FRAME\.?|FREEZE\.?|FADE (IN|OUT)|CUT TO)\s*$", re.I)
_PAREN = re.compile(r"^\(.*\)$")


def _strip_md(text: str) -> str:
    """Remove markdown heading hashes / bullets so the PDF is clean screenplay text."""
    out = []
    for ln in text.split("\n"):
        s = re.sub(r"^\s{0,3}#{1,6}\s*", "", ln)   # drop leading '# '
        s = re.sub(r"^\s*[-*•]\s+", "• ", s)        # normalise bullets
        s = s.replace("**", "").replace("*", "")
        out.append(s)
    return "\n".join(out)


def render_master_pdf(text: str, out_pdf: Path, title: str, subtitle: str = "") -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import ParagraphStyle

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))  # keeps stray CJK safe
    FONT, FONT_B = "Courier", "Courier-Bold"

    ST = {
        "title": ParagraphStyle("title", fontName=FONT_B, fontSize=18, alignment=TA_CENTER,
                                spaceAfter=6, leading=22),
        "subtitle": ParagraphStyle("subtitle", fontName=FONT, fontSize=10, alignment=TA_CENTER,
                                   textColor="#475569", spaceAfter=14, leading=13),
        "ep": ParagraphStyle("ep", fontName=FONT_B, fontSize=13, alignment=TA_LEFT,
                             spaceBefore=18, spaceAfter=8, leading=16, textColor="#0f766e"),
        # Scene heading: left, caps
        "scene": ParagraphStyle("scene", fontName=FONT_B, fontSize=11, alignment=TA_LEFT,
                                spaceBefore=10, spaceAfter=4, leading=14),
        # Action: left, full width
        "action": ParagraphStyle("action", fontName=FONT, fontSize=10.5, alignment=TA_LEFT,
                                 spaceAfter=5, leading=13.5),
        # Character cue: ~3.7in from left, caps
        "cue": ParagraphStyle("cue", fontName=FONT_B, fontSize=10.5, leftIndent=3.7 * inch,
                              spaceBefore=6, leading=12),
        # Parenthetical: nested just under the cue
        "paren": ParagraphStyle("paren", fontName=FONT, fontSize=10, leftIndent=3.1 * inch,
                                textColor="#334155", leading=12),
        # Dialogue: centred block ~2.5in from left
        "dlg": ParagraphStyle("dlg", fontName=FONT, fontSize=10.5, leftIndent=2.5 * inch,
                              rightIndent=1.2 * inch, spaceAfter=4, leading=12.5),
        "trans": ParagraphStyle("trans", fontName=FONT_B, fontSize=10.5, alignment=TA_RIGHT,
                                textColor="#475569", spaceBefore=4, spaceAfter=8, leading=13),
    }

    def esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    flow = [Paragraph(esc(title), ST["title"])]
    if subtitle:
        flow.append(Paragraph(esc(subtitle), ST["subtitle"]))
    else:
        flow.append(Spacer(1, 6))

    mode = "action"
    for ln in _strip_md(text).split("\n"):
        s = ln.strip()
        if not s:
            mode = "action"
            continue
        if FC.episode_num(s) is not None:
            flow.append(Paragraph(esc(f"EPISODE {FC.episode_num(s)}"), ST["ep"]))
            mode = "action"; continue
        if FC._SCENE.match(s) or FC._SLUG.match(s) or s.upper().startswith("SCENE PROFILE") \
                or s.upper().startswith("SETTING:"):
            flow.append(Paragraph(esc(s.upper() if (FC._SCENE.match(s) or FC._SLUG.match(s)) else s),
                                  ST["scene"])); mode = "action"; continue
        if _TRANS.search(s) and len(s) < 30:
            flow.append(Paragraph(esc(s), ST["trans"])); mode = "action"; continue
        if _PAREN.match(s):
            flow.append(Paragraph(esc(s), ST["paren"])); mode = "dialogue"; continue
        if FC.is_cue(ln):
            flow.append(Paragraph(esc(s.upper()), ST["cue"])); mode = "dialogue"; continue
        flow.append(Paragraph(esc(s), ST["dlg" if mode == "dialogue" else "action"]))

    SimpleDocTemplate(str(out_pdf), pagesize=A4, leftMargin=1.0 * inch, rightMargin=0.9 * inch,
                      topMargin=0.9 * inch, bottomMargin=0.9 * inch, title=title).build(flow)
    return out_pdf


def run(task_id: str, merged_md: Path, merged_text: str, workdir: Path, show_title: str) -> dict:
    """Returns {'master_pdf', 'corrected_txt', 'report'}."""
    state.set_step(task_id, 4, "Formatting the master screenplay…", 68)

    corrected_txt = workdir / "Master_Screenplay_corrected.txt"
    # Deterministic check + auto-correct (numbering fixes; wording untouched).
    report = FC.run(str(merged_md), fix_path=str(corrected_txt))
    corrected = corrected_txt.read_text(encoding="utf-8")

    master_pdf = workdir / "Master_Screenplay.pdf"
    # Use the same Model-4 renderer as the standalone Formatter so the master
    # screenplay matches the validated house style / example outputs.
    from . import model4_formatter
    model4_formatter.render_pdf(corrected, str(master_pdf), f"{show_title} — Master Screenplay")

    # Also write the formatting report markdown (same format as the examples).
    report_md = workdir / "Master_Screenplay_format_report.md"
    after = FC.run(str(corrected_txt))
    model4_formatter.write_report(report, str(report_md), f"{show_title} — Master Screenplay", after=after)

    state.log(
        task_id,
        f"Step 4 complete — formatting {report['format_status']}, "
        f"{report['n_episodes']} episodes, readability {report['readability']}/5.",
    )
    return {"master_pdf": master_pdf, "corrected_txt": corrected_txt, "report_md": report_md,
            "corrected_text": corrected, "report": report}
