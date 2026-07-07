# 🎬 Microdrama Adaptation Checker

An end-to-end tool that turns **raw Chinese microdrama videos + a Hindi OG
script** into a **director-ready master screenplay** and an **adaptation-review
report** — automating the 5 models you previously ran by hand in Colab.

Hosted as a **Streamlit** web app so any scriptwriter can use it from a browser.

> This README is the complete guide: **repo contents → put it on GitHub → deploy
> → use it.** For internals/diagrams see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Two modes

### ✨ Formatting Only — instant, no AI
Upload an unformatted script (PDF/DOCX/TXT). You get back, exactly like the
notebook did, three files zipped together:
- `<name>_formatted.pdf` — the re-typeset, renumbered screenplay
- `<name>_format_report.md` — status, readability, long-dialogue table, action
  walls, emotion-as-action flags, runtime
- `<name>_corrected.txt` — the corrected plain text

Runs **inline in seconds**. No API key, no GPU.

### 🚀 Full Adaptation Checker — the 5-step pipeline (can run for hours)
Give it the episode **videos** (drag-drop *or* a Google Drive folder) and the
**Hindi OG script**:

| Step | Does | Output |
|------|------|--------|
| 1 · SRT extraction | Auto-crops the subtitle band (OpenCV) and OCRs it (PaddleOCR/videocr) | `.srt` per episode |
| 2 · Screenplay | Gemini watches each video, writes a screenplay with dialogue locked to the SRT | `.md`/`.pdf` per episode |
| 3 · Merge | Stitches episodes into one master document | — |
| 4 · Format | Deterministic checker + renumber → formatted **Master PDF** + report | Master PDF |
| 5 · Evaluate | Gemini compares Hindi vs the English master against the review "Bible" | **Report PDF** |

**It creates folders in your Drive exactly like your notebook** — an `SRT_Files/`
folder and a `Screenplays/` folder inside your source video folder — and uploads
the SRTs, per-episode screenplays, master PDF and report there. It also offers
**SRTs / Screenplays / Master+Evaluation** ZIP downloads in the UI.

**Long jobs are safe.** A full run of many long episodes can take **3–5 hours**.
The job runs as a **detached background process**, so you can **close the browser
tab** and come back later — track progress and grab downloads in the **📂 My
Jobs** tab. Results also land in Drive regardless.

---

## Repo layout (what's on GitHub)

The repo root **is** the app (so `requirements.txt` + `packages.txt` sit at the
top level, where Streamlit Cloud looks for them).

```
<repo root>/
├── requirements.txt          Python deps (Streamlit Cloud auto-detects)
├── packages.txt              apt packages (poppler, ffmpeg) for Streamlit Cloud
├── README.md · ARCHITECTURE.md · .gitignore
├── streamlit/
│   ├── streamlit_app.py      THE APP  (Streamlit "Main file path")
│   ├── job_runner.py         detached background runner for the full pipeline
│   ├── local_source.py       drag-drop videos → duck-types the Drive client
│   ├── Dockerfile            for server/GPU deploys (build from repo root)
│   └── .streamlit/           config.toml + secrets.toml.example
├── backend/app/              the shared pipeline the app imports
│   ├── pipeline/             step1..step5, autocrop, format_check, model4_formatter, prompts …
│   └── drive.py  gemini.py  config.py  …
└── (frontend/ · docker-compose.yml · render.yaml)   ← optional multi-user stack; ignore for Streamlit
```

---

## Prerequisites

- **Python 3.11** (PaddleOCR has no wheels for 3.12+ — pin 3.11).
- **Gemini API key** — https://aistudio.google.com/apikey (Steps 2 & 5; not
  needed for Formatting-Only).
- **poppler + ffmpeg** (PDF text + video decode). Local: `brew install poppler
  ffmpeg` / `apt-get install poppler-utils ffmpeg`. On servers these come from
  `packages.txt` / the Dockerfile.
- A **GitHub** account. For the video pipeline: a machine with enough
  **RAM/CPU (ideally a GPU)** — see deployment below.
- *(Drive mode)* a Google Cloud **service-account** JSON.

---

## Part 1 — Put the code on GitHub

From this repo root:

```bash
git init -b main
git add .
git commit -m "Microdrama Adaptation Checker"
gh repo create microdrama-adaptation-checker --private --source=. --push
# …or add the remote the GitHub UI shows you and: git push -u origin main
```

