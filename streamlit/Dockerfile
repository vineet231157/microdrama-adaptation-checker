# Streamlit image — runs the whole pipeline in one container.
# Build from the superapp/ ROOT so it can copy both backend/ and streamlit/:
#     docker build -f streamlit/Dockerfile -t adaptation-streamlit .
#     docker run -p 8501:8501 -e GEMINI_API_KEY=... adaptation-streamlit
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1

# poppler (pdftotext), OpenCV runtime libs, ffmpeg (video decode), git (videocr)
RUN apt-get update && apt-get install -y --no-install-recommends \
        poppler-utils libgl1 libglib2.0-0 ffmpeg git build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Canonical deps live at the repo root.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Bring in the shared pipeline code + the Streamlit UI.
COPY backend/app ./backend/app
COPY streamlit ./streamlit

WORKDIR /app/streamlit
EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
