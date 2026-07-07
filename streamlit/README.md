# Streamlit app — quick reference

> Full setup, deployment, and usage instructions live in the **[repo root
> README](../README.md)**. This is a short pointer.

```
streamlit/
├── streamlit_app.py   the UI — 3 tabs: Formatting Only · Full Adaptation Checker · My Jobs
├── job_runner.py      detached background runner (multi-hour jobs survive tab close)
├── local_source.py    drag-drop videos → duck-types the Drive client
├── Dockerfile         build from the repo root
└── .streamlit/        config.toml + secrets.toml.example
```

## Run locally
```bash
# from the repo root
pip install -r requirements.txt        # + brew/apt install poppler ffmpeg
streamlit run streamlit/streamlit_app.py
```

## Keeping your API key private
Set `GEMINI_API_KEY` in `.streamlit/secrets.toml` or the Streamlit Cloud
**Secrets** box. When a host key is present the app hides the key input entirely —
users never see or enter it. See the root README →
**“Sharing the tool without giving out your API key.”**

## Modes
- **Formatting Only** — instant, deterministic, no key. Outputs `_formatted.pdf`,
  `_format_report.md`, `_corrected.txt`.
- **Full Adaptation Checker** — videos (upload or Drive) + Hindi script → SRTs,
  screenplays, master PDF, evaluation report. Runs in a **detached background
  process**, writes `SRT_Files/` + `Screenplays/` to Drive, and downloads appear
  in **My Jobs**. Safe to close the tab.

Community Cloud suits Formatting-Only; run the video pipeline on a Docker
server/GPU box (see root README → Deploy).
