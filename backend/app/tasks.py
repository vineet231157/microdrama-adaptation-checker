"""Celery tasks — the two entry points that do the heavy work off the request thread.

  • format_task    → standalone Formatter (Model 4)
  • pipeline_task  → the full 5-step Super Pipeline

Each task runs inside a unique UUID workspace under WORK_ROOT so concurrent
jobs never collide. Progress + artifacts are written to Redis via ``state`` and
streamed to the browser by the FastAPI SSE endpoint.
"""
from __future__ import annotations

import shutil
import traceback
from pathlib import Path

from . import state
from .celery_app import celery_app
from .config import settings
from .drive import DriveClient, folder_id_from_url
from .pipeline import (step1_srt, step2_screenplay, step3_merge,
                       step4_format, step5_evaluate)
from .pipeline.textextract import extract_text
from .zipper import zip_files


def _workdir(task_id: str) -> Path:
    d = settings.WORK_ROOT / task_id
    d.mkdir(parents=True, exist_ok=True)
    return d


# ═══════════════════════════════════════════════════════════════════════════
# OPTION 1 — Formatting Only (Model 4, standalone)
# ═══════════════════════════════════════════════════════════════════════════
@celery_app.task(bind=True, name="format_task")
def format_task(self, task_id: str, input_path: str, show_title: str = ""):
    wd = _workdir(task_id)
    try:
        from .pipeline import model4_formatter

        state.set_step(task_id, 1, "Formatting script…", 20)
        state.log(task_id, f"Formatting {Path(input_path).name}")

        # DOCX isn't handled by pdftotext, so convert it to a .txt the checker reads
        # directly. PDF and TXT are passed straight through (identical to the model).
        src = Path(input_path)
        if src.suffix.lower() == ".docx":
            text = extract_text(src)
            fmt_input = wd / f"{src.stem}.txt"
            fmt_input.write_text(text, encoding="utf-8")
        else:  # .pdf → pdftotext -layout ; .txt → read as-is
            fmt_input = src

        state.set_step(task_id, 1, "Checking + formatting…", 40)
        # Produces, in wd:  <base>_formatted.pdf, <base>_format_report.md, <base>_corrected.txt
        out = model4_formatter.run(str(fmt_input), outdir=str(wd))
        r = out["result"]
        state.log(task_id, f"Formatting {r['format_status']} · {r['n_episodes']} episodes · "
                           f"readability {r['readability']}/5.")
        files = [Path(out["pdf"]), Path(out["report"]), Path(out["corrected"])]

        # Stage 2 — director-ready enrichment (only if a key is set; NEVER fatal —
        # the fast formatted PDF is always delivered even if enrichment fails).
        if settings.GEMINI_API_KEY:
            try:
                from .pipeline import enrich_director_ready
                base = Path(out["pdf"]).stem.replace("_formatted", "")
                corrected = Path(out["corrected"]).read_text(encoding="utf-8")
                den = enrich_director_ready.run(task_id, corrected, wd,
                                                show_title or base.replace("_", " ").title(), base=base)
                files = [Path(den["director_pdf"]), Path(den["bible_md"])] + files
            except Exception as e:
                state.log(task_id, f"Director-ready enrichment skipped ({e}); "
                                   f"formatted PDF still delivered.", level="error")

        out_zip = wd / "Formatted.zip"
        zip_files(files, out_zip)
        state.add_artifact(task_id, "format_pdf",
                           f"{settings.PUBLIC_BASE_URL}/api/download/{task_id}/format")
        state.finish(task_id)
        state.log(task_id, "Done — formatted PDF + report ready to download.")
    except Exception as e:
        state.fail(task_id, str(e))
        state.log(task_id, traceback.format_exc(), level="error")
        raise


# ═══════════════════════════════════════════════════════════════════════════
# OPTION 2 — Full Adaptation Checker (the 5-step Super Pipeline)
# ═══════════════════════════════════════════════════════════════════════════
@celery_app.task(bind=True, name="pipeline_task")
def pipeline_task(self, task_id: str, drive_url: str, access_token: str,
                  hindi_script_path: str, show_title: str = "", max_episodes: int = 0):
    wd = _workdir(task_id)
    try:
        drive = DriveClient(access_token)
        source_folder_id = folder_id_from_url(drive_url)
        title = show_title.strip() or drive.folder_name(source_folder_id)
        state.update(task_id, show_title=title)
        state.log(task_id, f"Starting pipeline for “{title}”.")

        # ── STEP 1 — SRT extraction ────────────────────────────────────────
        s1 = step1_srt.run(task_id, drive, source_folder_id, wd)

        # ── STEP 2 — Screenplay generation ────────────────────────────────
        s2 = step2_screenplay.run(task_id, drive, source_folder_id, s1["srts"],
                                  title, wd, max_episodes=max_episodes)

        # ── STEP 3 — Merge ─────────────────────────────────────────────────
        s3 = step3_merge.run(task_id, s2["episodes"], wd, title)

        # ── STEP 4 — Format the master screenplay ──────────────────────────
        s4 = step4_format.run(task_id, s3["merged_md"], s3["merged_text"], wd, title)
        # Upload the master PDF to Drive (into the Screenplays folder).
        drive.upload(s4["master_pdf"], s4["master_pdf"].name, s2["folder_id"], "application/pdf")

        # ── STEP 5 — Adaptation evaluation ─────────────────────────────────
        s5 = step5_evaluate.run(task_id, hindi_script_path, s4["corrected_text"], wd, title)
        drive.upload(s5["report_pdf"], s5["report_pdf"].name, s2["folder_id"], "application/pdf")
        if s5.get("annotated_pdf"):
            drive.upload(s5["annotated_pdf"], Path(s5["annotated_pdf"]).name, s2["folder_id"],
                         "application/pdf")

        # ── Final bundle ───────────────────────────────────────────────────
        state.set_step(task_id, 5, "Packaging final deliverables…", 96)
        final_zip = wd / "Final_Deliverables.zip"
        final_files = [s4["master_pdf"], s4["report_md"], s5["report_pdf"], s5["report_json"]]
        if s5.get("annotated_pdf"):
            final_files.insert(0, s5["annotated_pdf"])
        zip_files(final_files, final_zip)
        state.add_artifact(task_id, "final_zip",
                           f"{settings.PUBLIC_BASE_URL}/api/download/{task_id}/final")

        state.finish(task_id)
        state.log(task_id, "🎉 Pipeline complete — all artifacts ready in the UI and on Drive.")
    except Exception as e:
        state.fail(task_id, str(e))
        state.log(task_id, traceback.format_exc(), level="error")
        raise
    finally:
        # Clean up any leftover video temp dir (screenplays/SRTs are kept for download).
        vids = wd / "_videos"
        if vids.exists():
            shutil.rmtree(vids, ignore_errors=True)
