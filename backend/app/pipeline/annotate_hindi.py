"""Annotated Hindi Script (PDF) — the Hindi OG screenplay reproduced verbatim with:

  • a grey  ADAPTATION CHANGES  box  at the top of each episode (what the Hindi did differently)
  • a red   MISSING INFORMATION box  at the top of each episode (genuine story info never received)
  • GREEN INLINE HIGHLIGHT of the actual passages ADDED in the Hindi that aren't in the original
    (substantive additions that add information — NOT translated dialogue). No green box — the
    added text itself is highlighted where it appears in the script.

Rendered with reportlab.
"""
from __future__ import annotations

import re

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, KeepTogether)
from reportlab.lib.styles import ParagraphStyle

NAVY = colors.HexColor("#1F3864")
GREY = colors.HexColor("#555555")
RED = colors.HexColor("#B22222")
GREY_FILL = colors.HexColor("#F0F0F0")
RED_FILL = colors.HexColor("#FDECEA")
GREEN_HL = "#C6F6D5"          # inline highlight for added content

_SLUG = re.compile(r"^(Scene\s+\d+[^/]*/\s*)?(INT\.|EXT\.|INT\./EXT\.|MONTAGE)", re.I)
_SLUG2 = re.compile(r"^\d+(-\d+)?\s*/\s*(INT|EXT|MONTAGE)", re.I)
_EP = re.compile(r"^EPISODE\s+(\d+)\b", re.I)
_EP2 = re.compile(r"^EP\s*0?(\d+)\b", re.I)

S = {
    "title": ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=17, textColor=NAVY, spaceAfter=4, leading=21),
    "sub": ParagraphStyle("s", fontName="Helvetica", fontSize=10.5, textColor=GREY, spaceAfter=8, leading=14),
    "legend": ParagraphStyle("lg", fontName="Helvetica", fontSize=9.5, leading=14, spaceAfter=2, leftIndent=8),
    "ep": ParagraphStyle("ep", fontName="Helvetica-Bold", fontSize=14, textColor=NAVY, spaceBefore=6, spaceAfter=8, leading=17),
    "boxlabel": ParagraphStyle("bl", fontName="Helvetica-Bold", fontSize=9, leading=12, spaceAfter=2),
    "boxitem": ParagraphStyle("bi", fontName="Helvetica", fontSize=8.5, leading=11.5, leftIndent=6, textColor=colors.HexColor("#222222")),
    "slug": ParagraphStyle("sl", fontName="Helvetica-Bold", fontSize=10.5, textColor=NAVY, spaceBefore=8, spaceAfter=3, leading=14),
    "note": ParagraphStyle("nt", fontName="Helvetica-Oblique", fontSize=9, textColor=GREY, leftIndent=8, leading=12, spaceAfter=2),
    "cue": ParagraphStyle("cue", fontName="Helvetica-Bold", fontSize=10, leftIndent=1.7 * inch, spaceBefore=4, leading=12),
    "body": ParagraphStyle("bd", fontName="Helvetica", fontSize=10, leading=13.5, spaceAfter=4),
}


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _highlight(raw: str, spans: list[str]) -> str:
    """Return reportlab markup: `raw` escaped, with any `spans` wrapped in a green
    background. Matches are case-insensitive, non-overlapping, longest-first."""
    spans = [s for s in (spans or []) if s and len(s.strip()) >= 4]
    if not spans:
        return esc(raw)
    low = raw.lower()
    ranges: list[tuple[int, int]] = []
    for sp in sorted(set(spans), key=len, reverse=True):
        needle = sp.lower().strip()
        start = 0
        while True:
            i = low.find(needle, start)
            if i < 0:
                break
            j = i + len(needle)
            if not any(a < j and i < b for a, b in ranges):
                ranges.append((i, j))
            start = j
    if not ranges:
        return esc(raw)
    ranges.sort()
    out, pos = [], 0
    for a, b in ranges:
        if a < pos:
            continue
        out.append(esc(raw[pos:a]))
        out.append(f'<font backColor="{GREEN_HL}">' + esc(raw[a:b]) + "</font>")
        pos = b
    out.append(esc(raw[pos:]))
    return "".join(out)


