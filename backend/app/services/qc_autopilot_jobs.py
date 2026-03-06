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
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


_jobs: dict[str, QCAutopilotJob] = {}
_jobs_lock = Lock()


def _progress_pct(job: QCAutopilotJob) -> float:
    if job.total_questions <= 0:
        return 100.0 if job.status in {"completed", "failed"} else 0.0
    pct = (job.processed_questions / job.total_questions) * 100.0
    return round(max(0.0, min(100.0, pct)), 2)


def _to_payload(job: QCAutopilotJob) -> dict:
    data = asdict(job)
    data.pop("expires_at", None)
    data["progress_pct"] = _progress_pct(job)
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
