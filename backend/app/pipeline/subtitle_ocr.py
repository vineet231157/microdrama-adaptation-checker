"""Hard-subtitle OCR → SRT, using PaddleOCR + OpenCV directly.

Replaces the external `videocr` package (whose GitHub repo is no longer
cloneable). Samples frames from the video, OCRs the calculated crop region,
groups consecutive frames with the same/similar text into subtitle cues, and
writes a standard .srt. Uses only paddleocr + opencv + rapidfuzz, which are
already installed — no git clone, no fragile dependency.
"""
from __future__ import annotations

from ..config import settings


def _get_ocr():
    """Reuse the single PaddleOCR instance created for auto-crop (det+rec capable)."""
    from .autocrop import _get_paddle_detector
    return _get_paddle_detector()


def _ocr_text(ocr, img, conf_threshold: int) -> str:
    """Return the recognised text in the crop (confident lines only), reading order."""
    result = ocr.ocr(img, cls=False)
    if not result:
        return ""
    page = result[0] if result and isinstance(result[0], list) else result
    lines = []
    for det in page or []:
        try:
            box, (text, conf) = det[0], det[1]
        except Exception:
            continue
        if text and text.strip() and conf * 100 >= conf_threshold:
            top = min(p[1] for p in box)
            left = min(p[0] for p in box)
            lines.append((round(top, 1), round(left, 1), text.strip()))
    lines.sort()
    return " ".join(t for _, _, t in lines)


def _fmt_ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    ms = int(round((seconds - int(seconds)) * 1000))
    s = int(seconds)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _write_srt(cues: list[dict], srt_path: str, min_dur: float) -> None:
    lines = []
    for i, c in enumerate(cues, 1):
        start = c["start"]
        end = max(c["end"], start + min_dur)
        lines.append(str(i))
        lines.append(f"{_fmt_ts(start)} --> {_fmt_ts(end)}")
        lines.append(c["text"])
        lines.append("")
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def extract_srt(video_path: str, srt_path: str, crop, *,
                conf_threshold: int | None = None,
                sim_threshold: int | None = None,
                sample_fps: float | None = None,
                on_progress=None) -> str:
    """OCR the burned-in subtitles in `crop` and write an .srt to `srt_path`."""
    import cv2
    from rapidfuzz import fuzz

    conf_threshold = settings.OCR_CONF_THRESHOLD if conf_threshold is None else conf_threshold
    sim_threshold = settings.OCR_SIM_THRESHOLD if sim_threshold is None else sim_threshold
    sample_fps = settings.OCR_SAMPLE_FPS if sample_fps is None else sample_fps

    ocr = _get_ocr()
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video for OCR: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    stride = max(1, int(round(fps / max(sample_fps, 0.1))))
    x, y, w, h = crop.x, crop.y, crop.width, crop.height

    cues: list[dict] = []
    cur: dict | None = None
    idx = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % stride == 0:
                t = idx / fps
                sub = frame[y:y + h, x:x + w]
                text = _ocr_text(ocr, sub, conf_threshold) if sub.size else ""
                if text:
                    if cur and fuzz.ratio(text.lower(), cur["text"].lower()) >= sim_threshold:
                        cur["end"] = t                      # same subtitle → extend
                        if len(text) > len(cur["text"]):
                            cur["text"] = text              # keep the fullest reading
                    else:
                        if cur:
                            cues.append(cur)
                        cur = {"text": text, "start": t, "end": t}
                else:
                    if cur:
                        cues.append(cur)
                        cur = None
                if on_progress and total:
                    on_progress(int(idx / total * 100))
            idx += 1
    finally:
        cap.release()
    if cur:
        cues.append(cur)

    _write_srt(cues, srt_path, min_dur=stride / fps)
    return srt_path
