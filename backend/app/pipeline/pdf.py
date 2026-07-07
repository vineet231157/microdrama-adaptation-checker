"""Per-episode / generic screenplay-text → PDF (CJK-safe).

Ported from ``video_to_screenplay_pipeline.ipynb``'s ``text_to_pdf``. The
director-ready master PDF is rendered separately by ``step4_format`` using the
richer Model-4 renderer.
"""
from __future__ import annotations

import re
from pathlib import Path


def text_to_pdf(text: str, pdf_path: str | Path, title: str) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    pdf_path = str(pdf_path)
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))  # CJK-safe + Latin
    doc = SimpleDocTemplate(pdf_path, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=2 * cm, bottomMargin=2 * cm)
    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["Normal"], fontName="STSong-Light", fontSize=10, leading=14)
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontName="STSong-Light", fontSize=15,
                        leading=19, spaceBefore=16, spaceAfter=8)
    slug = ParagraphStyle("sl", parent=ss["Heading2"], fontName="STSong-Light", fontSize=11,
                          leading=15, spaceBefore=10, spaceAfter=4)

    def esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    flow = [Paragraph(esc(title), h1), Spacer(1, 6)]
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            flow.append(Spacer(1, 5))
            continue
        st = h1 if re.match(r"^EPISODE\s+\d+", s) else (
            slug if re.match(r"^(INT\.|EXT\.|MONTAGE|SCENE PROFILE|SETTING:)", s) else body)
        flow.append(Paragraph(esc(line), st))
    doc.build(flow)
    return Path(pdf_path)
