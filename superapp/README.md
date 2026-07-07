# 🎬 Microdrama Adaptation Checker

An end-to-end tool that turns **raw Chinese microdrama videos + a Hindi OG
script** into a **director-ready master screenplay** and an **adaptation-review
report** — automating the 5 models you previously ran by hand in Colab.

Hosted as a **Streamlit** web app so any scriptwriter can use it from a browser.

> This README is the complete guide: **what's in the repo → put it on GitHub →
> deploy it as a Streamlit tool → use it.** For the internals/diagrams see
> [ARCHITECTURE.md](ARCHITECTURE.md).

---

## What it does

Two modes in one app:

- **✨ Formatting Only** — upload an unformatted script (PDF/DOCX/TXT) → cleanly
  formatted screenplay PDF. Deterministic, no AI, no API key.
- **🚀 Full Adaptation Checker** — the 5-step pipeline:

| Step | Does | Output |
|------|------|--------|
| 1 · SRT extraction | Auto-crops the subtitle band (OpenCV) and OCRs it (PaddleOCR/videocr) | `.srt` per episode → **SRTs ZIP** |
| 2 · Screenplay | Gemini watches each video, writes a screenplay with dialogue locked to the SRT | `.md`/`.pdf` per episode → **Screenplays ZIP** |
| 3 · Merge | Stitches episodes into one master document | — |
| 4 · Format | Deterministic checker + renumber → formatted **Master PDF** | Master PDF |
| 5 · Evaluate | Gemini compares Hindi vs the English master against the review "Bible" | **Report PDF** → **Final ZIP** |

Videos come from **drag-drop upload** (no Google account needed) or a **Google
Drive folder** (via a service-account key). In Drive mode the results are also
written back to Drive folders.

---

## Repo layout (what goes on GitHub)

Push the **contents of this `superapp/` folder** as your repository root — the
root-level `requirements.txt` and `packages.txt` are what Streamlit Cloud reads.

```
<your-repo-root>/                 ←  = the superapp/ folder
├── requirements.txt              Python deps (Streamlit Cloud auto-detects this)
├── packages.txt                  apt packages (poppler, ffmpeg) for Streamlit Cloud
├── ARCHITECTURE.md
├── README.md                     ← this file
├── .gitignore
├── streamlit/
│   ├── streamlit_app.py          THE APP  (Streamlit Cloud "Main file path")
│   ├── local_source.py           drag-drop videos → duck-types the Drive client
│   ├── Dockerfile                for Docker/Render/Cloud Run/HF deploys
│   └── .streamlit/
│       ├── config.toml           4 GB upload limit, theme
│       └── secrets.toml.example  → copy to secrets.toml locally
├── backend/app/                  the shared pipeline the app imports
│   ├── pipeline/                 step1..step5, autocrop, format_check, prompts …
│   ├── drive.py  gemini.py  config.py  state.py  …
└── (frontend/ + docker-compose.yml + render.yaml)   ← optional scale-out stack; ignore for Streamlit
```

The `frontend/` (Next.js) + `backend/main.py` (FastAPI) + `docker-compose.yml`
are the optional multi-user product stack. **For the Streamlit tool you can
ignore them** — they don't interfere. Keep or delete them as you like.

---

## Prerequisites

