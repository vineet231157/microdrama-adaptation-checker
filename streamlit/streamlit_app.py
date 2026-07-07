"""
Microdrama Adaptation Checker — Streamlit front-end.

A single-process alternative to the Next.js + FastAPI + Celery stack. It reuses
the EXACT same pipeline modules (app.pipeline.step1..step5); it just runs them
inline and streams progress into Streamlit widgets instead of Redis + SSE.

Two modes:
  • Formatting Only        — upload a script → formatted screenplay PDF (Model 4)
  • Full Adaptation Checker — videos (drag-drop OR Drive) + Hindi script → SRTs,
                              screenplays, master PDF, and an evaluation report.

Run:  streamlit run streamlit_app.py
"""
from __future__ import annotations

import json
import sys
import traceback
import uuid
from pathlib import Path

import streamlit as st

# ── make the backend package importable ─────────────────────────────────────
# Insert the streamlit dir first (for local_source), then BACKEND at index 0 so
# the `app` package resolves to backend/app (the entry file is streamlit_app.py,
# so there is no name collision with the `app` package).
_HERE = Path(__file__).resolve().parent
BACKEND = _HERE.parents[0] / "backend"
sys.path.insert(0, str(_HERE))          # for `local_source`
sys.path.insert(0, str(BACKEND))        # ends up first → `app.*` resolves here

from app.config import settings          # noqa: E402
import app.state as state                # noqa: E402

st.set_page_config(page_title="Microdrama Adaptation Checker", page_icon="🎬", layout="wide")


# ═══════════════════════════════════════════════════════════════════════════
# Redirect the pipeline's Redis-backed progress calls into live Streamlit UI.
# The step modules call state.set_step/log/add_artifact/set_drive_link at run
# time, so monkeypatching these module attributes is enough — no Redis needed.
# ═══════════════════════════════════════════════════════════════════════════
class _UI:
    progress = None
    caption = None
    logbox = None
    lines: list[str] = []


def _set_step(task_id, step, label, percent):
    if _UI.progress is not None:
        _UI.progress.progress(min(max(percent, 0), 100) / 100.0)
    if _UI.caption is not None:
        _UI.caption.markdown(f"**Step {step}/5 — {label}**")


def _log(task_id, msg, level="info"):
    prefix = "❌ " if level == "error" else ""
    _UI.lines.append(prefix + str(msg))
    if _UI.logbox is not None:
        _UI.logbox.code("\n".join(_UI.lines[-300:]), language="log")


def _add_artifact(task_id, name, url):
    st.session_state.setdefault("_artifacts", set()).add(name)


def _set_drive_link(task_id, name, url):
    if url and url.startswith("https://drive.google.com"):
        st.session_state.setdefault("_drive", {})[name] = url


def _noop(*a, **k):
    return None


