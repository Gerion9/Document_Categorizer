"""In-memory job store for QC checklist AI Autopilot."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Optional
from uuid import uuid4

JOB_TTL_SECONDS = 6 * 60 * 60  # 6 hours
ACTIVE_STATUSES = {"queued", "running"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class QCAutopilotJob:
    id: str
    checklist_id: str
    case_id: Optional[str]
    status: str
    phase: str
    total_questions: int
    processed_questions: int
    verified: int
    skipped: int
    errors: int
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime
    ocr_total_pages: int = 0
    ocr_processed_pages: int = 0
    ocr_error_pages: int = 0
    index_total_chunks: int = 0
    index_processed_chunks: int = 0
    index_error_chunks: int = 0
    evidence_total_questions: int = 0
    evidence_processed_questions: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


_jobs: dict[str, QCAutopilotJob] = {}
_jobs_lock = Lock()


def _safe_pct(processed: int, total: int) -> float:
    if total <= 0:
        return 100.0 if processed > 0 else 0.0
    pct = (processed / total) * 100.0
    return round(max(0.0, min(100.0, pct)), 2)


def _phase_progress_pct(job: QCAutopilotJob) -> float:
    if job.status in {"completed", "failed"} and job.phase == "completed":
        return 100.0
    if job.phase == "extracting_document":
        return _safe_pct(job.ocr_processed_pages + job.ocr_error_pages, job.ocr_total_pages)
    if job.phase == "writing_json":
        return 100.0
    if job.phase == "indexing_document":
        return _safe_pct(job.index_processed_chunks + job.index_error_chunks, job.index_total_chunks)
    if job.phase == "gathering_evidence":
        return _safe_pct(job.evidence_processed_questions, job.evidence_total_questions or job.total_questions)
    if job.phase == "verifying_questions":
        return _safe_pct(job.processed_questions, job.total_questions)
    if job.phase == "completed":
        return 100.0
    return 0.0


def _overall_progress_pct(job: QCAutopilotJob) -> float:
    phase_pct = _phase_progress_pct(job) / 100.0
    ranges = {
        "queued": (0.0, 0.0),
        "loading_questions": (0.0, 0.02),
        "extracting_document": (0.02, 0.45),
        "writing_json": (0.45, 0.50),
        "indexing_document": (0.50, 0.65),
        "gathering_evidence": (0.65, 0.80),
        "verifying_questions": (0.80, 1.00),
        "completed": (1.00, 1.00),
        "failed": (0.0, 1.0),
    }
    start, end = ranges.get(job.phase, (0.0, 1.0))
    if job.phase == "failed":
        if job.processed_questions or job.total_questions:
            return _safe_pct(job.processed_questions, job.total_questions)
        if job.evidence_processed_questions or job.evidence_total_questions:
            return _safe_pct(job.evidence_processed_questions, job.evidence_total_questions)
        if job.index_processed_chunks or job.index_total_chunks:
            return _safe_pct(job.index_processed_chunks + job.index_error_chunks, job.index_total_chunks)
        if job.ocr_processed_pages or job.ocr_total_pages:
            return _safe_pct(job.ocr_processed_pages + job.ocr_error_pages, job.ocr_total_pages)
        return 0.0
    overall = (start + ((end - start) * phase_pct)) * 100.0
    return round(max(0.0, min(100.0, overall)), 2)


def _to_payload(job: QCAutopilotJob) -> dict:
    data = asdict(job)
    data.pop("expires_at", None)
    data["phase_progress_pct"] = _phase_progress_pct(job)
    data["overall_progress_pct"] = _overall_progress_pct(job)
    data["progress_pct"] = data["overall_progress_pct"]
    return data


def _touch(job: QCAutopilotJob, now: datetime) -> None:
    job.updated_at = now
    job.expires_at = now + timedelta(seconds=JOB_TTL_SECONDS)


def _cleanup_locked(now: datetime) -> None:
    expired_ids = [
        job_id
        for job_id, job in _jobs.items()
        if job.expires_at is not None and job.expires_at <= now
    ]
    for job_id in expired_ids:
        _jobs.pop(job_id, None)


def create_job(checklist_id: str, case_id: Optional[str], total_questions: int = 0) -> dict:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        job = QCAutopilotJob(
            id=str(uuid4()),
            checklist_id=checklist_id,
            case_id=case_id,
            status="queued",
            phase="queued",
            total_questions=max(0, total_questions),
            processed_questions=0,
            verified=0,
            skipped=0,
            errors=0,
            error_message=None,
            created_at=now,
            updated_at=now,
            evidence_total_questions=max(0, total_questions),
            started_at=None,
            completed_at=None,
            expires_at=now + timedelta(seconds=JOB_TTL_SECONDS),
        )
        _jobs[job.id] = job
        return _to_payload(job)


def get_job(job_id: str) -> Optional[dict]:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        job = _jobs.get(job_id)
        if not job:
            return None
        return _to_payload(job)


def get_active_job_for_checklist(checklist_id: str) -> Optional[dict]:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        for job in _jobs.values():
            if job.checklist_id == checklist_id and job.status in ACTIVE_STATUSES:
                return _to_payload(job)
        return None


def set_total_questions(job_id: str, total_questions: int) -> Optional[dict]:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        job = _jobs.get(job_id)
        if not job:
            return None
        job.total_questions = max(0, total_questions)
        job.evidence_total_questions = max(0, total_questions)
        _touch(job, now)
        return _to_payload(job)


def mark_running(job_id: str, phase: str = "running") -> Optional[dict]:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        job = _jobs.get(job_id)
        if not job:
            return None
        job.status = "running"
        job.phase = phase
        if job.started_at is None:
            job.started_at = now
        _touch(job, now)
        return _to_payload(job)


def update_progress(
    job_id: str,
    *,
    processed_delta: int = 0,
    verified_delta: int = 0,
    skipped_delta: int = 0,
    errors_delta: int = 0,
    phase: Optional[str] = None,
    error_message: Optional[str] = None,
) -> Optional[dict]:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        job = _jobs.get(job_id)
        if not job:
            return None

        job.processed_questions = max(0, job.processed_questions + processed_delta)
        job.verified = max(0, job.verified + verified_delta)
        job.skipped = max(0, job.skipped + skipped_delta)
        job.errors = max(0, job.errors + errors_delta)

        if job.total_questions > 0 and job.processed_questions > job.total_questions:
            job.processed_questions = job.total_questions
        if phase is not None:
            job.phase = phase
        if error_message:
            job.error_message = error_message[:500]
        _touch(job, now)
        return _to_payload(job)


def set_ocr_total(job_id: str, total_pages: int, *, phase: str = "extracting_document") -> Optional[dict]:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        job = _jobs.get(job_id)
        if not job:
            return None
        job.phase = phase
        job.ocr_total_pages = max(0, total_pages)
        _touch(job, now)
        return _to_payload(job)


def update_ocr_progress(
    job_id: str,
    *,
    processed_pages: int | None = None,
    error_pages: int | None = None,
    phase: str = "extracting_document",
) -> Optional[dict]:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        job = _jobs.get(job_id)
        if not job:
            return None
        job.phase = phase
        if processed_pages is not None:
            job.ocr_processed_pages = max(0, processed_pages)
        if error_pages is not None:
            job.ocr_error_pages = max(0, error_pages)
        _touch(job, now)
        return _to_payload(job)


def set_index_total(job_id: str, total_chunks: int, *, phase: str = "indexing_document") -> Optional[dict]:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        job = _jobs.get(job_id)
        if not job:
            return None
        job.phase = phase
        job.index_total_chunks = max(0, total_chunks)
        _touch(job, now)
        return _to_payload(job)


def update_index_progress(
    job_id: str,
    *,
    processed_chunks: int | None = None,
    error_chunks: int | None = None,
    phase: str = "indexing_document",
) -> Optional[dict]:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        job = _jobs.get(job_id)
        if not job:
            return None
        job.phase = phase
        if processed_chunks is not None:
            job.index_processed_chunks = max(0, processed_chunks)
        if error_chunks is not None:
            job.index_error_chunks = max(0, error_chunks)
        _touch(job, now)
        return _to_payload(job)


def set_evidence_total(job_id: str, total_questions: int, *, phase: str = "gathering_evidence") -> Optional[dict]:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        job = _jobs.get(job_id)
        if not job:
            return None
        job.phase = phase
        job.evidence_total_questions = max(0, total_questions)
        _touch(job, now)
        return _to_payload(job)


def update_evidence_progress(
    job_id: str,
    *,
    processed_questions: int | None = None,
    phase: str = "gathering_evidence",
) -> Optional[dict]:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        job = _jobs.get(job_id)
        if not job:
            return None
        job.phase = phase
        if processed_questions is not None:
            job.evidence_processed_questions = max(0, processed_questions)
        _touch(job, now)
        return _to_payload(job)


def mark_completed(job_id: str, phase: str = "completed") -> Optional[dict]:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        job = _jobs.get(job_id)
        if not job:
            return None
        job.status = "completed"
        job.phase = phase
        if job.total_questions > 0:
            job.processed_questions = min(job.processed_questions, job.total_questions)
        job.completed_at = now
        _touch(job, now)
        return _to_payload(job)


def mark_failed(job_id: str, error_message: str, phase: str = "failed") -> Optional[dict]:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        job = _jobs.get(job_id)
        if not job:
            return None
        job.status = "failed"
        job.phase = phase
        job.error_message = (error_message or "Unknown error")[:500]
        job.completed_at = now
        _touch(job, now)
        return _to_payload(job)