- **Python 3.11** (PaddleOCR wheels don't exist for 3.13/3.14 yet — pin 3.11).
- **Gemini API key** — https://aistudio.google.com/apikey (Steps 2 & 5). Not
  needed for Formatting-Only.
- **poppler + ffmpeg** system tools (PDF text + video decode). Local install:
  `brew install poppler ffmpeg` (macOS) / `apt-get install poppler-utils ffmpeg`
  (Ubuntu). On Streamlit Cloud these come from `packages.txt` automatically.
- A **GitHub** account and a **Streamlit Community Cloud** account
  (https://share.streamlit.io, sign in with GitHub) — both free.
- *(Optional, Drive mode)* a **Google Cloud service account** JSON.

---

## Part 1 — Put the code on GitHub

From a terminal, at this `superapp/` folder:

```bash
cd superapp

# 1. Initialise a repo (a .gitignore is already included).
git init -b main
git add .
git commit -m "Microdrama Adaptation Checker — Streamlit tool"
```

Then create the GitHub repo and push. **Either** with the GitHub CLI:

```bash
# gh auth login   (once, if you haven't)
gh repo create microdrama-adaptation-checker --private --source=. --push
```

**Or** via the website:

1. github.com → **New repository** → name it `microdrama-adaptation-checker`
   (Private is fine) → **Create** (don't add a README/…, the repo is not empty).
2. Copy the "push an existing repository" commands it shows, e.g.:

```bash
git remote add origin https://github.com/<you>/microdrama-adaptation-checker.git
git push -u origin main
```

✅ Your code is now on GitHub. **Never commit secrets** — `.gitignore` already
excludes `.env`, `secrets.toml`, and any service-account JSON.

---

## Part 2 — Run it locally (optional sanity check)

```bash
cd superapp
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export GEMINI_API_KEY=your-key          # or paste it in the sidebar at runtime
streamlit run streamlit/streamlit_app.py # opens http://localhost:8501
```

---

## Part 3 — Deploy as a Streamlit tool

### A) Streamlit Community Cloud (recommended, free, connects to GitHub)

1. Go to **https://share.streamlit.io** → sign in with GitHub.
2. **Create app → Deploy a public/private app from GitHub**.
3. Fill in:
   - **Repository:** `<you>/microdrama-adaptation-checker`
   - **Branch:** `main`
   - **Main file path:** `streamlit/streamlit_app.py`
   - **Advanced settings → Python version:** **3.11**
4. **Advanced settings → Secrets:** paste your key (see
   `streamlit/.streamlit/secrets.toml.example`):
   ```toml
   GEMINI_API_KEY = "your-gemini-api-key"
   ```
5. **Deploy.** Streamlit installs `requirements.txt` + the `packages.txt` apt
   packages, then serves the app at `https://<your-app>.streamlit.app`.

> ⚠️ **Free-tier limits.** The free sandbox has **no GPU** and limited RAM/CPU.
> That's perfect for **Formatting-Only** and for screenplay/eval runs, but full
> **video OCR** of many long episodes will be slow or hit memory limits. For
> heavy OCR, deploy with a GPU using option B or C below (the app is identical).

### B) Docker — on any VM, including a GPU box

```bash
cd superapp
docker build -f streamlit/Dockerfile -t adaptation-checker .
docker run -p 8501:8501 -e GEMINI_API_KEY=your-key adaptation-checker
# → http://localhost:8501
```
GPU OCR: base the image on an NVIDIA CUDA image, swap `paddlepaddle` →
`paddlepaddle-gpu` in `requirements.txt`, run with `--gpus all`, and toggle
"Use GPU for OCR" in the sidebar.

### C) Render / Railway / Hugging Face Spaces

Deploy `streamlit/Dockerfile` as a single web service; set `GEMINI_API_KEY`; add
a persistent disk if you want download artifacts to survive restarts. HF Spaces:
create a **Docker Space**, add `GEMINI_API_KEY` as a secret, pick a GPU tier for
OCR.

---

## Configuration & secrets

| Setting | Where | Purpose |
|---------|-------|---------|
| `GEMINI_API_KEY` | Streamlit **Secrets** / sidebar / `export` | screenplay + evaluation |
| Gemini model | sidebar | default `gemini-1.5-pro`, auto-fallback built in |
| Use GPU for OCR | sidebar | enable only on a CUDA host |
| Service-account JSON | uploaded in Drive mode | Drive read/write |

**Drive mode setup:** create a service account in Google Cloud, enable the
**Google Drive API**, download its JSON key, and **share your Drive video folder
with the service account's `client_email`** so it can read videos and create
result folders.

---

## Using the tool

1. Open the app URL.
2. **Formatting Only** tab → upload a script → **Format Script** → download PDF.
3. **Full Adaptation Checker** tab →
   - choose **Upload video files** (drag-drop) *or* **Google Drive folder** (+ JSON),
   - upload the **Hindi OG script**,
   - **Start Full Pipeline** → watch the live log/progress → download **SRTs**,
     **Screenplays**, and **Master + Evaluation** ZIPs when done.

> Because a full video job runs synchronously in your session (it can take
> 15–30+ min for many episodes), Streamlit suits a few scriptwriters running
> jobs one at a time. For many concurrent users, the optional Next.js + FastAPI
> + Celery stack in this repo scales out — same pipeline code. See
> [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `paddlepaddle` install fails on Streamlit Cloud | Set **Python version = 3.11** in Advanced settings. |
| `pdftotext: not found` / PDF text empty | `packages.txt` must include `poppler-utils` (it does) — redeploy so apt runs. |
| OCR extremely slow / app restarts | Free tier has no GPU; use Docker/HF on a GPU host for Step 1. |
| Gemini `429` errors | Built-in exponential backoff retries; if persistent, lower episode count or upgrade your Gemini quota. |
| Drive "file not found" | Share the folder with the service account's `client_email`. |
