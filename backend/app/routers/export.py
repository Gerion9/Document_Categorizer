"""Router – Export consolidated PDF and compliance report."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditLog, Case
from ..schemas import AuditLogOut
from ..services.export_service import (
    STORAGE_DIR,
    build_compliance_report,
    build_consolidated_pdf,
    build_qc_compliance_report,
)

router = APIRouter(tags=["export"])


@router.get("/cases/{case_id}/export/pdf")
def export_pdf(case_id: str, db: Session = Depends(get_db)):
    """Download consolidated PDF with hierarchical index and bookmarks."""
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    try:
        rel_path = build_consolidated_pdf(db, case_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    abs_path = str(STORAGE_DIR / rel_path)
    db.add(AuditLog(case_id=case_id, action="exported_pdf", entity_type="case", entity_id=case_id))
    db.commit()
    return FileResponse(
        abs_path,
        media_type="application/pdf",
        filename=f"expediente_{case.name}.pdf",
    )


@router.get("/cases/{case_id}/export/report")
def export_report(case_id: str, db: Session = Depends(get_db)):
    """Download legacy checklist compliance report."""
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    try:
        rel_path = build_compliance_report(db, case_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    abs_path = str(STORAGE_DIR / rel_path)
    db.add(AuditLog(case_id=case_id, action="exported_report", entity_type="case", entity_id=case_id))
    db.commit()
    return FileResponse(
        abs_path,
        media_type="application/pdf",
        filename=f"reporte_{case.name}.pdf",
    )


@router.get("/cases/{case_id}/export/qc-report")
def export_qc_report(case_id: str, db: Session = Depends(get_db)):
    """Download QC compliance report with AI verification results."""
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    try:
        rel_path = build_qc_compliance_report(db, case_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    abs_path = str(STORAGE_DIR / rel_path)
    db.add(AuditLog(case_id=case_id, action="exported_qc_report", entity_type="case", entity_id=case_id))
    db.commit()
    return FileResponse(
        abs_path,
        media_type="application/pdf",
        filename=f"qc_reporte_{case.name}.pdf",
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