`.gitignore` already excludes `.env`, `secrets.toml`, and service-account JSONs —
**never commit secrets.**

---

## Part 2 — Run locally

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # + brew/apt install poppler ffmpeg
export GEMINI_API_KEY=your-key            # or paste it in the sidebar
streamlit run streamlit/streamlit_app.py  # → http://localhost:8501
```

---

## Part 3 — Deploy

Pick the host based on which mode you need:

### Formatting Only → Streamlit Community Cloud (free, easiest)
1. https://share.streamlit.io → sign in with GitHub → **Create app**.
2. Repository `…/microdrama-adaptation-checker`, branch `main`,
   **Main file path `streamlit/streamlit_app.py`**,
   **Advanced → Python version `3.11`**.
3. Deploy → `https://<your-app>.streamlit.app`.

Community Cloud is perfect for the instant Formatting mode. **It is not suitable
for the full video pipeline** — the free sandbox has **no GPU, limited RAM, and
recycles idle apps**, so a multi-hour OCR job would be killed. Use a real server
for that ↓.

### Full video pipeline → Docker on a server (recommended; GPU for OCR speed)
Because jobs run for hours and Step 1 is OCR-heavy, deploy on a VM/box you
control (a cloud **GPU VM**, a Hugging Face **GPU Docker Space**, or your own
workstation):

```bash
# build from the repo root
docker build -f streamlit/Dockerfile -t adaptation-checker .
docker run -p 8501:8501 \
  -e GEMINI_API_KEY=your-key \
  -v adaptation_jobs:/tmp/adaptation_jobs \   # persist jobs/results across restarts
  adaptation-checker
# → http://localhost:8501  (put it behind your VPN / an auth proxy for a team)
```

For real OCR throughput: base the image on an NVIDIA CUDA image, replace
`paddlepaddle` with `paddlepaddle-gpu` in `requirements.txt`, run with
`--gpus all`, and enable **Use GPU for OCR** in the sidebar.

> The background job runner and its `status.json`/ZIP artifacts live under
> `WORK_ROOT` (`/tmp/adaptation_jobs` by default). Mount a volume there so the
> **My Jobs** tab and downloads survive container restarts.

---

## Configuration & secrets

| Setting | Where | Purpose |
|---------|-------|---------|
| `GEMINI_API_KEY` | Streamlit **Secrets** / sidebar / `-e` | screenplay + evaluation |
| Gemini model | sidebar | default `gemini-1.5-pro`, auto-fallback built in |
| Use GPU for OCR | sidebar | enable only on a CUDA host |
| Service-account JSON | uploaded in Drive mode | Drive read/write |

**Drive mode setup:** create a service account, enable the **Google Drive API**,
download its JSON key, and **share your video folder with the service account's
`client_email`** so it can read the videos and create `SRT_Files/` +
`Screenplays/`.

---

## Using the tool

- **Formatting Only:** upload a script → **Format Script** → download the ZIP
  (formatted PDF + report + corrected text) instantly.
- **Full Adaptation Checker:** choose **Upload video files** or **Google Drive
  folder** (+ service-account JSON), upload the **Hindi OG script**, **Start Full
  Pipeline**. You'll get a **Job ID** — the job now runs in the background.
- **📂 My Jobs:** select your job to watch live progress (auto-refreshes),
  download **SRTs / Screenplays / Master+Evaluation** ZIPs as they're produced,
  and open the Drive folders. **Safe to close the tab** — the job keeps running.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `paddlepaddle` install fails | Set **Python 3.11** (Streamlit Cloud: Advanced settings). |
| `pdftotext: not found` / empty PDF text | Ensure `poppler-utils` is installed (`packages.txt` / Dockerfile). |
| Full pipeline killed / times out on Streamlit Cloud | Expected — run the video pipeline on a Docker server (above), not Community Cloud. |
| OCR very slow | No GPU; use `paddlepaddle-gpu` on a CUDA host and toggle GPU in the sidebar. |
| Gemini `429` | Built-in exponential backoff retries; if persistent, lower episode count or raise your quota. |
| Drive "file not found" | Share the folder with the service account's `client_email`. |
| Job vanished after restart | Mount a volume at `WORK_ROOT` (`/tmp/adaptation_jobs`) to persist jobs. |
```