def _box(label: str, label_hex: str, fill, items: list[str]):
    rows = [Paragraph(f'<font color="{label_hex}"><b>{esc(label)}</b></font>', S["boxlabel"])]
    for it in items:
        rows.append(Paragraph("•  " + esc(it), S["boxitem"]))
    tbl = Table([[rows]], colWidths=[6.2 * inch])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), fill),
        ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor(label_hex)),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return KeepTogether(tbl)


def _is_slug(l: str) -> bool:
    return bool(_SLUG.match(l) or _SLUG2.match(l))


def _is_cue(l: str) -> bool:
    if len(l) > 46:
        return False
    m = re.match(r"^([A-Z0-9][A-Z0-9 .,'’&/\-]*?)(\s*\([^)]*\))?$", l)
    if not m:
        return False
    name = m.group(1).strip()
    if len(name) < 2 or re.match(r"^(SETTING|SCENE PROFILE)", name):
        return False
    return bool(re.search(r"[A-Z]{2,}", name)) and name == name.upper()


def _starts_lower(l: str) -> bool:
    return bool(re.match(r"^[a-z'\"“(]", l))


def build(hindi_text: str, out_pdf: str, *, title: str, hindi_ann: dict[int, dict]) -> str:
    """hindi_ann: {episode: {'added_spans':[], 'gaps':[], 'changes':[]}}."""
    flow = [
        Paragraph(esc(title), S["title"]),
        Paragraph("Annotated Hindi Script — dialogue verbatim; adaptation notes per episode.", S["sub"]),
        Paragraph("<b>HOW TO READ THIS DOCUMENT</b>", S["legend"]),
        Paragraph('•  <font color="#555555"><b>ADAPTATION CHANGES</b></font> (grey box) — what the '
                  "Hindi did differently.", S["legend"]),
        Paragraph('•  <font color="#B22222"><b>MISSING INFORMATION</b></font> (red box) — genuine '
                  "story info a viewer never receives.", S["legend"]),
        Paragraph(f'•  <font backColor="{GREEN_HL}"><b>Green highlight</b></font> — content ADDED in '
                  "the Hindi that isn't in the original (not translated dialogue).", S["legend"]),
        Spacer(1, 8),
    ]

    lines = [ln.rstrip() for ln in hindi_text.split("\n")]
    started = False
    buf: list[str] = []
    cur_spans: list[str] = []

    def flush():
        nonlocal buf
        if buf:
            flow.append(Paragraph(_highlight(" ".join(buf).strip(), cur_spans), S["body"]))
            buf = []

    def start_episode(n: int):
        nonlocal started, cur_spans
        flush()
        started = True
        a = hindi_ann.get(n, {})
        cur_spans = a.get("added_spans") or []
        flow.append(Paragraph(f"Episode {n} (Hindi)", S["ep"]))
        flow.append(_box("ADAPTATION CHANGES", "#555555", GREY_FILL,
                         (a.get("changes") or []) or ["No notable changes."]))
        flow.append(Spacer(1, 4))
        flow.append(_box("MISSING INFORMATION", "#B22222", RED_FILL,
                         (a.get("gaps") or ["None — no information missing."])))
        flow.append(Spacer(1, 6))

    for raw in lines:
        l = raw.strip()
        m = _EP.match(l) or _EP2.match(l)
        if m:
            start_episode(int(m.group(1)))
            continue
        if not started or l == "":
            continue
        if re.match(r"^SCENE PROFILE$", l, re.I):
            flush(); continue
        if _is_slug(l):
            flush(); flow.append(Paragraph(esc(l), S["slug"])); continue
        if re.match(r"^SETTING:", l, re.I) or l.startswith("•"):
            flush(); flow.append(Paragraph(_highlight(l, cur_spans), S["note"])); continue
        if _is_cue(l):
            flush(); flow.append(Paragraph(esc(l), S["cue"])); continue
        if buf and _starts_lower(l):
            buf.append(l)
        else:
            flush(); buf = [l]
    flush()

    # No episode markers in the Hindi text → still surface annotations + highlight.
    if not started and hindi_ann:
        for n in sorted(hindi_ann):
            start_episode(n)
        flow.append(Paragraph(_highlight(hindi_text[:20000],
                    [s for a in hindi_ann.values() for s in (a.get("added_spans") or [])]), S["body"]))

    SimpleDocTemplate(out_pdf, pagesize=A4, leftMargin=0.9 * inch, rightMargin=0.9 * inch,
                      topMargin=0.9 * inch, bottomMargin=0.8 * inch, title=title).build(flow)
    return out_pdf
