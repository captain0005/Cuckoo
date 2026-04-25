from __future__ import annotations

from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.jobs import JobFile, TranslationJob, job_store
from app.pipeline import ImageTranslationPipeline
from app.storage import (
    build_job_zip,
    build_output_filename,
    ensure_storage_dirs,
    job_output_dir,
    job_upload_dir,
    new_job_id,
    safe_filename,
    save_upload,
)

app = FastAPI(title=settings.app_name, version="0.1.0")

ensure_storage_dirs()
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/files", StaticFiles(directory=str(settings.outputs_dir)), name="files")


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_name}


@app.post("/api/jobs", status_code=202)
async def create_job(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    source_language: str = Form(default=settings.source_language),
    target_language: str = Form(default=settings.target_language),
):
    if not files:
        raise HTTPException(status_code=400, detail="At least one image is required.")
    if len(files) > settings.max_batch_size:
        raise HTTPException(
            status_code=400,
            detail=f"Batch size exceeds {settings.max_batch_size} images.",
        )

    job_id = new_job_id()
    upload_dir = job_upload_dir(job_id)
    output_dir = job_output_dir(job_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    max_bytes = settings.max_upload_mb * 1024 * 1024
    job_files: list[JobFile] = []
    for index, upload in enumerate(files, start=1):
        filename = safe_filename(upload.filename or f"image_{index}.png")
        input_path = upload_dir / filename
        try:
            await save_upload(upload, input_path, max_bytes=max_bytes)
        except ValueError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc

        output_name = build_output_filename(filename)
        job_files.append(
            JobFile(
                source_filename=filename,
                input_path=input_path,
                output_path=output_dir / output_name,
            )
        )

    job = TranslationJob(
        job_id=job_id,
        status="queued",
        source_language=source_language,
        target_language=target_language,
        total=len(job_files),
        files=job_files,
    )
    job_store.add(job)
    background_tasks.add_task(_run_job, job_id)

    return _job_payload(job)


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return _job_payload(job)


@app.get("/api/jobs/{job_id}/download")
async def download_job(job_id: str):
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status != "completed":
        raise HTTPException(status_code=409, detail="Job is not completed yet.")
    zip_path = build_job_zip(job_id)
    return FileResponse(zip_path, filename=f"cuckoo-{job_id}.zip", media_type="application/zip")


def _run_job(job_id: str) -> None:
    job = job_store.get(job_id)
    if job is None:
        return
    job_store.mark_processing(job_id)
    pipeline = ImageTranslationPipeline(
        source_language=job.source_language,
        target_language=job.target_language,
    )

    try:
        for item in job.files:
            result = pipeline.process_image(
                input_path=item.input_path,
                output_path=item.output_path,
                source_filename=item.source_filename,
            )
            job_store.add_result(job_id, result)
        job_store.mark_completed(job_id)
    except Exception as exc:
        job_store.mark_failed(job_id, str(exc))


def _job_payload(job: TranslationJob) -> dict[str, object]:
    return {
        "job_id": job.job_id,
        "status": job.status,
        "progress": job.progress,
        "completed": job.completed,
        "total": job.total,
        "source_language": job.source_language,
        "target_language": job.target_language,
        "error": job.error,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "download_url": f"/api/jobs/{job.job_id}/download" if job.status == "completed" else None,
        "results": [
            result.to_dict(file_url=_file_url(job.job_id, result.output_path))
            for result in job.results
        ],
    }


def _file_url(job_id: str, output_path: Path) -> str:
    return f"/files/{job_id}/{output_path.name}"
