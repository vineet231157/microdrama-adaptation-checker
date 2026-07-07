#!/usr/bin/env python3
"""
Render the enriched, director-ready screenplay markup into a styled PDF
(Scene-Profile blocks + grounded action + bracketed emotional cues).

Markup line prefixes (one per line):
  @EP|<episode header>            episode title bar (teal)
  @SC|<scene heading>             scene slug
  @PB                             begin SCENE PROFILE block
  @SET|<setting line>             setting line inside a profile
  @CH|<character profile line>    one character inside a profile
  @SU|<state update line>         a short state-update note (mid-episode)
  @PE                             end SCENE PROFILE block
  @AC|<action>                    action / description (left aligned)
  @CUE|<NAME (cue)>               character cue (bold, indented)
  @DL|<dialogue>                  dialogue (indented block)
  @TR|<transition>                transition (right aligned)
Lines that are blank or start with '#' are ignored.

Ported from the v1 model's render_director_ready.py; adds build_from_text() so
callers can render a markup string without writing a temp file.
"""
from __future__ import annotations

import sys

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_RIGHT, TA_CENTER
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, KeepTogether)
from reportlab.lib.styles import ParagraphStyle

TEAL = colors.HexColor("#0f766e")
TEAL_BG = colors.HexColor("#ecfdf5")
TEAL_LINE = colors.HexColor("#99f6e4")
GREY = colors.HexColor("#475569")

ST = {
    "title": ParagraphStyle("title", fontName="Courier-Bold", fontSize=20, alignment=TA_CENTER, spaceAfter=4, leading=24),
    "subtitle": ParagraphStyle("subtitle", fontName="Courier", fontSize=10, alignment=TA_CENTER, textColor=GREY, spaceAfter=14, leading=13),
    "ep": ParagraphStyle("ep", fontName="Courier-Bold", fontSize=14, spaceBefore=20, spaceAfter=8, leading=17, textColor=colors.white, backColor=TEAL, borderPadding=(5, 6, 5, 6)),
    "scene": ParagraphStyle("scene", fontName="Courier-Bold", fontSize=11, spaceBefore=12, spaceAfter=4, leading=14, textColor=colors.HexColor("#0f172a")),
    "prof_label": ParagraphStyle("prof_label", fontName="Courier-Bold", fontSize=8.5, textColor=TEAL, spaceAfter=3, leading=11),
    "prof_set": ParagraphStyle("prof_set", fontName="Courier-Bold", fontSize=9, textColor=colors.HexColor("#0f172a"), leading=12, spaceAfter=3),
    "prof_ch": ParagraphStyle("prof_ch", fontName="Courier", fontSize=9, textColor=colors.HexColor("#334155"), leading=12, leftIndent=6, spaceAfter=2),
    "su": ParagraphStyle("su", fontName="Courier-Oblique", fontSize=9, textColor=TEAL, leading=12, spaceBefore=4, spaceAfter=4),
    "action": ParagraphStyle("action", fontName="Courier", fontSize=10.5, spaceAfter=5, leading=13.5),
    "cue": ParagraphStyle("cue", fontName="Courier-Bold", fontSize=10.5, leftIndent=2.2 * inch, spaceBefore=4, leading=12),
    "dlg": ParagraphStyle("dlg", fontName="Courier", fontSize=10.5, leftIndent=1.2 * inch, rightIndent=1.0 * inch, spaceAfter=3, leading=12.5),
    "trans": ParagraphStyle("trans", fontName="Courier-Bold", fontSize=10.5, alignment=TA_RIGHT, textColor=GREY, spaceBefore=4, spaceAfter=8, leading=13),
}


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _flowables(lines):
    flow, prof_rows = [], None
    for ln in lines:
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        if "|" in ln:
            tag, _, body = ln.partition("|")
        else:
            tag, body = ln.strip(), ""
        tag, body = tag.strip(), body.strip()
        if tag == "@PB":
            prof_rows = [Paragraph("SCENE PROFILE", ST["prof_label"])]
            continue
        if tag == "@SET" and prof_rows is not None:
            prof_rows.append(Paragraph("<b>SETTING:</b> " + esc(body), ST["prof_set"]))
            continue
        if tag == "@CH" and prof_rows is not None:
            prof_rows.append(Paragraph("• " + esc(body), ST["prof_ch"]))
            continue
        if tag == "@PE":
            if prof_rows:
                tbl = Table([[prof_rows]], colWidths=[6.0 * inch])
                tbl.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), TEAL_BG),
                    ("BOX", (0, 0), (-1, -1), 0.75, TEAL_LINE),
                    ("LEFTPADDING", (0, 0), (-1, -1), 9),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]))
                flow.append(Spacer(1, 3))
                flow.append(KeepTogether(tbl))
                flow.append(Spacer(1, 5))
            prof_rows = None
            continue
        if tag == "@EP":
            flow.append(Paragraph(esc(body), ST["ep"]))
        elif tag == "@SC":
            flow.append(Paragraph(esc(body), ST["scene"]))
        elif tag == "@SU":
            flow.append(Paragraph("STATE UPDATE — " + esc(body), ST["su"]))
        elif tag == "@AC":
            flow.append(Paragraph(esc(body), ST["action"]))
        elif tag == "@CUE":
            flow.append(Paragraph(esc(body), ST["cue"]))
        elif tag == "@DL":
            flow.append(Paragraph(esc(body), ST["dlg"]))
        elif tag == "@TR":
            flow.append(Paragraph(esc(body), ST["trans"]))
    return flow


def build_from_text(markup: str, out_pdf: str, title: str, subtitle: str = "") -> str:
    flow = [Paragraph(esc(title), ST["title"])]
    if subtitle:
        flow.append(Paragraph(esc(subtitle), ST["subtitle"]))
    flow.extend(_flowables(markup.split("\n")))
    SimpleDocTemplate(out_pdf, pagesize=A4, leftMargin=1.1 * inch, rightMargin=0.9 * inch,
                      topMargin=0.9 * inch, bottomMargin=0.8 * inch, title=title).build(flow)
    return out_pdf


def build(markup_path: str, out_pdf: str, title: str, subtitle: str = "") -> str:
    with open(markup_path, encoding="utf-8") as f:
        return build_from_text(f.read(), out_pdf, title, subtitle)


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2],
          sys.argv[3] if len(sys.argv) > 3 else "Screenplay",
          sys.argv[4] if len(sys.argv) > 4 else "")
