#!/usr/bin/env python3
"""
=============================================================================
FORMATTING MODEL — micro-drama script formatter (extract → check → correct →
                   formatted PDF + report)
=============================================================================
ONE command does everything:

    python formatting_model.py "MyScript.pdf"

It produces, next to the input:
    <name>_formatted.pdf      — the cleaned, re-typeset script (headers fixed,
                                missing Episode 1 inserted, scenes renumbered)
    <name>_format_report.md   — the formatting report: status, readability, the
                                exact long-dialogue locations, action walls,
                                emotion-as-action lines, runtime flags, and the
                                recommended changes
    <name>_corrected.txt      — the corrected script as plain text

PIPELINE (same backbone as the earlier grading model)
  1. EXTRACT      pdftotext -layout  (identical extraction to the earlier model)
  2. SEGMENT+COUNT split into episodes/scenes/dialogue/action and COUNT words —
                   this is how the model locates where the issue lies
  3. CHECK        the 6 formatting rules (hardened against false positives)
  4. CORRECT      auto-fix episode/scene numbering & headers (never the wording)
  5. OUTPUT       render the formatted PDF + write the report

Requires:  format_check.py (in this folder), Python 3, reportlab (`pip install
reportlab`), and poppler's `pdftotext` for PDFs (`.txt` scripts need neither).
=============================================================================
"""
from __future__ import annotations
import os, sys, argparse
from . import format_check as FC   # the hardened checker + extractor + auto-corrector


# ── PDF rendering (clean screenplay layout) ──────────────────────────────────
def render_pdf(text, out_pdf, title):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import ParagraphStyle
    import re
    ST = {
        "title": ParagraphStyle("title", fontName="Courier-Bold", fontSize=18, alignment=TA_CENTER, spaceAfter=8, leading=22),
        "ep":    ParagraphStyle("ep", fontName="Courier-Bold", fontSize=13, spaceBefore=16, spaceAfter=6, leading=16, textColor="#0f766e"),
        "scene": ParagraphStyle("scene", fontName="Courier-Bold", fontSize=11, spaceBefore=8, spaceAfter=4, leading=14),
        "action":ParagraphStyle("action", fontName="Courier", fontSize=10.5, spaceAfter=5, leading=13),
        "cue":   ParagraphStyle("cue", fontName="Courier-Bold", fontSize=10.5, leftIndent=2.2*inch, spaceBefore=3, leading=12),
        "dlg":   ParagraphStyle("dlg", fontName="Courier", fontSize=10.5, leftIndent=1.2*inch, rightIndent=1.0*inch, spaceAfter=3, leading=12),
        "trans": ParagraphStyle("trans", fontName="Courier-Bold", fontSize=10.5, alignment=TA_RIGHT, spaceBefore=3, spaceAfter=6, leading=13),
    }
    _TRANS = re.compile(r"(TO:|FRAME\.?|FREEZE\.?|FADE (IN|OUT))\s*$", re.I)
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    flow = [Paragraph(esc(title), ST["title"]), Spacer(1, 6)]
    mode = "action"
    for ln in text.split("\n"):
        s = ln.strip()
        if not s:
            mode = "action"; continue
        if FC.episode_num(s) is not None:
            flow.append(Paragraph(esc(s), ST["ep"])); mode = "action"; continue
        if FC._SCENE.match(s) or FC._SLUG.match(s):
            flow.append(Paragraph(esc(s), ST["scene"])); mode = "action"; continue
        if _TRANS.search(s) and len(s) < 30:
            flow.append(Paragraph(esc(s), ST["trans"])); mode = "action"; continue
        if FC.is_cue(ln):
            flow.append(Paragraph(esc(s), ST["cue"])); mode = "dialogue"; continue
        flow.append(Paragraph(esc(s), ST["dlg" if mode == "dialogue" else "action"]))
    SimpleDocTemplate(out_pdf, pagesize=A4, leftMargin=1.2*inch, rightMargin=0.9*inch,
                      topMargin=0.9*inch, bottomMargin=0.9*inch, title=title).build(flow)


# ── report (markdown) ────────────────────────────────────────────────────────
def write_report(result, out_md, name, after=None):
    L = [f"# Formatting Report — {name}", "",
         f"**Input status:** {result['format_status']}  ·  **Readability:** {result['readability']}/5  ·  "
         f"**Episodes:** {result['n_episodes']}", ""]
    if after is not None:
        L += [f"**After auto-correction (the formatted PDF):** {after['format_status']}  ·  "
              f"readability {after['readability']}/5", ""]
    L += [f"> {result['summary']}", ""]
    for c in result["checks"]:
        L.append(f"### {c['check']} — {c['status']}")
        L.append(f"{c['detail']}")
        L.append(f"*Recommendation:* {c['recommendation']}")
        items = c.get("items", [])
        if items:
            if c["check"] == "Dialogue length":
                L.append("\n| Episode | Scene | Character | Lines | Excerpt |\n|---|---|---|---|---|")
                for it in items:
                    ex = it.get("excerpt", "").replace("|", "/")[:80]
                    L.append(f"| {it.get('episode')} | {it.get('scene')} | {it.get('character','')} | "
                             f"{it.get('n_lines')} | {ex} |")
            else:
                for it in items[:20]:
                    loc = f"Ep{it.get('episode')}/Sc{it.get('scene')}"
                    L.append(f"- {loc}: \"{it.get('excerpt','')[:90]}\"")
        L.append("")
    L.append("---")
    L.append("**Auto-corrected in the PDF:** episode headers normalised to `EPISODE N`, a missing "
             "`EPISODE 1` inserted if needed, and scene numbers restarted per episode. Dialogue / "
             "action wording was **not** changed — those items above are recommendations for the writer.")
    open(out_md, "w", encoding="utf-8").write("\n".join(L))


# ── orchestrator ─────────────────────────────────────────────────────────────
def run(path, outdir=None):
    base = os.path.splitext(os.path.basename(path))[0]
    outdir = outdir or os.path.dirname(os.path.abspath(path))
    pdf = os.path.join(outdir, f"{base}_formatted.pdf")
    rep = os.path.join(outdir, f"{base}_format_report.md")
    txt = os.path.join(outdir, f"{base}_corrected.txt")

    # 1-4: extract + segment/count + check + auto-correct (all inside FC.run)
    result = FC.run(path, fix_path=txt)
    # 5: outputs
    corrected = open(txt, encoding="utf-8").read()
    render_pdf(corrected, pdf, base.replace("_", " ").title())
    after = FC.run(txt)                       # status of the corrected text (shows it's fixed)
    write_report(result, rep, base, after=after)

    FC.print_report(result)
    print(f"\n  → formatted PDF : {pdf}")
    print(f"  → report (md)   : {rep}")
    print(f"  → corrected txt : {txt}")
    return {"pdf": pdf, "report": rep, "corrected": txt, "result": result}


def main():
    ap = argparse.ArgumentParser(description="Micro-drama formatting model (PDF + report)")
    ap.add_argument("path", help="script .pdf or .txt")
    ap.add_argument("--outdir", default=None, help="where to write outputs (default: next to input)")
    args = ap.parse_args()
    run(args.path, args.outdir)


if __name__ == "__main__":
    main()
