"""LocalSource — a drop-in stand-in for DriveClient that reads videos from a
local folder and writes "uploaded" artifacts to local sub-folders.

The 5 pipeline steps talk to an object with the DriveClient method surface
(list_videos / download / get_or_create_subfolder / upload / folder_name).
By duck-typing that surface we let scriptwriters just drag-drop video files in
the Streamlit UI — no Google Drive, no OAuth — while reusing the exact same
pipeline code that the Drive path uses.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from app.pipeline.common import episode_number

# Kept in sync with app.drive.VIDEO_EXTS but defined locally so the drag-drop
# upload path doesn't need the Google SDK importable.
VIDEO_EXTS = (".mp4", ".mkv", ".mov", ".webm", ".avi")


class LocalSource:
    def __init__(self, videos_dir: str | Path, out_root: str | Path):
        self.videos_dir = Path(videos_dir)
        self.out_root = Path(out_root)
        self.out_root.mkdir(parents=True, exist_ok=True)

    # ── reads ──────────────────────────────────────────────────────────────
    def folder_name(self, folder_id: str) -> str:
        return Path(folder_id).name or "Uploaded Videos"

    def list_files(self, folder_id: str, exts=None) -> list[dict]:
        exts = tuple(e.lower() for e in exts) if exts else None
        out = []
        for f in sorted(Path(folder_id).iterdir()):
            if f.is_file() and (exts is None or f.name.lower().endswith(exts)):
                out.append({"id": str(f), "name": f.name})
        return out

    def list_videos(self, folder_id: str) -> list[dict]:
        vids = self.list_files(folder_id, VIDEO_EXTS)
        vids.sort(key=lambda v: (episode_number(v["name"]) is None,
                                 episode_number(v["name"]) or 0, v["name"]))
        return vids

    # ── folders / transfers (all local copies) ──────────────────────────────
    def get_or_create_subfolder(self, parent_id: str, name: str) -> str:
        d = self.out_root / name
        d.mkdir(parents=True, exist_ok=True)
        return str(d)

    def download(self, file_id: str, local_path, on_progress=None):
        local_path = Path(local_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_id, local_path)  # file_id IS the source path here
        if on_progress:
            on_progress(100)
        return local_path

    def upload(self, local_path, name: str, parent_id: str, mimetype: str) -> str:
        dest = Path(parent_id) / name
        shutil.copy2(local_path, dest)
        return str(dest)

    @staticmethod
    def folder_link(folder_id: str) -> str:  # not a real URL in local mode
        return ""
