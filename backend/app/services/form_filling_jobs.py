"""In-memory runtime job store for PDF form filling."""

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
class FormFillingRuntimeJob:
    id: str
    case_id: str
    form_type: Optional[str]
    status: str
    phase: str
    progress_pct: float
    preparation_progress_pct: float
    original_pdf_path: str
    filled_pdf_path: str
    field_count: int
    filled_count: int
    matched_fields: int
    evidence_total_fields: int
    evidence_processed_fields: int
    extracted_fields: int
    failed_fields: int
    written_fields: int
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


_jobs: dict[str, FormFillingRuntimeJob] = {}
_jobs_lock = Lock()


def _safe_pct(processed: int, total: int) -> float:
    if total <= 0:
        return 100.0 if processed > 0 else 0.0
    pct = (processed / total) * 100.0
    return round(max(0.0, min(100.0, pct)), 2)


def _phase_progress_pct(job: FormFillingRuntimeJob) -> float:
    if job.status in {"completed", "failed", "needs_review"} and job.phase in {"completed", "needs_review"}:
        return 100.0
    if job.phase == "queued":
        return 0.0
    if job.phase == "preparing_case":
        return round(max(0.0, min(100.0, float(job.preparation_progress_pct or 0.0))), 2)
    if job.phase == "detecting_fields":
        return 100.0 if job.field_count >= 0 and job.updated_at != job.created_at else 0.0
    if job.phase == "matching_form":
        return _safe_pct(job.matched_fields, job.field_count or max(1, job.matched_fields))
    if job.phase == "gathering_evidence":
        return _safe_pct(job.evidence_processed_fields, job.evidence_total_fields or job.field_count)
    if job.phase == "extracting_values":
        return _safe_pct(job.extracted_fields + job.failed_fields, job.field_count)
    if job.phase in {"writing_pdf", "regenerating_pdf"}:
        baseline = job.field_count if job.field_count > 0 else max(job.filled_count, 1)
        return _safe_pct(job.written_fields, baseline)
    if job.phase == "completed":
        return 100.0
    return 0.0


def _overall_progress_pct(job: FormFillingRuntimeJob) -> float:
    phase_pct = _phase_progress_pct(job) / 100.0
    ranges = {
        "queued": (0.0, 0.0),
        "preparing_case": (0.0, 0.20),
        "detecting_fields": (0.20, 0.30),
        "matching_form": (0.30, 0.40),
        "gathering_evidence": (0.40, 0.65),
        "extracting_values": (0.65, 0.90),
        "writing_pdf": (0.90, 1.00),
        "regenerating_pdf": (0.90, 1.00),
        "completed": (1.00, 1.00),
        "needs_review": (1.00, 1.00),
        "failed": (0.0, 1.0),
    }
    start, end = ranges.get(job.phase, (0.0, 1.0))
    if job.phase == "failed":
        if (
            job.preparation_progress_pct
            and not job.field_count
            and not job.matched_fields
            and not job.extracted_fields
            and not job.written_fields
        ):
            return round(20.0 * (max(0.0, min(100.0, float(job.preparation_progress_pct or 0.0))) / 100.0), 2)
        if job.written_fields or job.field_count:
            return _safe_pct(job.written_fields, job.field_count)
        if job.extracted_fields or job.failed_fields or job.field_count:
            return _safe_pct(job.extracted_fields + job.failed_fields, job.field_count)
        if job.evidence_processed_fields or job.evidence_total_fields:
            return _safe_pct(job.evidence_processed_fields, job.evidence_total_fields)
        if job.matched_fields or job.field_count:
            return _safe_pct(job.matched_fields, job.field_count)
        return 0.0
    overall = (start + ((end - start) * phase_pct)) * 100.0
    return round(max(0.0, min(100.0, overall)), 2)


def _to_payload(job: FormFillingRuntimeJob) -> dict:
    data = asdict(job)
    data.pop("expires_at", None)
    data["phase_progress_pct"] = _phase_progress_pct(job)
    data["overall_progress_pct"] = _overall_progress_pct(job)
    data["progress_pct"] = data["overall_progress_pct"]
    return data


