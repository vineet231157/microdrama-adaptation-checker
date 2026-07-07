"""Google Drive client built from a user OAuth access token.

In Colab the notebooks used ``google.colab.auth.authenticate_user()``. On a
server we don't have that — instead the Next.js frontend performs Google OAuth
(NextAuth) with the Drive scope and forwards the *access token*. We wrap that
token in short-lived credentials and talk to the Drive v3 REST API.

Everything here is instance-based (``DriveClient``) so each job uses its own
caller's credentials — no cross-user contamination.
"""
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Iterable, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

VIDEO_EXTS = (".mp4", ".mkv", ".mov", ".webm", ".avi")
_ID_RE = re.compile(r"(?:folders|/d|id=)/?([a-zA-Z0-9_-]{20,})")
_ID_FALLBACK = re.compile(r"([a-zA-Z0-9_-]{20,})")

FOLDER_MIME = "application/vnd.google-apps.folder"


def folder_id_from_url(url: str) -> str:
    """Extract a Drive folder ID from a full URL or accept a raw ID."""
    m = _ID_RE.search(url)
    if m:
        return m.group(1)
    m = _ID_FALLBACK.search(url.strip())
    if m:
        return m.group(1)
    raise ValueError(f"Could not extract a Drive folder ID from: {url!r}")


class DriveClient:
    def __init__(self, access_token: str):
        creds = Credentials(token=access_token)
        # cache_discovery=False avoids noisy warnings + filesystem writes in containers
        self.svc = build("drive", "v3", credentials=creds, cache_discovery=False)

    @classmethod
    def from_service_account_info(cls, info: dict) -> "DriveClient":
        """Build a client from a service-account key dict (used by the Streamlit app).

        Share the target Drive folder with the service account's client_email so
        it can read the videos and create/write result folders.
        """
        from google.oauth2 import service_account

        obj = cls.__new__(cls)  # skip __init__ (no access token)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive"]
        )
        obj.svc = build("drive", "v3", credentials=creds, cache_discovery=False)
        return obj

    # ── reads ────────────────────────────────────────────────────────────
    def folder_name(self, folder_id: str) -> str:
        return self.svc.files().get(
            fileId=folder_id, fields="name", supportsAllDrives=True
        ).execute()["name"]

    def list_files(self, folder_id: str, exts: Optional[Iterable[str]] = None) -> list[dict]:
        """List non-trashed files in a folder, optionally filtered by extension."""
        exts = tuple(e.lower() for e in exts) if exts else None
        out, token = [], None
        while True:
            resp = self.svc.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="nextPageToken, files(id, name, mimeType, size)",
                orderBy="name", pageSize=200, pageToken=token,
                supportsAllDrives=True, includeItemsFromAllDrives=True,
            ).execute()
            for f in resp.get("files", []):
                if exts is None or f["name"].lower().endswith(exts):
                    out.append(f)
            token = resp.get("nextPageToken")
            if not token:
                break
        return out

    def list_videos(self, folder_id: str) -> list[dict]:
        return self.list_files(folder_id, VIDEO_EXTS)

    # ── folder management ──────────────────────────────────────────────────
    def get_or_create_subfolder(self, parent_id: str, name: str) -> str:
        existing = self.svc.files().list(
            q=(f"'{parent_id}' in parents and name='{name}' and "
               f"mimeType='{FOLDER_MIME}' and trashed=false"),
            fields="files(id, name)", supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute().get("files", [])
        if existing:
            return existing[0]["id"]
        meta = {"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}
        return self.svc.files().create(
            body=meta, fields="id", supportsAllDrives=True
        ).execute()["id"]

    @staticmethod
    def folder_link(folder_id: str) -> str:
        return f"https://drive.google.com/drive/folders/{folder_id}"

    # ── transfers ────────────────────────────────────────────────────────
    def download(self, file_id: str, local_path: Path, on_progress=None) -> Path:
        """Stream-download a Drive file to local disk in 50 MB chunks."""
        local_path = Path(local_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        req = self.svc.files().get_media(fileId=file_id, supportsAllDrives=True)
        with io.FileIO(local_path, "wb") as fh:
            dl = MediaIoBaseDownload(fh, req, chunksize=50 * 1024 * 1024)
            done = False
            while not done:
                status, done = dl.next_chunk()
                if status and on_progress:
                    on_progress(int(status.progress() * 100))
        return local_path

    def upload(self, local_path: Path, name: str, parent_id: str, mimetype: str) -> str:
        media = MediaFileUpload(str(local_path), mimetype=mimetype, resumable=True)
        up = self.svc.files().create(
            body={"name": name, "parents": [parent_id]},
            media_body=media, fields="id, name", supportsAllDrives=True,
        ).execute()
        return up["id"]
