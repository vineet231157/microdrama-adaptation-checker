"""STEP 1 — Automated SRT extraction & folder generation (Model 1).

For each episode video in the Drive folder:
  • stream-download it into the job's /tmp workspace,
  • (first episode only) auto-calculate the subtitle crop region,
  • OCR the hard-subtitles (PaddleOCR + OpenCV) constrained to that crop → .srt,
  • save the .srt locally, upload it to an ``SRT_Files`` Drive folder,
  • delete the local .mp4 immediately to keep disk usage flat,
  • re-zip the SRTs folder so the frontend can download partial results early.
"""
from __future__ import annotations

from pathlib import Path

from .. import state
from ..config import settings
from ..drive import DriveClient
from ..zipper import zip_folder
from . import autocrop
from .common import episode_number


def _run_ocr(video_path: Path, srt_path: Path, crop: autocrop.Crop) -> None:
    """OCR the hard-subtitles inside the calculated crop box → .srt."""
    from . import subtitle_ocr  # PaddleOCR + OpenCV (no external videocr dependency)

    subtitle_ocr.extract_srt(
        str(video_path), str(srt_path), crop,
        conf_threshold=settings.OCR_CONF_THRESHOLD,
        sim_threshold=settings.OCR_SIM_THRESHOLD,
    )


def run(task_id: str, drive: DriveClient, source_folder_id: str, workdir: Path) -> dict:
    """Returns {'srt_dir': Path, 'srts': [{name, path, ep}], 'srt_folder_id': str}."""
    srt_dir = workdir / "SRTs"
    vid_dir = workdir / "_videos"
    srt_dir.mkdir(parents=True, exist_ok=True)
    vid_dir.mkdir(parents=True, exist_ok=True)

    videos = drive.list_videos(source_folder_id)
    if not videos:
        raise RuntimeError("No video files (.mp4/.mkv/...) found in the Drive folder.")
    videos.sort(key=lambda v: (episode_number(v["name"]) is None,
                               episode_number(v["name"]) or 0, v["name"]))
    state.log(task_id, f"Found {len(videos)} episode(s) in Drive.")

    # Create/reuse an "SRT_Files" folder inside the source folder (matches the
    # original notebook's behaviour).
    srt_folder_id = drive.get_or_create_subfolder(source_folder_id, "SRT_Files")
    state.set_drive_link(task_id, "srt_folder", DriveClient.folder_link(srt_folder_id))

    crop: autocrop.Crop | None = None
    produced: list[dict] = []
    zip_path = workdir / "SRT_Files.zip"

    for i, v in enumerate(videos, 1):
        stem = Path(v["name"]).stem
        ep = episode_number(v["name"]) or i
        local_vid = vid_dir / f"{stem}.mp4"
        local_srt = srt_dir / f"{stem}.srt"
        pct = 5 + int((i - 1) / len(videos) * 20)  # step 1 occupies ~5–25%
        state.set_step(task_id, 1, f"Extracting subtitles ({i}/{len(videos)}): {v['name']}", pct)

        try:
            drive.download(v["id"], local_vid,
                           on_progress=lambda p, n=v["name"]: None)

            # Calculate the crop ONCE, on the first successfully-downloaded episode.
            if crop is None:
                state.log(task_id, "Calculating auto-crop from the first episode…")
                crop = autocrop.calculate_crop(str(local_vid))
                state.log(
                    task_id,
                    f"Auto-crop: x={crop.x} y={crop.y} w={crop.width} h={crop.height}",
                )

            state.log(task_id, f"OCR → {local_srt.name}")
            _run_ocr(local_vid, local_srt, crop)

            drive.upload(local_srt, local_srt.name, srt_folder_id, "text/plain")
            produced.append({"name": local_srt.name, "path": str(local_srt), "ep": ep})
            state.log(task_id, f"✓ {local_srt.name} extracted & uploaded to Drive.")
        except Exception as e:
            state.log(task_id, f"✗ SRT failed for {v['name']}: {e}", level="error")
        finally:
            # Delete the local video immediately — Step 2 re-downloads what it needs.
            if local_vid.exists():
                local_vid.unlink()

        # Re-zip after each episode so the download reflects progress.
        zip_folder(srt_dir, zip_path)
        state.add_artifact(task_id, "srts_zip",
                           f"{settings.PUBLIC_BASE_URL}/api/download/{task_id}/srts")

    if not produced:
        raise RuntimeError("Step 1 produced no SRT files.")

    state.log(task_id, f"Step 1 complete — {len(produced)} SRT file(s).")
    return {"srt_dir": srt_dir, "srts": produced, "srt_folder_id": srt_folder_id}