def _touch(job: FormFillingRuntimeJob, now: datetime) -> None:
    job.updated_at = now
    job.expires_at = now + timedelta(seconds=JOB_TTL_SECONDS)
    job.progress_pct = _overall_progress_pct(job)


def _cleanup_locked(now: datetime) -> None:
    expired_ids = [
        job_id
        for job_id, job in _jobs.items()
        if job.expires_at is not None and job.expires_at <= now
    ]
    for job_id in expired_ids:
        _jobs.pop(job_id, None)


def create_job(
    *,
    case_id: str,
    original_pdf_path: str = "",
    form_type: str | None = None,
    field_count: int = 0,
    job_id: str | None = None,
) -> dict:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        resolved_job_id = str(job_id or uuid4())
        current = _jobs.get(resolved_job_id)
        if current:
            return _to_payload(current)
        job = FormFillingRuntimeJob(
            id=resolved_job_id,
            case_id=case_id,
            form_type=form_type,
            status="queued",
            phase="queued",
            progress_pct=0.0,
            preparation_progress_pct=0.0,
            original_pdf_path=original_pdf_path,
            filled_pdf_path="",
            field_count=max(0, field_count),
            filled_count=0,
            matched_fields=0,
            evidence_total_fields=max(0, field_count),
            evidence_processed_fields=0,
            extracted_fields=0,
            failed_fields=0,
            written_fields=0,
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


def delete_job(job_id: str) -> None:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        if job_id in _jobs:
            del _jobs[job_id]


def list_jobs_for_case(case_id: str) -> list[dict]:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        jobs = [job for job in _jobs.values() if job.case_id == case_id]
        jobs.sort(key=lambda item: item.created_at, reverse=True)
        return [_to_payload(job) for job in jobs]


def get_active_job_for_case(case_id: str) -> Optional[dict]:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        for job in sorted(_jobs.values(), key=lambda item: item.created_at, reverse=True):
            if job.case_id == case_id and job.status in ACTIVE_STATUSES:
                return _to_payload(job)
        return None


def mark_running(job_id: str, *, phase: str = "running") -> Optional[dict]:
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


def set_form_type(job_id: str, form_type: str | None) -> Optional[dict]:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        job = _jobs.get(job_id)
        if not job:
            return None
        job.form_type = form_type
        _touch(job, now)
        return _to_payload(job)


def set_pdf_paths(
    job_id: str,
    *,
    original_pdf_path: str | None = None,
    filled_pdf_path: str | None = None,
) -> Optional[dict]:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        job = _jobs.get(job_id)
        if not job:
            return None
        if original_pdf_path is not None:
            job.original_pdf_path = original_pdf_path
        if filled_pdf_path is not None:
            job.filled_pdf_path = filled_pdf_path
        _touch(job, now)
        return _to_payload(job)


def reset_job(
    job_id: str,
    *,
    phase: str = "queued",
    form_type: str | None = None,
    original_pdf_path: str | None = None,
    field_count: int | None = None,
) -> Optional[dict]:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        job = _jobs.get(job_id)
        if not job:
            return None
        job.status = "queued"
        job.phase = phase
        job.progress_pct = 0.0
        job.preparation_progress_pct = 0.0
        if form_type is not None:
            job.form_type = form_type
        if original_pdf_path is not None:
            job.original_pdf_path = original_pdf_path
        if field_count is not None:
            job.field_count = max(0, field_count)
            job.evidence_total_fields = max(0, field_count)
        job.filled_pdf_path = ""
        job.filled_count = 0
        job.matched_fields = 0
        job.evidence_processed_fields = 0
        job.extracted_fields = 0
        job.failed_fields = 0
        job.written_fields = 0
        job.error_message = None
        job.started_at = None
        job.completed_at = None
        _touch(job, now)
        return _to_payload(job)


def set_field_total(job_id: str, total_fields: int, *, phase: str = "detecting_fields") -> Optional[dict]:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        job = _jobs.get(job_id)
        if not job:
            return None
        job.phase = phase
        job.preparation_progress_pct = 0.0
        job.field_count = max(0, total_fields)
        job.evidence_total_fields = max(0, total_fields)
        _touch(job, now)
        return _to_payload(job)


def update_preparation_progress(
    job_id: str,
    *,
    progress_pct: float | int | None = None,
    phase: str = "preparing_case",
) -> Optional[dict]:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        job = _jobs.get(job_id)
        if not job:
            return None
        job.phase = phase
        if progress_pct is not None:
            try:
                job.preparation_progress_pct = round(
                    max(0.0, min(100.0, float(progress_pct or 0.0))),
                    2,
                )
            except (TypeError, ValueError):
                pass
        _touch(job, now)
        return _to_payload(job)


def update_matching_progress(
    job_id: str,
    *,
    matched_fields: int | None = None,
    phase: str = "matching_form",
) -> Optional[dict]:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        job = _jobs.get(job_id)
        if not job:
            return None
        job.phase = phase
        if matched_fields is not None:
            job.matched_fields = max(0, min(int(matched_fields), max(job.field_count, 0) or int(matched_fields)))
        _touch(job, now)
        return _to_payload(job)


def set_evidence_total(job_id: str, total_fields: int, *, phase: str = "gathering_evidence") -> Optional[dict]:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        job = _jobs.get(job_id)
        if not job:
            return None
        job.phase = phase
        job.evidence_total_fields = max(0, total_fields)
        _touch(job, now)
        return _to_payload(job)


def update_evidence_progress(
    job_id: str,
    *,
    processed_fields: int | None = None,
    phase: str = "gathering_evidence",
) -> Optional[dict]:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        job = _jobs.get(job_id)
        if not job:
            return None
        job.phase = phase
        if processed_fields is not None:
            job.evidence_processed_fields = max(0, processed_fields)
        _touch(job, now)
        return _to_payload(job)


def update_extraction_progress(
    job_id: str,
    *,
    extracted_fields: int | None = None,
    filled_count: int | None = None,
    failed_fields: int | None = None,
    phase: str = "extracting_values",
) -> Optional[dict]:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        job = _jobs.get(job_id)
        if not job:
            return None
        job.phase = phase
        if extracted_fields is not None:
            job.extracted_fields = max(0, extracted_fields)
        if filled_count is not None:
            job.filled_count = max(0, filled_count)
        if failed_fields is not None:
            job.failed_fields = max(0, failed_fields)
        _touch(job, now)
        return _to_payload(job)


def update_writing_progress(
    job_id: str,
    *,
    written_fields: int | None = None,
    filled_pdf_path: str | None = None,
    filled_count: int | None = None,
    phase: str = "writing_pdf",
) -> Optional[dict]:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        job = _jobs.get(job_id)
        if not job:
            return None
        job.phase = phase
        if written_fields is not None:
            job.written_fields = max(0, written_fields)
        if filled_count is not None:
            job.filled_count = max(0, filled_count)
        if filled_pdf_path is not None:
            job.filled_pdf_path = filled_pdf_path
        _touch(job, now)
        return _to_payload(job)


def mark_completed(job_id: str, *, phase: str = "completed") -> Optional[dict]:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        job = _jobs.get(job_id)
        if not job:
            return None
        job.status = "completed"
        job.phase = phase
        job.completed_at = now
        _touch(job, now)
        return _to_payload(job)


def mark_needs_review(job_id: str, error_message: str, *, phase: str = "needs_review") -> Optional[dict]:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        job = _jobs.get(job_id)
        if not job:
            return None
        job.status = "needs_review"
        job.phase = phase
        job.error_message = (error_message or "Manual review required")[:1000]
        job.completed_at = now
        _touch(job, now)
        return _to_payload(job)


def mark_failed(job_id: str, error_message: str, *, phase: str = "failed") -> Optional[dict]:
    now = _utcnow()
    with _jobs_lock:
        _cleanup_locked(now)
        job = _jobs.get(job_id)
        if not job:
            return None
        job.status = "failed"
        job.phase = phase
        job.error_message = (error_message or "Unknown error")[:1000]
        job.completed_at = now
        _touch(job, now)
        return _to_payload(job)

