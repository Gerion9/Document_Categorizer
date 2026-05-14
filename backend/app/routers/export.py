"""Router -- Export consolidated PDF and compliance report (S3-backed)."""

import re
import unicodedata
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_s3_service
from ..models import AuditLog, Case, QCChecklist
from ..schemas import AuditLogOut
from ..services.export_service import (
    build_compliance_report,
    build_consolidated_pdf,
    build_qc_compliance_report,
)
from ..services.storage_service import S3StorageService

router = APIRouter(tags=["export"])


def _sanitize_filename(name: str) -> str:
    """Normalize Unicode and strip non-ASCII so the value is safe for HTTP headers."""
    normalized = unicodedata.normalize("NFKD", name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^\w\-.]", "_", ascii_name).strip("_")


def _export_case_file(
    case_id: str,
    db: Session,
    s3: S3StorageService,
    *,
    builder: Callable[[Session, str, S3StorageService], str],
    audit_action: str,
    filename_template: str,
) -> Response:
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    try:
        s3_key = builder(db, case_id, s3)
    except ValueError as e:
        raise HTTPException(400, str(e))
    pdf_bytes = s3.download_bytes(s3_key)
    db.add(AuditLog(case_id=case_id, action=audit_action, entity_type="case", entity_id=case_id))
    db.commit()
    filename = filename_template.format(name=_sanitize_filename(case.name))
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/cases/{case_id}/export/pdf")
def export_pdf(case_id: str, db: Session = Depends(get_db), s3: S3StorageService = Depends(get_s3_service)):
    return _export_case_file(
        case_id, db, s3,
        builder=build_consolidated_pdf,
        audit_action="exported_pdf",
        filename_template="expediente_{name}.pdf",
    )


@router.get("/cases/{case_id}/export/report")
def export_report(case_id: str, db: Session = Depends(get_db), s3: S3StorageService = Depends(get_s3_service)):
    return _export_case_file(
        case_id, db, s3,
        builder=build_compliance_report,
        audit_action="exported_report",
        filename_template="reporte_{name}.pdf",
    )


@router.get("/cases/{case_id}/export/qc-report")
def export_qc_report(case_id: str, db: Session = Depends(get_db), s3: S3StorageService = Depends(get_s3_service)):
    return _export_case_file(
        case_id, db, s3,
        builder=build_qc_compliance_report,
        audit_action="exported_qc_report",
        filename_template="qc_reporte_{name}.pdf",
    )


@router.get("/cases/{case_id}/export/qc-report/{cl_id}")
def export_single_qc_report(
    case_id: str,
    cl_id: str,
    db: Session = Depends(get_db),
    s3: S3StorageService = Depends(get_s3_service),
):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    cl = db.query(QCChecklist).filter(QCChecklist.id == cl_id, QCChecklist.case_id == case_id).first()
    if not cl:
        raise HTTPException(404, "QC Checklist not found in this case")
    try:
        s3_key = build_qc_compliance_report(db, case_id, s3, checklist_id=cl_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    pdf_bytes = s3.download_bytes(s3_key)
    db.add(AuditLog(case_id=case_id, action="exported_qc_report", entity_type="qc_checklist", entity_id=cl_id))
    db.commit()
    safe_name = _sanitize_filename(cl.name)
    safe_case = _sanitize_filename(case.name)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="qc_{safe_name}_{safe_case}.pdf"'},
    )


# -- Audit log ----------------------------------------------------------------

@router.get("/cases/{case_id}/audit", response_model=list[AuditLogOut])
def get_audit_log(case_id: str, db: Session = Depends(get_db)):
    logs = (
        db.query(AuditLog)
        .filter(AuditLog.case_id == case_id)
        .order_by(AuditLog.created_at.desc())
        .limit(200)
        .all()
    )
    return [AuditLogOut.model_validate(l) for l in logs]
