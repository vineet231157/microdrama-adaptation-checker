"""
Microdrama Adaptation Checker — Streamlit front-end.

- **Formatting Only** runs INLINE and is fast (deterministic, no AI). Produces
  the same 3 files as the notebook: <name>_formatted.pdf, _format_report.md,
  _corrected.txt.
- **Full Adaptation Checker** submits the job to a DETACHED background process
  (job_runner.py). A 3–5 hour job keeps running even if you close the tab; it
  writes results to Google Drive (SRT_Files/ + Screenplays/ folders) and to
  local ZIPs. The **My Jobs** tab polls progress and serves the downloads.

Run:  streamlit run streamlit_app.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import streamlit as st

# ── make the backend package importable ─────────────────────────────────────
_HERE = Path(__file__).resolve().parent
BACKEND = _HERE.parents[0] / "backend"
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(BACKEND))

import importlib.util  # noqa: E402

from app.config import settings  # noqa: E402

st.set_page_config(page_title="Microdrama Adaptation Checker", page_icon="🎬", layout="wide")

# The subtitle-OCR stack (Step 1) is heavy and only installed in the Docker image.
# On Streamlit Community Cloud it's absent — Formatting / screenplay / eval still work.
OCR_AVAILABLE = (importlib.util.find_spec("cv2") is not None
                 and importlib.util.find_spec("paddleocr") is not None)

PIPELINE_STEPS = ["SRT extraction", "Screenplay", "Merge", "Format", "Evaluation"]
ZIP_LABELS = [
    ("SRT_Files.zip", "⬇️ SRTs (ZIP)"),
    ("Screenplays.zip", "⬇️ Individual Screenplays (ZIP)"),
    ("Final_Deliverables.zip", "⬇️ Master + Evaluation (ZIP)"),
]


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════
def workdir(job_id: str) -> Path:
    d = settings.WORK_ROOT / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_upload(uploaded, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(uploaded.getbuffer())
    return dest


def launch_detached_job(spec: dict):
    """Write the spec and spawn job_runner.py as an independent process."""
    wd = Path(spec["workdir"])
    spec_path = wd / "job.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    env = {
        **os.environ,
        "GEMINI_API_KEY": settings.GEMINI_API_KEY or "",
        "GEMINI_MODEL": settings.GEMINI_MODEL,
        "OCR_USE_GPU": "true" if settings.OCR_USE_GPU else "false",
        "WORK_ROOT": str(settings.WORK_ROOT),
    }
    log_f = open(wd / "runner.log", "ab")
    # start_new_session=True detaches from Streamlit's process group so the job
    # survives the UI session ending / the tab closing.
    subprocess.Popen(
        [sys.executable, str(_HERE / "job_runner.py"), "--spec", str(spec_path)],
        stdout=log_f, stderr=log_f, start_new_session=True, env=env,
    )


def read_status(job_id: str) -> dict | None:
    p = settings.WORK_ROOT / job_id / "status.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_jobs() -> list[dict]:
    root = settings.WORK_ROOT
    if not root.exists():
        return []
    jobs = []
    for d in root.iterdir():
        s = read_status(d.name)
        if s:
            jobs.append(s)
    jobs.sort(key=lambda s: s.get("started_at", 0), reverse=True)
    return jobs


def download_row(job_dir: Path):
    cols = st.columns(len(ZIP_LABELS))
    for col, (fname, label) in zip(cols, ZIP_LABELS):
        f = job_dir / fname
        with col:
            if f.exists():
                st.download_button(label, data=f.read_bytes(), file_name=f.name,
                                   mime="application/zip", key=f"dl_{job_dir.name}_{fname}")
            else:
                st.button(label, disabled=True, key=f"dl_{job_dir.name}_{fname}_off")


def render_job(s: dict):
    job_id = s["job_id"]
    job_dir = settings.WORK_ROOT / job_id
    status = s.get("status", "running")

    top = st.columns([3, 1, 1])
    top[0].markdown(f"**{s.get('show_title') or job_id}**  \n`{job_id}`")
    top[1].metric("Status", status.upper())
    started = s.get("started_at")
    if started:
        mins = (s.get("updated_at", time.time()) - started) / 60.0
        top[2].metric("Elapsed", f"{mins:.0f} min")

    st.progress(min(max(s.get("percent", 0), 0), 100) / 100.0)
    st.caption(f"Step {s.get('step', 0)}/5 — {s.get('step_label', '')}")

    if status == "error" and s.get("error"):
        st.error(s["error"])

    # step tracker
    cols = st.columns(5)
    for i, name in enumerate(PIPELINE_STEPS, 1):
        done = s.get("step", 0) > i or status == "done"
        active = s.get("step", 0) == i and status == "running"
        icon = "✅" if done else ("⏳" if active else "•")
        cols[i - 1].markdown(f"{icon} **{i}**  \n{name}")

    st.divider()
    st.markdown("**Deliverables**")
    download_row(job_dir)
    drive = s.get("drive", {})
    if drive:
        links = "  ·  ".join(f"[{k.replace('_',' ').title()}]({v})" for k, v in drive.items())
        st.caption("On Google Drive: " + links)

    with st.expander("Live log", expanded=(status == "running")):
        lines = [f"{l.get('msg','')}" for l in s.get("log", [])]
        st.code("\n".join(lines[-300:]) or "…", language="log")

    return status


# ═══════════════════════════════════════════════════════════════════════════
# Secrets / access control
# ═══════════════════════════════════════════════════════════════════════════
def _secret(name: str):
    """Read a value from Streamlit secrets (safe if no secrets file exists)."""
    try:
        return st.secrets.get(name)
    except Exception:
        return None


def configured_key() -> str | None:
    """The host's Gemini key from the environment or Streamlit secrets.

    When present, the key stays SERVER-SIDE — it is never shown in the UI and
    never sent to a user's browser. It is only forwarded to the detached job
    runner via an environment variable.
    """
    return os.environ.get("GEMINI_API_KEY") or _secret("GEMINI_API_KEY")


# ═══════════════════════════════════════════════════════════════════════════
# Sidebar
# ═══════════════════════════════════════════════════════════════════════════
st.sidebar.title("⚙️ Configuration")

_admin_key = configured_key()
if _admin_key:
    # Host provided the key server-side → don't render an input; never expose it.
    settings.GEMINI_API_KEY = _admin_key
    st.sidebar.success("✓ Gemini API key configured by the host")
else:
    # No host key (e.g. someone self-hosting) → let them supply their own.
    _k = st.sidebar.text_input(
        "Gemini API key", type="password",
        help="No host key found. Paste your own to run the Full pipeline "
             "(not needed for Formatting Only).")
    if _k:
        settings.GEMINI_API_KEY = _k

settings.GEMINI_MODEL = st.sidebar.selectbox(
    "Gemini model",
    ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-pro", "gemini-1.5-flash"],
    index=0,
    help="The app auto-detects which models your key supports and falls back "
         "accordingly, so any choice here is safe.")
settings.OCR_USE_GPU = st.sidebar.toggle("Use GPU for OCR", value=settings.OCR_USE_GPU,
                                         help="Enable only on a CUDA host.")
st.sidebar.divider()
st.sidebar.caption(f"Workspace: `{settings.WORK_ROOT}`")


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════
st.title("🎬 Microdrama Adaptation Checker")
st.caption("Chinese microdrama → Hindi director-ready screenplay, end to end.")

tab_fmt, tab_pipe, tab_jobs = st.tabs(
    ["✨ Formatting Only", "🚀 Full Adaptation Checker", "📂 My Jobs"])

# ── Formatting Only (inline) ─────────────────────────────────────────────────
with tab_fmt:
    st.write("Upload an unformatted script → a cleanly formatted screenplay + report. "
             "Optionally enrich it into a **director-ready** screenplay (Scene Profiles with "
             "character descriptions + an emotional cue on every line, dialogue kept verbatim).")

    f_title = st.text_input("Title (optional)", key="fmt_title")
    f_file = st.file_uploader("Script (PDF / DOCX / TXT)", type=["pdf", "docx", "txt"], key="fmt_file")
    enrich = st.toggle(
        "🎬 Director-ready enrichment (AI)", value=bool(settings.GEMINI_API_KEY),
        help="Adds Scene Profiles (character age/build/state-of-mind), grounded action and an "
             "emotion bracket on every dialogue line. Needs the Gemini key; takes longer on long scripts.")
    if enrich and not settings.GEMINI_API_KEY:
        st.info("Enrichment needs a Gemini key (configure it in the sidebar/secrets). "
                "Without it you still get the clean formatted PDF.")

    if st.button("✨ Format Script", type="primary"):
        if not f_file:
            st.error("Upload a script file.")
        else:
            # ── Stage 1 — fast deterministic formatting (always delivered) ──
            try:
                from app.pipeline import model4_formatter
                from app.pipeline.textextract import extract_text
                from app.zipper import zip_files

                wd = workdir("fmt_" + uuid.uuid4().hex[:8])
                src = save_upload(f_file, wd / f_file.name)
                if src.suffix.lower() == ".docx":  # DOCX → text the checker can read
                    txt = wd / f"{src.stem}.txt"
                    txt.write_text(extract_text(src), encoding="utf-8")
                    src = txt
                with st.spinner("Formatting…"):
                    out = model4_formatter.run(str(src), outdir=str(wd))
                r = out["result"]
                base = Path(out["pdf"]).stem.replace("_formatted", "")
            except Exception as e:
                st.error(f"Formatting failed: {e}")
                st.exception(e)
                st.stop()

            # Show + offer the fast result IMMEDIATELY.
            c1, c2, c3 = st.columns(3)
            c1.metric("Formatting", r["format_status"])
            c2.metric("Episodes", r["n_episodes"])
            c3.metric("Readability", f"{r['readability']}/5")
            st.success("✅ Formatted screenplay ready.")
            st.download_button("⬇️ Formatted screenplay (PDF)",
                               data=Path(out["pdf"]).read_bytes(),
                               file_name=Path(out["pdf"]).name, mime="application/pdf")

            files = [Path(out["pdf"]), Path(out["report"]), Path(out["corrected"])]

            # ── Stage 2 — director-ready enrichment (OPTIONAL, never fatal) ──
            if enrich and settings.GEMINI_API_KEY:
                try:
                    from app.pipeline import enrich_director_ready
                    corrected = Path(out["corrected"]).read_text(encoding="utf-8")
                    prog = st.progress(0.0, text="Director-ready enrichment (AI)…")
                    import app.state as _state
                    _state.set_step = lambda t, s, l, p: prog.progress(min(p, 100) / 100.0, text=l)
                    _state.log = lambda *a, **k: None
                    _state.add_artifact = _state.set_drive_link = lambda *a, **k: None
                    den = enrich_director_ready.run(
                        "fmt", corrected, wd, f_title or base.replace("_", " ").title(), base=base)
                    director_pdf = Path(den["director_pdf"])
                    files = [director_pdf, Path(den["bible_md"])] + files
                    prog.progress(1.0, text="Director-ready enrichment complete.")
                    st.success("🎬 Director-ready screenplay ready.")
                    st.download_button("⬇️ Director-Ready Screenplay (PDF)",
                                       data=director_pdf.read_bytes(),
                                       file_name=director_pdf.name, mime="application/pdf")
                except Exception as e:
                    st.warning(f"Director-ready enrichment couldn't finish ({e}). "
                               f"Your formatted screenplay above is ready to use.")

            zip_path = wd / "Formatted.zip"
            zip_files(files, zip_path)
            st.download_button("⬇️ Download everything (ZIP)",
                               data=zip_path.read_bytes(), file_name="Formatted.zip",
                               mime="application/zip")
            with st.expander("Formatting report"):
                st.markdown(Path(out["report"]).read_text(encoding="utf-8"))

# ── Full Adaptation Checker (detached) ───────────────────────────────────────
with tab_pipe:
    st.write("Videos + Hindi OG script → SRTs, screenplays, master PDF, and an adaptation "
             "report. The job runs in the background — **you can close this tab** and check "
             "**My Jobs** later. Download the results from **My Jobs** when it finishes.")

    if not OCR_AVAILABLE:
        st.warning(
            "⚠️ **Subtitle OCR (Step 1) isn't available on this instance.** This is expected on "
            "Streamlit Community Cloud, which can't install the heavy OCR/GPU stack. Run the full "
            "video pipeline on the **Docker image** (see README → Deploy). Formatting-Only and the "
            "screenplay/evaluation steps work fine here."
        )

    src_mode = st.radio("Video source", ["Upload video files", "Google Drive link"], horizontal=True)
    videos = drive_url = None
    if src_mode == "Upload video files":
        videos = st.file_uploader("Episode videos (.mp4/.mkv/.mov)",
                                  type=["mp4", "mkv", "mov", "webm", "avi"], accept_multiple_files=True)
    else:
        drive_url = st.text_input("Google Drive folder link")
        st.caption("📎 Share the folder as **‘Anyone with the link’** (Share → General access → "
                   "Anyone with the link). No Google sign-in, API key, or JSON needed — the app "
                   "just downloads the videos from the link.")

    c1, c2 = st.columns(2)
    p_title = c1.text_input("Show title (optional)")
    max_eps = c2.number_input("Max episodes (0 = all)", min_value=0, value=0, step=1)
    hindi = st.file_uploader("Hindi OG script (PDF / DOCX / TXT)", type=["pdf", "docx", "txt"])

    if st.button("▶️ Start Full Pipeline", type="primary"):
        errs = []
        if not settings.GEMINI_API_KEY:
            errs.append("A Gemini API key must be configured (sidebar/secrets).")
        if not hindi:
            errs.append("Upload the Hindi OG script.")
        if src_mode == "Upload video files" and not videos:
            errs.append("Upload at least one video file.")
        if src_mode == "Google Drive link" and not drive_url:
            errs.append("Paste the shared Google Drive folder link.")
        if errs:
            for e in errs:
                st.error(e)
        else:
            job_id = uuid.uuid4().hex
            wd = workdir(job_id)
            hindi_path = str(save_upload(hindi, wd / f"hindi_{hindi.name}"))
            spec = {"job_id": job_id, "workdir": str(wd), "mode": "pipeline",
                    "title": p_title, "max_episodes": int(max_eps), "hindi_path": hindi_path}
            if src_mode == "Upload video files":
                vids_dir = wd / "_input_videos"
                vids_dir.mkdir(parents=True, exist_ok=True)
                for v in videos:
                    save_upload(v, vids_dir / v.name)
                spec.update(source="local", videos_dir=str(vids_dir))
            else:
                spec.update(source="gdrive_link", drive_url=drive_url)

            launch_detached_job(spec)
            st.session_state["active_job"] = job_id
            st.success(f"🚀 Job started: `{job_id}`. Track it in **My Jobs** — you can close this tab.")

# ── My Jobs (status + downloads) ─────────────────────────────────────────────
with tab_jobs:
    jobs = list_jobs()
    if not jobs:
        st.info("No jobs yet. Start one from the Full Adaptation Checker tab.")
    else:
        ids = [j["job_id"] for j in jobs]
        labels = {j["job_id"]: f"{j.get('show_title') or '(untitled)'} · {j.get('status','?')} · {j['job_id'][:8]}"
                  for j in jobs}
        default = st.session_state.get("active_job")
        idx = ids.index(default) if default in ids else 0
        chosen = st.selectbox("Job", ids, index=idx, format_func=lambda i: labels[i])
        auto = st.checkbox("Auto-refresh (6s while running)", value=True)
        if st.button("🔄 Refresh now"):
            st.rerun()

        s = read_status(chosen)
        if s:
            status = render_job(s)
            if auto and status == "running":
                time.sleep(6)
                st.rerun()
