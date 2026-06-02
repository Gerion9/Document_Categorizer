"""In-memory background jobs for post-organization case preparation (OCR + index)."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from uuid import uuid4

log = logging.getLogger(__name__)

JOB_TTL_SECONDS = 6 * 60 * 60
_ACTIVE_STATUSES = {"queued", "running", "ocr_preparing", "indexing"}
_JOB_STORE_MAX_SIZE = 128


@dataclass
class CasePreparationJob:
    id: str
    case_id: str
    status: str = "queued"
    phase: str = "queued"
    progress_pct: float = 0.0
    progress_message: str = ""
    ocr_total_pages: int = 0
    ocr_processed_pages: int = 0
    ocr_error_pages: int = 0
    index_total_chunks: int = 0
    index_processed_chunks: int = 0
    error: Optional[str] = None
    result: Optional[dict[str, Any]] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "case_id": self.case_id,
            "status": self.status,
            "phase": self.phase,
            "progress_pct": float(self.progress_pct or 0.0),
            "progress_message": self.progress_message or "",
            "ocr_total_pages": int(self.ocr_total_pages or 0),
            "ocr_processed_pages": int(self.ocr_processed_pages or 0),
            "ocr_error_pages": int(self.ocr_error_pages or 0),
            "index_total_chunks": int(self.index_total_chunks or 0),
            "index_processed_chunks": int(self.index_processed_chunks or 0),
            "error": self.error,
            "result": self.result,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


_jobs: dict[str, CasePreparationJob] = {}
_jobs_lock = threading.Lock()


def _gc_locked(now: float) -> None:
    expired = [
        job_id
        for job_id, job in _jobs.items()
        if job.finished_at is not None and (now - job.finished_at) > JOB_TTL_SECONDS
    ]
    for job_id in expired:
        _jobs.pop(job_id, None)

    if len(_jobs) <= _JOB_STORE_MAX_SIZE:
        return
    finished = sorted(
        ((job_id, job) for job_id, job in _jobs.items() if job.finished_at is not None),
        key=lambda pair: pair[1].finished_at or 0.0,
    )
    to_drop = len(_jobs) - _JOB_STORE_MAX_SIZE
    for job_id, _ in finished[:to_drop]:
        _jobs.pop(job_id, None)


def _find_active_for_case_locked(case_id: str) -> Optional[CasePreparationJob]:
    for job in _jobs.values():
        if job.case_id == case_id and job.status in _ACTIVE_STATUSES:
            return job
    return None


def find_active_job(case_id: str) -> Optional[CasePreparationJob]:
    with _jobs_lock:
        _gc_locked(time.time())
        return _find_active_for_case_locked(case_id)


def get_job(job_id: str) -> Optional[CasePreparationJob]:
    with _jobs_lock:
        _gc_locked(time.time())
        return _jobs.get(job_id)


def start_job(
    case_id: str,
    runner: Callable[[CasePreparationJob], dict[str, Any]],
) -> CasePreparationJob:
    with _jobs_lock:
        _gc_locked(time.time())
        existing = _find_active_for_case_locked(case_id)
        if existing is not None:
            return existing

        job = CasePreparationJob(
            id=str(uuid4()),
            case_id=case_id,
            status="queued",
            phase="queued",
            progress_message="Queued",
        )
        _jobs[job.id] = job

    thread = threading.Thread(
        target=_run_job,
        args=(job, runner),
        name=f"case-prep-{case_id[:8]}-{job.id[:8]}",
        daemon=True,
    )
    thread.start()
    return job


def _run_job(job: CasePreparationJob, runner: Callable[[CasePreparationJob], dict[str, Any]]) -> None:
    job.started_at = time.time()
    job.status = "running"
    job.phase = "extracting_document"
    try:
        result = runner(job)
        job.result = result
        job.status = "completed"
        job.phase = "completed"
        job.progress_pct = 100.0
        if not job.progress_message:
            job.progress_message = "Completed"
    except Exception as exc:  # pylint: disable=broad-except
        log.exception("Case preparation job %s failed for case %s", job.id, job.case_id)
        job.status = "failed"
        job.phase = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
        job.progress_message = "Failed"
        job.result = None
    finally:
        job.finished_at = time.time()


def update_from_ocr_progress(job_id: str, payload: dict[str, int | str]) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None or job.status not in _ACTIVE_STATUSES:
            return
        total = int(payload.get("ocr_total_pages") or job.ocr_total_pages or 0)
        processed = int(payload.get("ocr_processed_pages") or 0)
        errors = int(payload.get("ocr_error_pages") or 0)
        job.status = "ocr_preparing"
        job.phase = str(payload.get("phase") or "extracting_document")
        job.ocr_total_pages = total
        job.ocr_processed_pages = processed
        job.ocr_error_pages = errors
        if total > 0:
            job.progress_pct = round(max(2.0, min(70.0, (processed / total) * 70.0)), 2)
        job.progress_message = f"Reading documents... ({processed}/{total} pages)"


def update_from_index_progress(job_id: str, payload: dict[str, int | str]) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None or job.status not in _ACTIVE_STATUSES:
            return
        total = int(payload.get("index_total_chunks") or job.index_total_chunks or 0)
        processed = int(payload.get("index_processed_chunks") or 0)
        job.status = "running"
        job.phase = "indexing_document"
        job.index_total_chunks = total
        job.index_processed_chunks = processed
        if total > 0:
            job.progress_pct = round(max(70.0, min(95.0, 70.0 + ((processed / total) * 25.0))), 2)
        else:
            job.progress_pct = 95.0
        job.progress_message = "Preparing evidence search..."


def mark_context_phase(job_id: str) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None or job.status not in _ACTIVE_STATUSES:
            return
        job.phase = "detecting_context"
        job.progress_pct = max(job.progress_pct, 96.0)
        job.progress_message = "Detecting case context..."


def wait_for_active_job(
    case_id: str,
    *,
    timeout_seconds: float = 3600.0,
    poll_seconds: float = 1.0,
) -> Optional[CasePreparationJob]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        job = find_active_job(case_id)
        if job is None:
            return get_latest_finished_job(case_id)
        time.sleep(poll_seconds)
    return find_active_job(case_id)


def get_latest_finished_job(case_id: str) -> Optional[CasePreparationJob]:
    with _jobs_lock:
        _gc_locked(time.time())
        candidates = [
            job for job in _jobs.values() if job.case_id == case_id and job.finished_at is not None
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda job: job.finished_at or 0.0)
