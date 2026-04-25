from __future__ import annotations

import re
import shutil
import uuid
import zipfile
from pathlib import Path

from fastapi import UploadFile

from app.config import settings


_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def ensure_storage_dirs() -> None:
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.outputs_dir.mkdir(parents=True, exist_ok=True)


def new_job_id() -> str:
    return uuid.uuid4().hex


def safe_filename(filename: str, default: str = "image.png") -> str:
    name = Path(filename or default).name.strip() or default
    cleaned = _SAFE_NAME_RE.sub("_", name)
    return cleaned[:120] or default


def job_upload_dir(job_id: str) -> Path:
    return settings.uploads_dir / job_id


def job_output_dir(job_id: str) -> Path:
    return settings.outputs_dir / job_id


async def save_upload(upload: UploadFile, destination: Path, *, max_bytes: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with destination.open("wb") as handle:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(f"{upload.filename or 'file'} exceeds the upload size limit")
            handle.write(chunk)
    await upload.close()


def build_output_filename(input_name: str) -> str:
    stem = Path(input_name).stem or "image"
    return f"{stem}_en.png"


def build_job_zip(job_id: str) -> Path:
    output_dir = job_output_dir(job_id)
    zip_path = settings.outputs_dir / f"{job_id}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output_dir.glob("*")):
            if path.is_file():
                archive.write(path, arcname=path.name)
    return zip_path


def reset_job_dirs(job_id: str) -> None:
    shutil.rmtree(job_upload_dir(job_id), ignore_errors=True)
    shutil.rmtree(job_output_dir(job_id), ignore_errors=True)
