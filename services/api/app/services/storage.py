"""Dataset storage, content fingerprinting and safe file handling.

Uploaded bytes are validated in memory and written to a *generated* path. The original
filename is never used on disk — only stored as sanitised metadata — which removes path
traversal and content-sniffing risks from the storage layer.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import tempfile
from pathlib import Path

import pandas as pd

from ..config import settings

UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._ -]")
MAX_FILENAME_LENGTH = 120


def safe_filename(name: str | None, *, fallback: str = "upload.csv") -> str:
    """Return a display-only filename with no directory components or control characters."""

    if not name:
        return fallback
    base = os.path.basename(name.replace("\\", "/")).strip()
    base = UNSAFE_NAME_CHARS.sub("_", base)
    base = base.lstrip(".") or fallback
    if not base.lower().endswith(".csv"):
        base = f"{base}.csv"
    return base[:MAX_FILENAME_LENGTH]


def canonical_csv(frame: pd.DataFrame) -> str:
    """Deterministic CSV text for a validated frame (sorted rows, fixed formatting)."""

    ordered = frame.sort_values(["store", "item", "date"]).reset_index(drop=True)
    buffer = io.StringIO()
    ordered.to_csv(
        buffer,
        index=False,
        columns=(
            ["date", "store", "item", "sales", "on_hand"]
            if "on_hand" in ordered.columns
            else ["date", "store", "item", "sales"]
        ),
        date_format="%Y-%m-%d",
        float_format="%.4f",
        lineterminator="\n",
    )
    return buffer.getvalue()


def fingerprint(frame: pd.DataFrame) -> str:
    """Content-derived dataset version id: SHA-256 over the canonical CSV."""

    digest = hashlib.sha256(canonical_csv(frame).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def dataset_dir(org_id: int, dataset_id: int) -> Path:
    path = Path(settings.data_dir) / "datasets" / str(org_id) / str(dataset_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def version_path(org_id: int, dataset_id: int, version: int, content_fingerprint: str) -> Path:
    short = content_fingerprint.split(":", 1)[-1][:12]
    return dataset_dir(org_id, dataset_id) / f"v{version}-{short}.csv"


def write_version_file(path: Path, text: str) -> int:
    """Atomically write the canonical CSV; returns the byte size."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=".upload-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return path.stat().st_size


def read_version_frame(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path)


def cleanup_temp_dir() -> None:
    """Remove abandoned ``.upload-*.tmp`` files left by crashed requests."""

    root = Path(settings.data_dir) / "datasets"
    if not root.exists():
        return
    for candidate in root.rglob(".upload-*.tmp"):
        candidate.unlink(missing_ok=True)


# --- Preview cache -----------------------------------------------------------------------
#
# "Preview before import" keeps the validated frame server-side for a short window so the
# confirm step cannot race with a different upload and no untrusted bytes are re-parsed.
# Expired previews are swept on every new preview request and on application startup.

PREVIEW_TTL_SECONDS = 1800
_PREVIEW_ID = re.compile(r"^[a-f0-9]{32}$")


def _preview_dir() -> Path:
    path = Path(settings.data_dir) / "previews"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_preview(csv_text: str, quality: dict) -> str:
    import json
    import uuid

    sweep_previews()
    preview_id = uuid.uuid4().hex
    directory = _preview_dir()
    (directory / f"{preview_id}.csv").write_text(csv_text, encoding="utf-8")
    (directory / f"{preview_id}.json").write_text(json.dumps(quality), encoding="utf-8")
    meta = directory / f"{preview_id}.meta"
    meta.write_text(str(int(__import__("time").time())), encoding="utf-8")
    return preview_id


def _preview_paths(preview_id: str) -> tuple[Path, Path, Path]:
    if not _PREVIEW_ID.match(preview_id or ""):
        raise ValueError("invalid preview id")
    directory = _preview_dir()
    return (
        directory / f"{preview_id}.csv",
        directory / f"{preview_id}.json",
        directory / f"{preview_id}.meta",
    )


def load_preview(preview_id: str) -> tuple[str, dict]:
    import json
    import time

    csv_path, quality_path, meta_path = _preview_paths(preview_id)
    if not csv_path.exists() or not meta_path.exists():
        raise FileNotFoundError(preview_id)
    created = int(meta_path.read_text(encoding="utf-8").strip() or 0)
    if time.time() - created > PREVIEW_TTL_SECONDS:
        delete_preview(preview_id)
        raise FileNotFoundError(preview_id)
    quality = json.loads(quality_path.read_text(encoding="utf-8")) if quality_path.exists() else {}
    return csv_path.read_text(encoding="utf-8"), quality


def delete_preview(preview_id: str) -> None:
    try:
        paths = _preview_paths(preview_id)
    except ValueError:
        return
    for path in paths:
        path.unlink(missing_ok=True)


def sweep_previews(now: float | None = None) -> int:
    import time

    directory = _preview_dir()
    cutoff = (now or time.time()) - PREVIEW_TTL_SECONDS
    removed = 0
    for meta in directory.glob("*.meta"):
        try:
            created = int(meta.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            created = 0
        if created < cutoff:
            delete_preview(meta.stem)
            removed += 1
    for orphan in list(directory.glob(".upload-*.tmp")):
        orphan.unlink(missing_ok=True)
    return removed
