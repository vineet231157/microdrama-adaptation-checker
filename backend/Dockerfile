# ─────────────────────────────────────────────────────────────────────────────
# Backend image: FastAPI + Celery worker + PaddleOCR + OpenCV + poppler.
#
# GPU: for real OCR throughput deploy on a CUDA host and install paddlepaddle-gpu
# (uncomment the GPU block). The CPU path below works everywhere but is slow.
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# System deps:
#  - poppler-utils → pdftotext (used by format_check.py for PDF extraction)
#  - libgl1 / libglib2.0-0 → OpenCV runtime
#  - ffmpeg → robust video decoding for OpenCV/videocr
#  - git → installing videocr from GitHub
RUN apt-get update && apt-get install -y --no-install-recommends \
        poppler-utils libgl1 libglib2.0-0 ffmpeg git build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Python deps ──────────────────────────────────────────────────────────────
COPY requirements.txt .

# CPU PaddlePaddle (default). For GPU, comment the next line and use the GPU one.
RUN pip install paddlepaddle==2.6.2
# GPU alternative (CUDA host only):
# RUN pip install paddlepaddle-gpu==2.6.2 -f https://www.paddlepaddle.org.cn/whl/linux/mkl/avx/stable.html

RUN pip install -r requirements.txt

COPY app ./app

EXPOSE 8000

# Default command runs the API. The worker overrides this in docker-compose.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
