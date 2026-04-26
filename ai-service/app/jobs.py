from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from app.pipeline import ImageTranslationResult


@dataclass(slots=True)
class JobFile:
    source_filename: str
    input_path: Path
    output_path: Path


@dataclass(slots=True)
class TranslationJob:
    job_id: str
    status: str
    source_language: str
    target_language: str
    total: int
    completed: int = 0
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    files: list[JobFile] = field(default_factory=list)
    results: list[ImageTranslationResult] = field(default_factory=list)

    @property
    def progress(self) -> float:
        if self.total <= 0:
            return 0.0
        return round((self.completed / self.total) * 100, 2)


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, TranslationJob] = {}
        self._lock = Lock()

    def add(self, job: TranslationJob) -> None:
        with self._lock:
            self._jobs[job.job_id] = job

    def get(self, job_id: str) -> TranslationJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def mark_processing(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = "processing"
            job.updated_at = datetime.now(timezone.utc)

    def add_result(self, job_id: str, result: ImageTranslationResult) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.results.append(result)
            job.completed += 1
            job.updated_at = datetime.now(timezone.utc)

    def mark_completed(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = "completed"
            job.updated_at = datetime.now(timezone.utc)

    def mark_failed(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = "failed"
            job.error = error
            job.updated_at = datetime.now(timezone.utc)


job_store = JobStore()
