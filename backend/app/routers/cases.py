"""Router – CRUD for Cases (expedientes)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditLog, Case, CaseUser, Checklist, Page, PageStatus, Role, Team, TeamUser, User, UserRole
from ..schemas import CaseCreate, CaseOut, CaseUpdate
from ..services.case_document_scope_service import (
    get_case_scope_source_document_ids,
    set_case_scope_source_document_ids,
)
from .auth import get_current_user

router = APIRouter(prefix="/cases", tags=["cases"])

CASEMANAGER_ROLE_ALIASES = {"casemanager", "casemanger", "casemaneger"}


def _case_to_out(case: Case, db: Session) -> CaseOut:
    page_count = db.query(Page).filter(Page.case_id == case.id, Page.deleted_at.is_(None)).count()
    classified = (
        db.query(Page)
        .filter(Page.case_id == case.id, Page.deleted_at.is_(None), Page.status == PageStatus.CLASSIFIED.value)
        .count()
    )
    cl_count = db.query(Checklist).filter(Checklist.case_id == case.id).count()

    creator_name = ""
    if case.created_by:
        creator = db.query(User).filter(User.id == case.created_by).first()
        if creator:
            creator_name = creator.name

    return CaseOut(
        id=case.id,
        name=case.name,
        description=case.description,
        created_by=case.created_by,
        created_by_name=creator_name,
        created_at=case.created_at,
        updated_at=case.updated_at,
        page_count=page_count,
        classified_count=classified,
        checklist_count=cl_count,
        form_filling_source_document_ids=get_case_scope_source_document_ids(case, "form_filling"),
        qc_checklist_source_document_ids=get_case_scope_source_document_ids(case, "qc_checklist"),
    )


def _get_user_role_names(db: Session, user_id: int) -> set[str]:
    rows = (
        db.query(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .filter(UserRole.user_id == user_id)
        .all()
    )
    return {name.lower() for (name,) in rows}


def _assert_case_access(db: Session, user_id: int, case_id: str):
    """Raise 403 unless user is admin, directly assigned, or supervises a
    team whose member owns the case."""
    if "admin" in _get_user_role_names(db, user_id):
        return

    direct = (
        db.query(CaseUser)
        .filter(
            CaseUser.case_id == case_id,
            CaseUser.user_id == user_id,
            CaseUser.deleted_at.is_(None),
        )
        .first()
    )
    if direct:
        return

    supervised = (
        db.query(CaseUser)
        .join(TeamUser, and_(
            TeamUser.user_id == CaseUser.user_id,
            TeamUser.deleted_at.is_(None),
        ))
        .join(Team, and_(
            Team.id == TeamUser.team_id,
            Team.deleted_at.is_(None),
            Team.supervisor_id == user_id,
        ))
        .filter(
            CaseUser.case_id == case_id,
            CaseUser.deleted_at.is_(None),
        )
        .first()
    )
    if supervised:
        return

    raise HTTPException(403, "Access denied to this case")


@router.get("", response_model=list[CaseOut])
def list_cases(
    payload: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = payload.get("user_id")
    role_names = _get_user_role_names(db, user_id)
    is_admin = "admin" in role_names
    is_casemanager = bool(role_names.intersection(CASEMANAGER_ROLE_ALIASES))

    if is_admin:
        cases = db.query(Case).order_by(Case.updated_at.desc()).all()
    else:
        # For casemanager (and any non-admin role), keep visibility scoped
        # to explicitly assigned cases only.
        case_ids = (
            db.query(CaseUser.case_id)
            .filter(CaseUser.user_id == user_id, CaseUser.deleted_at.is_(None))
            .subquery()
        )
        cases = (
            db.query(Case)
            .filter(Case.id.in_(case_ids))
            .order_by(Case.updated_at.desc())
            .all()
        )

        if is_casemanager and not cases:
            # Explicit branch to document intended behavior for case managers:
            # empty list is valid when there are no assigned cases.
            return []

    return [_case_to_out(c, db) for c in cases]


@router.post("", response_model=CaseOut, status_code=201)
def create_case(
    body: CaseCreate,
    payload: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = payload.get("user_id")

    case = Case(name=body.name, description=body.description, created_by=user_id)
    db.add(case)
    db.flush()

    db.add(CaseUser(case_id=case.id, user_id=user_id))
    db.add(AuditLog(
        case_id=case.id,
        action="created",
        entity_type="case",
        entity_id=case.id,
        user=str(user_id),
    ))

    db.commit()
    db.refresh(case)
    return _case_to_out(case, db)


@router.get("/{case_id}", response_model=CaseOut)
def get_case(
    case_id: str,
    payload: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    _assert_case_access(db, payload["user_id"], case_id)
    return _case_to_out(case, db)


@router.put("/{case_id}", response_model=CaseOut)
def update_case(
    case_id: str,
    body: CaseUpdate,
    payload: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    _assert_case_access(db, payload["user_id"], case_id)
    provided_fields = set(getattr(body, "model_fields_set", set()) or getattr(body, "__fields_set__", set()))
    if body.name is not None:
        case.name = body.name
    if body.description is not None:
        case.description = body.description
    if "form_filling_source_document_ids" in provided_fields:
        set_case_scope_source_document_ids(
            case,
            "form_filling",
            body.form_filling_source_document_ids,
        )
    if "qc_checklist_source_document_ids" in provided_fields:
        set_case_scope_source_document_ids(
            case,
            "qc_checklist",
            body.qc_checklist_source_document_ids,
        )
    db.add(AuditLog(
        case_id=case.id,
        action="updated",
        entity_type="case",
        entity_id=case.id,
        user=str(payload.get("user_id", "system")),
    ))
    db.commit()
    db.refresh(case)
    return _case_to_out(case, db)


@router.delete("/{case_id}", status_code=204)
def delete_case(
    case_id: str,
    payload: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if "admin" not in _get_user_role_names(db, payload["user_id"]):
        raise HTTPException(403, "Only admins can delete cases")
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        # Keep DELETE idempotent so stale dashboard cards or repeated clicks
        # do not surface a backend error for a case that is already gone.
        return
    db.delete(case)
    db.commit()
