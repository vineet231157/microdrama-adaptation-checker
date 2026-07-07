# Microdrama Adaptation Checker — Streamlit app

A **single-file, single-process** way to host the whole tool. Same 5-step
pipeline as the Next.js + FastAPI + Celery stack — it just runs inline and
streams progress into Streamlit widgets instead of Redis + SSE. Best for an
internal tool your scriptwriters use directly.

```
streamlit/
├── streamlit_app.py                 the whole UI (2 tabs: Full Pipeline, Formatting Only)
├── local_source.py        drag-drop videos → duck-types the Drive client
├── requirements.txt       streamlit + the pipeline deps
├── Dockerfile             build from superapp/ root
└── .streamlit/
    ├── config.toml        4 GB upload limit, teal theme
    └── secrets.toml.example
```

It imports the shared pipeline directly from `../backend/app/pipeline/*`, so
there is **no code duplication** — the Streamlit and Next.js front-ends drive
identical logic.

---

## What it does

Two tabs:

1. **🚀 Full Adaptation Checker** — pick a video source, upload the Hindi OG
   script, run the 5 steps, download everything.
   - **Video source A — Upload files** (simplest): drag-drop `.mp4/.mkv/...`.
     No Google account, no OAuth.
   - **Video source B — Google Drive**: paste a folder link + a **service-account
     JSON**. Share the folder with the service account's `client_email`; the app
     reads the videos and writes `Extracted_SRTs_*` / `Individual_Screenplays_*`
     folders back to Drive.
2. **✨ Formatting Only** — upload a script (PDF/DOCX/TXT) → formatted PDF
   (deterministic, no AI, no key needed).

Outputs (download buttons appear on completion): **SRTs ZIP**, **Individual
Screenplays ZIP**, **Master + Evaluation ZIP** (master screenplay PDF +
adaptation-report PDF + JSON). In Drive mode the folders also populate live, so
you can grab intermediate SRTs from Drive while later steps run.

---

## Run locally

```bash
cd superapp/streamlit
python -m venv .venv && source .venv/bin/activate      # Python 3.11 recommended
pip install -r requirements.txt

# Also need the poppler CLI for PDF text extraction:
#   macOS:  brew install poppler
#   Ubuntu: sudo apt-get install poppler-utils ffmpeg

export GEMINI_API_KEY=your-key            # or paste it in the sidebar / secrets
streamlit run streamlit_app.py                       # opens http://localhost:8501
```

> **OCR note.** Step 1 (subtitle OCR) uses PaddleOCR. The default
> `paddlepaddle` (CPU) works everywhere but is slow on long videos. On a CUDA
> machine, install `paddlepaddle-gpu` instead and flip **“Use GPU for OCR”** in
> the sidebar. If you only need Formatting-Only or the screenplay/eval steps on
> pre-made SRTs, CPU is fine.

## Configuration

| Where | Key | Purpose |
|-------|-----|---------|
| Sidebar / Secrets | `GEMINI_API_KEY` | screenplay generation + evaluation |
| Sidebar | Gemini model | `gemini-1.5-pro` default (auto-fallback built in) |
| Sidebar | Use GPU for OCR | enable on CUDA hosts only |
| Drive mode | service-account JSON | Drive read/write |

On **Streamlit Community Cloud**, put `GEMINI_API_KEY` in the app's **Secrets**
box (see `.streamlit/secrets.toml.example`) — the sidebar auto-fills from it.

---

## Deploy

### Option 1 — Streamlit Community Cloud (fastest, free)
1. Push this repo to GitHub.
2. share.streamlit.io → **New app** → point at `superapp/streamlit/streamlit_app.py`.
3. Add `GEMINI_API_KEY` in **Secrets**.
4. ⚠️ The free tier has **no GPU and a ~1 GB RAM / limited-CPU** sandbox and a
   short request budget — great for **Formatting-Only** and small
   screenplay/eval jobs, but full video OCR of many long episodes will be slow
   or hit limits. For heavy OCR use Option 2 or 3.

### Option 2 — Docker (any VM, incl. a GPU box)
```bash
cd superapp
docker build -f streamlit/Dockerfile -t adaptation-streamlit .
docker run -p 8501:8501 -e GEMINI_API_KEY=your-key adaptation-streamlit
# → http://localhost:8501
```
For GPU OCR: base the image on an NVIDIA CUDA image, swap `paddlepaddle` →
`paddlepaddle-gpu` in `requirements.txt`, run with `--gpus all`, and toggle GPU
in the sidebar.

### Option 3 — Render / Railway / Cloud Run
Deploy the Docker image as one web service. Set `GEMINI_API_KEY`. Give it a
**persistent disk** (job artifacts are written under `WORK_ROOT`, default
`/tmp/adaptation_jobs`) if you want downloads to survive restarts. Pick a plan
with enough RAM/CPU (and a GPU for real OCR throughput).

### Option 4 — Hugging Face Spaces (Docker Space)
Use `streamlit/Dockerfile`, add `GEMINI_API_KEY` as a Space secret. Upgrade to a
GPU Space for OCR.

---

## When to use this vs. the Next.js + FastAPI stack

| | **Streamlit** (this) | **Next.js + FastAPI + Celery** |
|--|--|--|
| Setup | one process, one container | frontend (Vercel) + API + worker + Redis |
| Auth | service account / direct upload | per-user Google OAuth (Drive scope) |
| Concurrency | one job per session (synchronous) | many concurrent users, queued jobs |
| Progressive downloads | on completion (+ live Drive folders) | true per-step download buttons via SSE |
| Best for | internal team tool, quick hosting | multi-user product, long parallel jobs |

Because a 15–30 min video job runs **synchronously** in a Streamlit session,
Streamlit is ideal for a handful of scriptwriters running jobs one at a time.
For a multi-user product with many simultaneous long jobs, the Celery stack is
the better fit. Both share the same pipeline code, so you can start on Streamlit
and graduate to the full stack later with no logic changes.
