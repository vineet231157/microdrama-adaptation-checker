"""Detached job runner for the Full Adaptation Checker.

The Streamlit UI spawns this as an INDEPENDENT background process
(`python job_runner.py --spec <job.json>`, in its own session). Because it is
detached, a 3–5 hour job keeps running even if the browser tab closes or the
Streamlit session ends. Progress is written to `<workdir>/status.json` (which
the UI polls) and all results are written to Google Drive + local ZIPs.

Run manually (e.g. to debug):
    GEMINI_API_KEY=... python job_runner.py --spec /path/to/job.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

# ── make the backend package importable (same logic as streamlit_app.py) ─────
_HERE = Path(__file__).resolve().parent
BACKEND = _HERE.parents[0] / "backend"
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(BACKEND))

import app.state as state  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════
# File-based state — replaces the Redis-backed progress store with a status.json
# that the Streamlit UI reads. Monkeypatches the same functions the pipeline
# steps call, so no step code changes.
# ═══════════════════════════════════════════════════════════════════════════
class FileState:
    def __init__(self, status_path: Path, base: dict):
        self.path = status_path
        self.data = base

    def _flush(self):
        self.data["updated_at"] = time.time()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)  # atomic — the UI never reads a half-written file

    def set_step(self, task_id, step, label, percent):
        self.data.update(status="running", step=step, step_label=label, percent=percent)
        self._flush()

    def log(self, task_id, msg, level="info"):
        self.data.setdefault("log", []).append(
            {"ts": round(time.time(), 2), "level": level, "msg": str(msg)}
        )
        self.data["log"] = self.data["log"][-500:]
        self._flush()

    def add_artifact(self, task_id, name, url):
        self.data.setdefault("artifacts", {})[name] = url
        self._flush()

    def set_drive_link(self, task_id, name, url):
        if url and url.startswith("https://drive.google.com"):
            self.data.setdefault("drive", {})[name] = url
            self._flush()

    def finish(self, task_id):
        self.data.update(status="done", percent=100, step_label="Complete")
        self._flush()

    def fail(self, task_id, error):
        self.data.update(status="error", step_label="Failed", error=error)
        self._flush()


def install_file_state(fs: FileState):
    state.set_step = fs.set_step
    state.log = fs.log
    state.add_artifact = fs.add_artifact
    state.set_drive_link = fs.set_drive_link
    state.finish = fs.finish
    state.fail = fs.fail
    state.create = lambda *a, **k: None
    state.update = lambda *a, **k: None
    state.get = lambda tid: None


# ═══════════════════════════════════════════════════════════════════════════
def build_source(spec: dict, wd: Path):
    """Return (source, source_folder_id, resolved_title)."""
    if spec["source"] == "local":
        from local_source import LocalSource
        vids_dir = Path(spec["videos_dir"])
        source = LocalSource(vids_dir, wd / "_local_out")
        return source, str(vids_dir), spec.get("title") or "Uploaded Show"
    # drive
    from app.drive import DriveClient, folder_id_from_url
    sa_info = json.loads(Path(spec["sa_json_path"]).read_text(encoding="utf-8"))
    source = DriveClient.from_service_account_info(sa_info)
    fid = folder_id_from_url(spec["drive_url"])
    return source, fid, (spec.get("title") or source.folder_name(fid))


def run(spec: dict, wd: Path, fs: FileState):
    from app.pipeline import (step1_srt, step2_screenplay, step3_merge,
                              step4_format, step5_evaluate)
    from app.zipper import zip_files

    task_id = spec["job_id"]
    source, source_folder_id, title = build_source(spec, wd)
    fs.data["show_title"] = title
    fs.log(task_id, f"Starting pipeline for “{title}”.")

    s1 = step1_srt.run(task_id, source, source_folder_id, wd)
    s2 = step2_screenplay.run(task_id, source, source_folder_id, s1["srts"],
                              title, wd, max_episodes=int(spec.get("max_episodes", 0)))
    s3 = step3_merge.run(task_id, s2["episodes"], wd, title)
    s4 = step4_format.run(task_id, s3["merged_md"], s3["merged_text"], wd, title)
    source.upload(s4["master_pdf"], s4["master_pdf"].name, s2["folder_id"], "application/pdf")
    s5 = step5_evaluate.run(task_id, spec["hindi_path"], s4["corrected_text"], wd, title)
    source.upload(s5["report_pdf"], s5["report_pdf"].name, s2["folder_id"], "application/pdf")

    fs.set_step(task_id, 5, "Packaging final deliverables…", 96)
    zip_files([s4["master_pdf"], s4["report_md"], s5["report_pdf"], s5["report_json"]],
              wd / "Final_Deliverables.zip")
    fs.add_artifact(task_id, "final_zip", "Final_Deliverables.zip")
    fs.finish(task_id)
    fs.log(task_id, "🎉 Pipeline complete — all artifacts ready (UI + Google Drive).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True, help="path to the job spec JSON")
    args = ap.parse_args()

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    wd = Path(spec["workdir"])
    wd.mkdir(parents=True, exist_ok=True)
    status_path = wd / "status.json"

    fs = FileState(status_path, {
        "job_id": spec["job_id"], "mode": "pipeline", "status": "running",
        "step": 0, "step_label": "Starting…", "percent": 0,
        "show_title": spec.get("title", ""), "log": [], "artifacts": {},
        "drive": {}, "error": None, "started_at": time.time(),
    })
    install_file_state(fs)

    try:
        run(spec, wd, fs)
    except Exception as e:
        fs.fail(spec["job_id"], str(e))
        fs.log(spec["job_id"], traceback.format_exc(), level="error")
        sys.exit(1)


if __name__ == "__main__":
    main()
