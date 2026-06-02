"""Router for post-organization case preparation jobs (OCR + index + context)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Case
from ..schemas import CasePreparationJobOut
from ..services.case_preparation_jobs import find_active_job, get_job
from ..services.case_preparation_service import maybe_start_case_preparation

router = APIRouter(tags=["case-preparation"])


def _get_case_or_404(db: Session, case_id: str) -> Case:
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    return case


def _as_utc_datetime(value: float | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(float(value), tz=timezone.utc)


def _job_out(job) -> CasePreparationJobOut:
    payload = job.to_dict()
    return CasePreparationJobOut(
        id=payload["id"],
        case_id=payload["case_id"],
        status=payload["status"],
        phase=payload.get("phase") or "queued",
        progress_pct=float(payload.get("progress_pct") or 0.0),
        progress_message=payload.get("progress_message") or "",
        ocr_total_pages=int(payload.get("ocr_total_pages") or 0),
        ocr_processed_pages=int(payload.get("ocr_processed_pages") or 0),
        ocr_error_pages=int(payload.get("ocr_error_pages") or 0),
        index_total_chunks=int(payload.get("index_total_chunks") or 0),
        index_processed_chunks=int(payload.get("index_processed_chunks") or 0),
        error_message=payload.get("error"),
        created_at=_as_utc_datetime(payload.get("created_at")) or datetime.now(timezone.utc),
        started_at=_as_utc_datetime(payload.get("started_at")),
        completed_at=_as_utc_datetime(payload.get("finished_at")),
    )


@router.get("/cases/{case_id}/case-preparation-jobs/active", response_model=CasePreparationJobOut | None)
def get_active_case_preparation_job(case_id: str, db: Session = Depends(get_db)):
    _get_case_or_404(db, case_id)
    job = find_active_job(case_id)
    if job is None:
        return None
    return _job_out(job)


@router.get("/case-preparation-jobs/{job_id}", response_model=CasePreparationJobOut)
def get_case_preparation_job(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, "Case preparation job not found")
    return _job_out(job)


@router.post("/cases/{case_id}/case-preparation-jobs", response_model=CasePreparationJobOut, status_code=202)
def start_case_preparation_job(case_id: str, db: Session = Depends(get_db)):
    _get_case_or_404(db, case_id)
    maybe_start_case_preparation(case_id)
    job = find_active_job(case_id)
    if job is None:
        raise HTTPException(409, "Case preparation is not needed or could not be started")
    return _job_out(job)
