"""In-memory background job runtime for questionnaire autofill.

Design rationale
----------------
The questionnaire autofill pipeline can take from a few seconds to several
minutes depending on document count, OCR readiness, and LLM batching. We do
not want to keep an HTTP connection open for the entire run because:

  1. Browsers, reverse proxies and load balancers all impose connection
     timeouts (30s-2min by default).
  2. A frontend abort should *never* terminate the underlying work; the user
     might just have a flaky network or the tab may be backgrounded.
  3. Multiple users on the same case need a shared view of progress.

To address this we expose a thin async job API:

    POST /.../autofill            -> 202 + {job_id}
    GET  /.../autofill-jobs/{id}  -> always fast, reads in-memory status
    DELETE /.../autofill-jobs/{id} -> requests cooperative cancellation

The actual work runs in a daemon thread that owns its own SQLAlchemy session.
Job state lives in a process-local dict guarded by a Lock and is garbage
collected after `_JOB_TTL_SECONDS`.

This module is intentionally framework-agnostic (no FastAPI imports) so the
runner callable can be tested in isolation.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from ..database import SessionLocal

log = logging.getLogger(__name__)

JobKind = Literal["shared", "attorney"]
JobStatus = Literal[
    "queued",
    "running",
    "ocr_preparing",
    "completed",
    "failed",
    "cancelled",
]

_ACTIVE_STATUSES: set[str] = {"queued", "running", "ocr_preparing"}
_JOB_TTL_SECONDS = 6 * 60 * 60  # keep finished jobs available for 6h


class AutofillCancelled(Exception):
    """Raised by the runner when a cooperative cancel is observed."""


@dataclass
class AutofillJob:
    """Mutable runtime record for a single autofill execution."""

    id: str
    case_id: str
    kind: JobKind
    status: JobStatus = "queued"
    progress_pct: float = 0.0
    progress_message: str = ""
    ocr_total_pages: int = 0
    ocr_processed_pages: int = 0
    error: Optional[str] = None
    result: Optional[dict[str, Any]] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    cancel_requested: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "case_id": self.case_id,
            "kind": self.kind,
            "status": self.status,
            "progress_pct": float(self.progress_pct or 0.0),
            "progress_message": self.progress_message or "",
            "ocr_total_pages": int(self.ocr_total_pages or 0),
            "ocr_processed_pages": int(self.ocr_processed_pages or 0),
            "error": self.error,
            "result": self.result,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


_jobs: dict[str, AutofillJob] = {}
_jobs_lock = threading.Lock()


def open_db_session() -> Session:
    """Return a fresh SQLAlchemy session for use inside a worker thread.

    Each background job must own its session because the request-scoped one
    yielded by `get_db` is closed as soon as the POST returns.
    """
    return SessionLocal()


def _gc_locked(now: float) -> None:
    """Drop finished jobs whose TTL expired. Caller must hold `_jobs_lock`."""
    expired = [
        job_id
        for job_id, job in _jobs.items()
        if job.finished_at is not None
        and (now - job.finished_at) > _JOB_TTL_SECONDS
    ]
    for job_id in expired:
        _jobs.pop(job_id, None)


def _find_active_for_case_locked(case_id: str, kind: JobKind) -> Optional[AutofillJob]:
    """Caller must hold `_jobs_lock`."""
    for job in _jobs.values():
        if (
            job.case_id == case_id
            and job.kind == kind
            and job.status in _ACTIVE_STATUSES
        ):
            return job
    return None


def find_active_job(case_id: str, kind: JobKind) -> Optional[AutofillJob]:
    """Return the active autofill job for a case+kind tuple, if any."""
    with _jobs_lock:
        _gc_locked(time.time())
        return _find_active_for_case_locked(case_id, kind)


def get_job(job_id: str) -> Optional[AutofillJob]:
    """Look up a job by id. Returns None if expired or missing."""
    with _jobs_lock:
        _gc_locked(time.time())
        return _jobs.get(job_id)


def cancel_job(job_id: str) -> Optional[AutofillJob]:
    """Request cooperative cancellation. The worker observes the flag and
    raises `AutofillCancelled` at the next checkpoint."""
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return None
        if job.status in ("completed", "failed", "cancelled"):
            return job
        job.cancel_requested = True
        return job


def start_job(
    *,
    case_id: str,
    kind: JobKind,
    runner: Callable[[AutofillJob], dict[str, Any]],
) -> AutofillJob:
    """Create and start a new autofill job.

    If an active job already exists for the same (case_id, kind) tuple we
    return it instead of starting a duplicate. This keeps the UI idempotent
    if the user double-clicks the autofill button.

    Parameters
    ----------
    case_id, kind
        Identify the target case and questionnaire side.
    runner
        Worker callable. It receives the live `AutofillJob` and must return
        the dict that goes into `job.result`. Long operations should poll
        `job.cancel_requested` periodically and raise `AutofillCancelled`.

    Returns
    -------
    AutofillJob
        The job that was created (or re-used). Always populated with `id`.
    """
    if kind not in ("shared", "attorney"):
        raise ValueError("kind must be 'shared' or 'attorney'.")

    with _jobs_lock:
        _gc_locked(time.time())
        existing = _find_active_for_case_locked(case_id, kind)
        if existing is not None:
            return existing

        job = AutofillJob(
            id=str(uuid4()),
            case_id=case_id,
            kind=kind,
            status="queued",
            progress_pct=0.0,
            progress_message="Queued",
        )
        _jobs[job.id] = job

    thread = threading.Thread(
        target=_run_job,
        args=(job, runner),
        name=f"autofill-{kind}-{job.id[:8]}",
        daemon=True,
    )
    thread.start()
    return job


def _run_job(
    job: AutofillJob,
    runner: Callable[[AutofillJob], dict[str, Any]],
) -> None:
    """Execute the runner inside the worker thread, capturing terminal state."""
    job.started_at = time.time()
    job.status = "running"
    try:
        result = runner(job)
        if job.cancel_requested:
            raise AutofillCancelled()
        job.result = result
        job.status = "completed"
        job.progress_pct = 100.0
        if not job.progress_message:
            job.progress_message = "Completed"
    except AutofillCancelled:
        job.status = "cancelled"
        job.progress_message = "Cancelled by user"
    except Exception as exc:  # pylint: disable=broad-except
        log.exception(
            "Autofill job %s (%s, case=%s) failed: %s",
            job.id,
            job.kind,
            job.case_id,
            exc,
        )
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
        if not job.progress_message:
            job.progress_message = "Failed"
        job.result = {"traceback": traceback.format_exc(limit=5)}
    finally:
        job.finished_at = time.time()
