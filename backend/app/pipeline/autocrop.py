"""Auto-crop calculation — replaces the manual ``crop_selector.py`` step.

Algorithm (per the spec):
  1. Sample N frames from the MIDDLE of the first episode (where hard-subs are
     reliably present, avoiding title cards / black intros).
  2. Restrict text detection to the LOWER ``lower_fraction`` (default 30%) of the
     frame height — hard subs live at the bottom.
  3. Run a lightweight text detector on each sampled band and collect every text
     bounding box (converted back to full-frame coordinates).
  4. Take the GLOBAL bounding box that encloses all detected text boxes, add a
     margin, clamp to the frame, and return (crop_x, crop_y, crop_width, crop_height).

Primary detector: PaddleOCR in detection-only mode (already a dependency, robust
on stylised subs). Fallback: OpenCV MSER text-region heuristic (no model needed),
so the pipeline still degrades gracefully if Paddle can't initialise.

If NOTHING is detected across all samples, we fall back to a sensible default:
the full width × the lower 25% of the frame.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

from ..config import settings

log = logging.getLogger(__name__)

# Cache a single detector instance per worker process (model load is expensive).
_PADDLE_DET = None


@dataclass
class Crop:
    x: int
    y: int
    width: int
    height: int

    def as_kwargs(self) -> dict:
        return {
            "crop_x": self.x,
            "crop_y": self.y,
            "crop_width": self.width,
            "crop_height": self.height,
        }


def _get_paddle_detector():
    global _PADDLE_DET
    if _PADDLE_DET is None:
        from paddleocr import PaddleOCR  # lazy — heavy import
        _PADDLE_DET = PaddleOCR(
            use_angle_cls=False,
            lang=settings.OCR_LANG,
            use_gpu=settings.OCR_USE_GPU,
            show_log=False,
        )
    return _PADDLE_DET


def _sample_frame_indices(total: int, n: int) -> list[int]:
    """N evenly spaced indices from the middle 60% of the video."""
    if total <= 0:
        return []
    lo, hi = int(total * 0.20), int(total * 0.80)
    hi = max(hi, lo + 1)
    if n >= (hi - lo):
        return list(range(lo, hi))
    step = (hi - lo) / n
    return [int(lo + step * i) for i in range(n)]


def _detect_boxes_paddle(band_bgr) -> list[tuple[int, int, int, int]]:
    """Return (x1,y1,x2,y2) boxes in band-local coords using PaddleOCR detection."""
    det = _get_paddle_detector()
    # rec=False → detection only (fast, no recognition step)
    result = det.ocr(band_bgr, det=True, rec=False, cls=False)
    boxes: list[tuple[int, int, int, int]] = []
    if not result:
        return boxes
    # PaddleOCR returns a nested list; each entry is a 4-point polygon.
    polys = result[0] if result and isinstance(result[0], list) else result
    for poly in polys or []:
        pts = np.array(poly).reshape(-1, 2)
        x1, y1 = pts[:, 0].min(), pts[:, 1].min()
        x2, y2 = pts[:, 0].max(), pts[:, 1].max()
        boxes.append((int(x1), int(y1), int(x2), int(y2)))
    return boxes


def _detect_boxes_mser(band_bgr) -> list[tuple[int, int, int, int]]:
    """Fallback: OpenCV MSER blobs merged into text-like regions."""
    gray = cv2.cvtColor(band_bgr, cv2.COLOR_BGR2GRAY)
    mser = cv2.MSER_create()
    regions, _ = mser.detectRegions(gray)
    boxes = []
    h, w = gray.shape
    for pts in regions:
        x, y, bw, bh = cv2.boundingRect(pts.reshape(-1, 1, 2))
        # keep only text-glyph-sized blobs
        if 6 < bh < h * 0.6 and bw < w * 0.9 and bw > 2:
            boxes.append((x, y, x + bw, y + bh))
    return boxes


def calculate_crop(
    video_path: str,
    samples: int | None = None,
    lower_fraction: float | None = None,
    margin: int | None = None,
) -> Crop:
    samples = samples or settings.AUTOCROP_SAMPLES
    lower_fraction = lower_fraction or settings.AUTOCROP_LOWER_FRACTION
    margin = margin if margin is not None else settings.AUTOCROP_MARGIN_PX

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video for auto-crop: {video_path}")

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    band_top = int(frame_h * (1.0 - lower_fraction))  # y where the lower band starts

    try:
        detector = _detect_boxes_paddle
        try:
            _get_paddle_detector()
        except Exception as e:  # pragma: no cover - environment dependent
            log.warning("PaddleOCR detector unavailable (%s); using MSER fallback.", e)
            detector = _detect_boxes_mser

        all_boxes: list[tuple[int, int, int, int]] = []
        for idx in _sample_frame_indices(total, samples):
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            band = frame[band_top:frame_h, 0:frame_w]  # lower band only
            for (x1, y1, x2, y2) in detector(band):
                # shift band-local y back into full-frame coordinates
                all_boxes.append((x1, y1 + band_top, x2, y2 + band_top))
    finally:
        cap.release()

    if not all_boxes:
        # Nothing detected → default: full width, lower 25%.
        log.warning("Auto-crop found no text; using default lower-band crop.")
        y = int(frame_h * 0.75)
        return Crop(x=0, y=y, width=frame_w, height=frame_h - y)

    # Global minimum bounding box across ALL detected boxes.
    min_x = min(b[0] for b in all_boxes)
    min_y = min(b[1] for b in all_boxes)
    max_x = max(b[2] for b in all_boxes)
    max_y = max(b[3] for b in all_boxes)

    # Add margin and clamp to the frame.
    x = max(0, min_x - margin)
    y = max(0, min_y - margin)
    x2 = min(frame_w, max_x + margin)
    y2 = min(frame_h, max_y + margin)

    return Crop(x=x, y=y, width=x2 - x, height=y2 - y)
