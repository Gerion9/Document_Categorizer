"""Router – CRUD for Cases (expedientes)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditLog, Case, Page, PageStatus, Checklist
from ..schemas import CaseCreate, CaseOut, CaseUpdate

router = APIRouter(prefix="/cases", tags=["cases"])


def _case_to_out(case: Case, db: Session) -> CaseOut:
    page_count = db.query(Page).filter(Page.case_id == case.id).count()
    classified = (
        db.query(Page)
        .filter(Page.case_id == case.id, Page.status == PageStatus.CLASSIFIED.value)
        .count()
    )
    cl_count = db.query(Checklist).filter(Checklist.case_id == case.id).count()
    return CaseOut(
        id=case.id,
        name=case.name,
        description=case.description,
        created_at=case.created_at,
        updated_at=case.updated_at,
        page_count=page_count,
        classified_count=classified,
        checklist_count=cl_count,
    )


@router.get("", response_model=list[CaseOut])
def list_cases(db: Session = Depends(get_db)):
    cases = db.query(Case).order_by(Case.updated_at.desc()).all()
    return [_case_to_out(c, db) for c in cases]


@router.post("", response_model=CaseOut, status_code=201)
def create_case(body: CaseCreate, db: Session = Depends(get_db)):
    case = Case(name=body.name, description=body.description)
    db.add(case)
    db.flush()
    db.add(AuditLog(case_id=case.id, action="created", entity_type="case", entity_id=case.id))
    db.commit()
    db.refresh(case)
    return _case_to_out(case, db)


@router.get("/{case_id}", response_model=CaseOut)
def get_case(case_id: str, db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    return _case_to_out(case, db)


@router.put("/{case_id}", response_model=CaseOut)
def update_case(case_id: str, body: CaseUpdate, db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    if body.name is not None:
        case.name = body.name
    if body.description is not None:
        case.description = body.description
    db.add(AuditLog(case_id=case.id, action="updated", entity_type="case", entity_id=case.id))
    db.commit()
    db.refresh(case)
    return _case_to_out(case, db)


@router.delete("/{case_id}", status_code=204)
def delete_case(case_id: str, db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    db.delete(case)
    db.commit()

