"""Router – Export consolidated PDF and compliance report."""

from typing import Callable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditLog, Case
from ..schemas import AuditLogOut
from ..services.export_service import (
    build_compliance_report,
    build_consolidated_pdf,
    build_qc_compliance_report,
)
from ..services.paths import STORAGE_DIR

router = APIRouter(tags=["export"])


def _export_case_file(
    case_id: str,
    db: Session,
    *,
    builder: Callable[[Session, str], str],
    audit_action: str,
    filename_template: str,
) -> FileResponse:
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    try:
        rel_path = builder(db, case_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    abs_path = str(STORAGE_DIR / rel_path)
    db.add(AuditLog(case_id=case_id, action=audit_action, entity_type="case", entity_id=case_id))
    db.commit()
    return FileResponse(abs_path, media_type="application/pdf", filename=filename_template.format(name=case.name))


@router.get("/cases/{case_id}/export/pdf")
def export_pdf(case_id: str, db: Session = Depends(get_db)):
    """Download consolidated PDF with hierarchical index and bookmarks."""
    return _export_case_file(
        case_id, db,
        builder=build_consolidated_pdf,
        audit_action="exported_pdf",
        filename_template="expediente_{name}.pdf",
    )


@router.get("/cases/{case_id}/export/report")
def export_report(case_id: str, db: Session = Depends(get_db)):
    """Download legacy checklist compliance report."""
    return _export_case_file(
        case_id, db,
        builder=build_compliance_report,
        audit_action="exported_report",
        filename_template="reporte_{name}.pdf",
    )


@router.get("/cases/{case_id}/export/qc-report")
def export_qc_report(case_id: str, db: Session = Depends(get_db)):
    """Download QC compliance report with AI verification results."""
    return _export_case_file(
        case_id, db,
        builder=build_qc_compliance_report,
        audit_action="exported_qc_report",
        filename_template="qc_reporte_{name}.pdf",
    )


# ── Audit log ─────────────────────────────────────────────────────────────

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
