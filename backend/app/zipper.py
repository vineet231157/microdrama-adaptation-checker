"""Zip helpers for exposing intermediate folders as downloadable archives."""
from __future__ import annotations

import zipfile
from pathlib import Path


def zip_folder(src_dir: Path, out_zip: Path) -> Path:
    """Zip every file under ``src_dir`` (recursively) into ``out_zip``.

    The archive is rebuilt each time it is called, so it always reflects the
    current contents — this is what lets the frontend download partial results
    (e.g. SRTs) before the whole pipeline finishes.
    """
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(src_dir.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(src_dir))
    return out_zip


def zip_files(files: list[Path], out_zip: Path) -> Path:
    """Zip an explicit list of files (flattened, using their basenames)."""
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            if f and Path(f).is_file():
                zf.write(f, Path(f).name)
    return out_zip
