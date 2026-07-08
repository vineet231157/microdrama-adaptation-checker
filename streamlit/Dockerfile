# Streamlit image — runs the whole pipeline in one container.
# Build from the repo ROOT so it can copy both backend/ and streamlit/:
#     docker build -f streamlit/Dockerfile -t adaptation-checker .
#     docker run -p 8501:8501 -e GEMINI_API_KEY=... adaptation-checker
#
# Pinned to linux/amd64: the OCR wheels (paddlepaddle 2.6.2) have no arm64 build,
# so this guarantees a working install on both Intel and Apple-Silicon Macs
# (the latter runs it under emulation — slower, but it works).
FROM --platform=linux/amd64 python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1

# poppler (pdftotext), OpenCV runtime libs, ffmpeg (video decode), git (videocr),
# curl (health check)
RUN apt-get update && apt-get install -y --no-install-recommends \
        poppler-utils libgl1 libglib2.0-0 ffmpeg git build-essential curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1) Heavy OCR stack FIRST (rarely changes) so light-dep edits don't re-trigger
#    the ~15-min PaddleOCR reinstall. Subtitle→SRT extraction is done in
#    app/pipeline/subtitle_ocr.py, so there is NO external videocr git dependency.
COPY requirements-ocr.txt .
RUN pip install -r requirements-ocr.txt

# 2) Light deps (UI + formatting + gemini + drive + pdf) — cached independently.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Bring in the shared pipeline code + the Streamlit UI.
COPY backend/app ./backend/app
COPY streamlit ./streamlit

WORKDIR /app/streamlit
EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
