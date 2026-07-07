"""STEP 2 — Multimodal video → director-ready screenplay (Model 2).

For each episode: download the video, match its SRT, upload the video to the
Gemini File API, generate the screenplay with dialogue locked to the SRT, save
.md + .pdf locally, upload both to a new ``Individual_Screenplays_[ts]`` Drive
folder, DELETE the Gemini file + local .mp4 immediately, and re-zip after each
episode so the frontend can download partial results.
"""
from __future__ import annotations

from pathlib import Path

from .. import state
from ..config import settings
from ..drive import DriveClient
from ..zipper import zip_folder
from .common import episode_number, parse_srt_text, sanitize
from .pdf import text_to_pdf
from .prompts import SCREENPLAY_SYSTEM_INSTRUCTION, build_screenplay_prompt


def run(
    task_id: str,
    drive: DriveClient,
    source_folder_id: str,
    srts: list[dict],
    show_title: str,
    workdir: Path,
    max_episodes: int = 0,
) -> dict:
    """Returns {'screenplay_dir', 'episodes': [{ep, screenplay, md, pdf}], 'folder_id'}."""
    from .. import gemini  # lazy — heavy AI SDK only needed at run time

    sp_dir = workdir / "Screenplays"
    vid_dir = workdir / "_videos"
    sp_dir.mkdir(parents=True, exist_ok=True)
    vid_dir.mkdir(parents=True, exist_ok=True)

    videos = drive.list_videos(source_folder_id)
    videos.sort(key=lambda v: (episode_number(v["name"]) is None,
                               episode_number(v["name"]) or 0, v["name"]))
    if max_episodes and max_episodes > 0:
        videos = videos[:max_episodes]

    # Create/reuse a "Screenplays" folder inside the source folder (matches the
    # original notebook's OUTPUT_FOLDER_NAME).
    out_id = drive.get_or_create_subfolder(source_folder_id, "Screenplays")
    state.set_drive_link(task_id, "screenplay_folder", DriveClient.folder_link(out_id))

    session = gemini.GeminiSession(SCREENPLAY_SYSTEM_INSTRUCTION)
    safe_show = sanitize(show_title) or "Show"
    zip_path = workdir / "Screenplays.zip"
    episodes: list[dict] = []

    for i, v in enumerate(videos, 1):
        ep = episode_number(v["name"]) or i
        srt = next((s for s in srts if s["ep"] == ep), None)
        pct = 25 + int((i - 1) / max(len(videos), 1) * 35)  # step 2 occupies ~25–60%
        state.set_step(task_id, 2, f"Writing screenplay ({i}/{len(videos)}): Episode {ep}", pct)

        if not srt:
            state.log(task_id, f"✗ Episode {ep}: no matching SRT, skipping.", level="error")
            continue

        local_vid = vid_dir / f"_ep_{ep}.mp4"
        gem_file = None
        try:
            drive.download(v["id"], local_vid)
            srt_text = parse_srt_text(srt["path"])

            state.log(task_id, f"Episode {ep}: uploading video to Gemini…")
            gem_file = gemini.upload_video(local_vid)

            state.log(task_id, f"Episode {ep}: generating screenplay ({session.model_name or settings.GEMINI_MODEL})…")
            prompt = build_screenplay_prompt(ep, show_title, srt_text)
            screenplay = session.generate([gem_file, prompt]).strip()

            base = f"{safe_show}__Episode_{ep:02d}"
            md_local = sp_dir / f"{base}.md"
            pdf_local = sp_dir / f"{base}.pdf"
            header = (f"# {show_title} — Episode {ep}\n\n"
                      f"*Director-ready screenplay — dialogue kept verbatim.*\n\n")
            md_local.write_text(header + screenplay, encoding="utf-8")
            text_to_pdf(screenplay, pdf_local, f"{show_title} — Episode {ep}")

            drive.upload(md_local, md_local.name, out_id, "text/markdown")
            drive.upload(pdf_local, pdf_local.name, out_id, "application/pdf")

            episodes.append({"ep": ep, "screenplay": screenplay,
                             "md": str(md_local), "pdf": str(pdf_local)})
            state.log(task_id, f"✓ Episode {ep} screenplay generated & uploaded.")
        except Exception as e:
            state.log(task_id, f"✗ Episode {ep} failed: {e}", level="error")
        finally:
            if gem_file is not None:
                gemini.delete_video(gem_file.name)  # free Gemini quota immediately
                state.log(task_id, f"Episode {ep}: deleted video from Gemini storage.")
            if local_vid.exists():
                local_vid.unlink()  # free disk immediately

        zip_folder(sp_dir, zip_path)
        state.add_artifact(task_id, "screenplays_zip",
                           f"{settings.PUBLIC_BASE_URL}/api/download/{task_id}/screenplays")

    if not episodes:
        raise RuntimeError("Step 2 produced no screenplays.")

    episodes.sort(key=lambda e: e["ep"])
    state.log(task_id, f"Step 2 complete — {len(episodes)} screenplay(s).")
    return {"screenplay_dir": sp_dir, "episodes": episodes, "folder_id": out_id}
