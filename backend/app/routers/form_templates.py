"""Router for pre-loaded form PDF templates stored in S3."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_s3_service
from ..models import AuditLog, Case, FormTemplate
from ..schemas import FormFillingJobOut, FormTemplateOut
from ..services.form_filling_service import create_job, run_form_filling_job
from ..services.pdf_service import save_uploaded_file
from ..services.storage_service import S3StorageService

router = APIRouter(tags=["form-templates"])


def _get_case_or_404(db: Session, case_id: str) -> Case:
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    return case


def _get_template_or_404(db: Session, template_id: str) -> FormTemplate:
    tpl = db.query(FormTemplate).filter(FormTemplate.id == template_id).first()
    if not tpl:
        raise HTTPException(404, "Form template not found")
    return tpl


def _job_out(job) -> FormFillingJobOut:
    payload = FormFillingJobOut.model_validate(job).model_dump()
    payload["fields"] = []
    return FormFillingJobOut(**payload)


@router.get("/form-templates", response_model=list[FormTemplateOut])
def list_form_templates(db: Session = Depends(get_db)):
    return db.query(FormTemplate).order_by(FormTemplate.name).all()


@router.get("/form-templates/{template_id}", response_model=FormTemplateOut)
def get_form_template(template_id: str, db: Session = Depends(get_db)):
    return _get_template_or_404(db, template_id)


@router.get("/form-templates/{template_id}/url")
def get_form_template_url(
    template_id: str,
    db: Session = Depends(get_db),
    s3: S3StorageService = Depends(get_s3_service),
):
    tpl = _get_template_or_404(db, template_id)
    url = s3.generate_presigned_url(tpl.s3_key, expires_in=3600)
    return {"url": url, "filename": tpl.original_filename}


@router.post(
    "/cases/{case_id}/form-fill/from-template/{template_id}",
    response_model=FormFillingJobOut,
    status_code=201,
)
def create_job_from_template(
    case_id: str,
    template_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    s3: S3StorageService = Depends(get_s3_service),
):
    _get_case_or_404(db, case_id)
    tpl = _get_template_or_404(db, template_id)

    pdf_bytes = s3.download_bytes(tpl.s3_key)
    upload_path = save_uploaded_file(pdf_bytes, tpl.original_filename, s3)

    job = create_job(
        db,
        case_id=case_id,
        original_pdf_path=upload_path,
        form_type=tpl.form_type,
    )

    db.add(AuditLog(
        case_id=case_id,
        action="form_filling_from_template",
        entity_type="form_filling_job",
        entity_id=job.id,
        details={
            "template_id": tpl.id,
            "template_name": tpl.name,
            "form_type": tpl.form_type,
            "original_pdf_path": upload_path,
        },
    ))
    db.commit()

    background_tasks.add_task(run_form_filling_job, job.id)
    return _job_out(job)