state.set_step = _set_step
state.log = _log
state.add_artifact = _add_artifact
state.set_drive_link = _set_drive_link
state.create = _noop
state.update = _noop
state.finish = _noop
state.fail = _noop
state.get = lambda tid: None


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════
def _workdir(task_id: str) -> Path:
    d = settings.WORK_ROOT / task_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_upload(uploaded, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(uploaded.getbuffer())
    return dest


def _fresh_run_state():
    _UI.lines = []
    st.session_state["_artifacts"] = set()
    st.session_state["_drive"] = {}


def _download_button(label: str, path: Path, mime="application/zip"):
    if path.exists():
        st.download_button(label, data=path.read_bytes(), file_name=path.name, mime=mime)


# ═══════════════════════════════════════════════════════════════════════════
# Pipeline runners (synchronous — mirror app.tasks but inline)
# ═══════════════════════════════════════════════════════════════════════════
def run_full_pipeline(source, source_folder_id, hindi_path, title, max_episodes):
    from app.pipeline import (step1_srt, step2_screenplay, step3_merge,
                              step4_format, step5_evaluate)
    from app.zipper import zip_files

    task_id = uuid.uuid4().hex
    wd = _workdir(task_id)

    s1 = step1_srt.run(task_id, source, source_folder_id, wd)
    s2 = step2_screenplay.run(task_id, source, source_folder_id, s1["srts"],
                              title, wd, max_episodes=max_episodes)
    s3 = step3_merge.run(task_id, s2["episodes"], wd, title)
    s4 = step4_format.run(task_id, s3["merged_md"], s3["merged_text"], wd, title)
    source.upload(s4["master_pdf"], s4["master_pdf"].name, s2["folder_id"], "application/pdf")
    s5 = step5_evaluate.run(task_id, hindi_path, s4["corrected_text"], wd, title)
    source.upload(s5["report_pdf"], s5["report_pdf"].name, s2["folder_id"], "application/pdf")

    zip_files([s4["master_pdf"], s5["report_pdf"], s5["report_json"]],
              wd / "Final_Deliverables.zip")
    _set_step(task_id, 5, "Complete", 100)
    return {"id": task_id, "wd": str(wd), "mode": "pipeline", "title": title,
            "eval": s5["data"], "drive": dict(st.session_state.get("_drive", {}))}


def run_format(uploaded, title):
    from app.pipeline import step4_format
    from app.pipeline.textextract import extract_text
    from app.zipper import zip_files

    task_id = uuid.uuid4().hex
    wd = _workdir(task_id)
    src = _save_upload(uploaded, wd / uploaded.name)
    title = title or src.stem.replace("_", " ").title()

    if src.suffix.lower() in (".docx", ".txt"):
        text = extract_text(src)
        md_path = wd / f"{src.stem}.md"
        md_path.write_text(text, encoding="utf-8")
        merged_text = text
    else:  # PDF — format_check extracts via pdftotext internally
        md_path, merged_text = src, ""

    result = step4_format.run(task_id, md_path, merged_text, wd, title)
    zip_files([result["master_pdf"], result["corrected_txt"]], wd / "Formatted.zip")
    _set_step(task_id, 4, "Complete", 100)
    return {"id": task_id, "wd": str(wd), "mode": "format", "title": title,
            "report": result["report"]}


# ═══════════════════════════════════════════════════════════════════════════
# Results renderer (survives download-button reruns via session_state)
# ═══════════════════════════════════════════════════════════════════════════
def render_results(res: dict):
    wd = Path(res["wd"])
    st.success(f"✅ Done — “{res['title']}”")

    if res["mode"] == "format":
        rep = res.get("report", {})
        c1, c2, c3 = st.columns(3)
        c1.metric("Formatting", rep.get("format_status", "—"))
        c2.metric("Episodes", rep.get("n_episodes", "—"))
        c3.metric("Readability", f"{rep.get('readability','—')}/5")
        _download_button("⬇️ Download Formatted Script (ZIP)", wd / "Formatted.zip")
        return

    ev = res.get("eval", {})
    c1, c2, c3 = st.columns(3)
    c1.metric("Overall verdict", ev.get("overall_verdict", "—"))
    c2.metric("Score", f"{ev.get('overall_score','—')}/100")
    c3.metric("Genuine gaps", len(ev.get("information_gaps", []) or []))
    if ev.get("summary"):
        st.info(ev["summary"])

    st.subheader("Deliverables")
    cols = st.columns(3)
    with cols[0]:
        _download_button("⬇️ SRTs (ZIP)", wd / "SRT_Files.zip")
    with cols[1]:
        _download_button("⬇️ Individual Screenplays (ZIP)", wd / "Screenplays.zip")
    with cols[2]:
        _download_button("⬇️ Master + Evaluation (ZIP)", wd / "Final_Deliverables.zip")

    drive = res.get("drive", {})
    if drive:
        st.caption("On Google Drive:")
        for name, url in drive.items():
            st.markdown(f"- [{name.replace('_',' ').title()}]({url})")


# ═══════════════════════════════════════════════════════════════════════════
# Sidebar — configuration
# ═══════════════════════════════════════════════════════════════════════════
st.sidebar.title("⚙️ Configuration")
gemini_key = st.sidebar.text_input(
    "Gemini API key", type="password",
    value=settings.GEMINI_API_KEY, help="Used for screenplay generation + evaluation.",
)
if gemini_key:
    settings.GEMINI_API_KEY = gemini_key
settings.GEMINI_MODEL = st.sidebar.selectbox(
    "Gemini model", ["gemini-1.5-pro", "gemini-2.5-pro", "gemini-2.0-flash", "gemini-1.5-flash"],
    index=0,
)
settings.OCR_USE_GPU = st.sidebar.toggle("Use GPU for OCR", value=settings.OCR_USE_GPU,
                                         help="Enable only on a CUDA host.")
st.sidebar.divider()
st.sidebar.caption("Tip: on Streamlit Cloud, put GEMINI_API_KEY in **Secrets** and it "
                   "auto-fills above.")

# Streamlit Cloud secrets → env
if not gemini_key and "GEMINI_API_KEY" in st.secrets:
    settings.GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════
st.title("🎬 Microdrama Adaptation Checker")
st.caption("Chinese microdrama → Hindi director-ready screenplay, end to end.")

# Re-render last results if present (keeps downloads alive across reruns).
if "last_result" in st.session_state:
    render_results(st.session_state["last_result"])
    if st.button("Start a new job"):
        del st.session_state["last_result"]
        st.rerun()
    st.stop()

tab_pipeline, tab_format = st.tabs(["🚀 Full Adaptation Checker", "✨ Formatting Only"])

# ── Full pipeline ────────────────────────────────────────────────────────────
with tab_pipeline:
    st.write("Videos + your Hindi OG script → SRTs, screenplays, master PDF, and an "
             "adaptation-review report.")
    src_mode = st.radio("Video source", ["Upload video files", "Google Drive folder"],
                        horizontal=True)

    videos = drive_url = sa_info = None
    if src_mode == "Upload video files":
        videos = st.file_uploader("Episode videos (.mp4/.mkv/.mov)",
                                  type=["mp4", "mkv", "mov", "webm", "avi"],
                                  accept_multiple_files=True)
    else:
        drive_url = st.text_input("Google Drive folder link (raw videos)")
        sa_file = st.file_uploader("Service-account key (JSON)", type=["json"],
                                   help="Share the Drive folder with the service account's "
                                        "client_email so it can read videos + write results.")
        if sa_file:
            sa_info = json.loads(sa_file.getvalue().decode("utf-8"))

    col1, col2 = st.columns(2)
    title = col1.text_input("Show title (optional)")
    max_eps = col2.number_input("Max episodes (0 = all)", min_value=0, value=0, step=1)
    hindi = st.file_uploader("Hindi OG script (PDF / DOCX / TXT)", type=["pdf", "docx", "txt"])

    if st.button("▶️ Start Full Pipeline", type="primary"):
        if not settings.GEMINI_API_KEY:
            st.error("Enter your Gemini API key in the sidebar.")
        elif not hindi:
            st.error("Upload the Hindi OG script.")
        elif src_mode == "Upload video files" and not videos:
            st.error("Upload at least one video file.")
        elif src_mode == "Google Drive folder" and not (drive_url and sa_info):
            st.error("Provide the Drive link and the service-account JSON.")
        else:
            _fresh_run_state()
            _UI.caption = st.empty()
            _UI.progress = st.progress(0.0)
            with st.expander("Live log", expanded=True):
                _UI.logbox = st.empty()
            try:
                task_id = uuid.uuid4().hex
                wd = _workdir(task_id)
                hindi_path = str(_save_upload(hindi, wd / hindi.name))

                if src_mode == "Upload video files":
                    from local_source import LocalSource
                    vids_dir = wd / "_input_videos"
                    vids_dir.mkdir(parents=True, exist_ok=True)
                    for v in videos:
                        _save_upload(v, vids_dir / v.name)
                    source = LocalSource(vids_dir, wd / "_local_out")
                    source_folder_id = str(vids_dir)
                    show_title = title or "Uploaded Show"
                else:
                    from app.drive import DriveClient, folder_id_from_url
                    source = DriveClient.from_service_account_info(sa_info)
                    source_folder_id = folder_id_from_url(drive_url)
                    show_title = title or source.folder_name(source_folder_id)

                with st.spinner("Running the 5-step pipeline… (this can take a while)"):
                    res = run_full_pipeline(source, source_folder_id, hindi_path,
                                            show_title, int(max_eps))
                st.session_state["last_result"] = res
                st.rerun()
            except Exception as e:
                st.error(f"Pipeline failed: {e}")
                st.code(traceback.format_exc())

# ── Formatting only ────────────────────────────────────────────────────────
with tab_format:
    st.write("Upload an unformatted script — get a cleanly formatted screenplay PDF "
             "(deterministic, no AI).")
    f_title = st.text_input("Title (optional)", key="fmt_title")
    f_file = st.file_uploader("Script (PDF / DOCX / TXT)", type=["pdf", "docx", "txt"],
                              key="fmt_file")
    if st.button("✨ Format Script", type="primary"):
        if not f_file:
            st.error("Upload a script file.")
        else:
            _fresh_run_state()
            _UI.caption = st.empty()
            _UI.progress = st.progress(0.0)
            with st.expander("Live log", expanded=True):
                _UI.logbox = st.empty()
            try:
                with st.spinner("Formatting…"):
                    res = run_format(f_file, f_title)
                st.session_state["last_result"] = res
                st.rerun()
            except Exception as e:
                st.error(f"Formatting failed: {e}")
                st.code(traceback.format_exc())
