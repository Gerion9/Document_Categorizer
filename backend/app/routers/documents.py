"""Router – CRUD for DocumentTypes and Sections (taxonomy tree with multi-level hierarchy)."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditLog, Case, DocumentType, Section
from ..schemas import (
    DocumentTypeCreate,
    DocumentTypeOut,
    DocumentTypeUpdate,
    ReorderRequest,
    SectionCreate,
    SectionOut,
    SectionUpdate,
)
from ..services.indexing_service import is_indexing_available, reindex_case_pages

router = APIRouter(tags=["documents"])


# ── helpers ───────────────────────────────────────────────────────────────

def _compute_path_code(sec: Section, db: Session) -> str:
    """Build a dotted path code like 'B.1.2' walking up the parent chain."""
    parts: list[str] = [sec.code]
    current = sec
    while current.parent_section_id:
        parent = db.query(Section).filter(Section.id == current.parent_section_id).first()
        if not parent:
            break
        parts.insert(0, parent.code)
        current = parent
    # Prepend the doc type code
    dt = db.query(DocumentType).filter(DocumentType.id == sec.document_type_id).first()
    if dt:
        parts.insert(0, dt.code)
    return ".".join(parts)


def _compute_depth(sec: Section, db: Session) -> int:
    depth = 0
    current = sec
    while current.parent_section_id:
        depth += 1
        parent = db.query(Section).filter(Section.id == current.parent_section_id).first()
        if not parent:
            break
        current = parent
    return depth


def _refresh_section_subtree(sec: Section, db: Session) -> None:
    sec.depth = _compute_depth(sec, db)
    sec.path_code = _compute_path_code(sec, db)
    children = db.query(Section).filter(Section.parent_section_id == sec.id).all()
    for child in children:
        _refresh_section_subtree(child, db)


def _queue_case_reindex(background_tasks: BackgroundTasks, case_id: str | None) -> None:
    if not case_id or not is_indexing_available():
        return
    background_tasks.add_task(reindex_case_pages, case_id)


def _section_out(sec: Section, all_sections: list[Section] | None = None) -> SectionOut:
    children: list[SectionOut] = []
    if all_sections:
        child_secs = sorted(
            [s for s in all_sections if s.parent_section_id == sec.id],
            key=lambda s: s.order,
        )
        children = [_section_out(s, all_sections) for s in child_secs]

    return SectionOut(
        id=sec.id,
        document_type_id=sec.document_type_id,
        parent_section_id=sec.parent_section_id,
        name=sec.name,
        code=sec.code,
        path_code=sec.path_code or "",
        depth=sec.depth or 0,
        order=sec.order,
        is_required=sec.is_required,
        page_count=len(sec.pages),
        children=children,
    )


def _doctype_out(dt: DocumentType) -> DocumentTypeOut:
    all_secs = list(dt.sections)
    root_secs = sorted(
        [s for s in all_secs if not s.parent_section_id],
        key=lambda s: s.order,
    )
    return DocumentTypeOut(
        id=dt.id,
        case_id=dt.case_id,
        name=dt.name,
        code=dt.code,
        order=dt.order,
        has_tables=dt.has_tables or False,
        created_at=dt.created_at,
        sections=[_section_out(s, all_secs) for s in root_secs],
    )


# ── DocumentType endpoints ────────────────────────────────────────────────

@router.get("/cases/{case_id}/document-types", response_model=list[DocumentTypeOut])
def list_document_types(case_id: str, db: Session = Depends(get_db)):
    dts = (
        db.query(DocumentType)
        .filter(DocumentType.case_id == case_id)
        .order_by(DocumentType.order)
        .all()
    )
    return [_doctype_out(dt) for dt in dts]


@router.post("/cases/{case_id}/document-types", response_model=DocumentTypeOut, status_code=201)
def create_document_type(case_id: str, body: DocumentTypeCreate, db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    dt = DocumentType(case_id=case_id, name=body.name, code=body.code, order=body.order, has_tables=body.has_tables)
    db.add(dt)
    db.flush()
    db.add(AuditLog(case_id=case_id, action="created", entity_type="document_type", entity_id=dt.id,
                    details={"name": body.name, "code": body.code}))
    db.commit()
    db.refresh(dt)
    return _doctype_out(dt)


@router.put("/document-types/{dt_id}", response_model=DocumentTypeOut)
def update_document_type(
    dt_id: str,
    body: DocumentTypeUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    dt = db.query(DocumentType).filter(DocumentType.id == dt_id).first()
    if not dt:
        raise HTTPException(404, "DocumentType not found")
    should_refresh_sections = False
    if body.name is not None:
        dt.name = body.name
    if body.code is not None:
        dt.code = body.code
        should_refresh_sections = True
    if body.order is not None:
        dt.order = body.order
    if body.has_tables is not None:
        dt.has_tables = body.has_tables
    if should_refresh_sections:
        for sec in db.query(Section).filter(Section.document_type_id == dt.id).all():
            if not sec.parent_section_id:
                _refresh_section_subtree(sec, db)
    db.add(AuditLog(case_id=dt.case_id, action="updated", entity_type="document_type", entity_id=dt.id))
    db.commit()
    db.refresh(dt)
    _queue_case_reindex(background_tasks, dt.case_id)
    return _doctype_out(dt)


@router.delete("/document-types/{dt_id}", status_code=204)
def delete_document_type(dt_id: str, db: Session = Depends(get_db)):
    dt = db.query(DocumentType).filter(DocumentType.id == dt_id).first()
    if not dt:
        raise HTTPException(404, "DocumentType not found")
    db.add(AuditLog(case_id=dt.case_id, action="deleted", entity_type="document_type", entity_id=dt.id,
                    details={"name": dt.name}))
    db.delete(dt)
    db.commit()


@router.put("/document-types/reorder", status_code=200)
def reorder_document_types(body: ReorderRequest, db: Session = Depends(get_db)):
    for item in body.items:
        dt = db.query(DocumentType).filter(DocumentType.id == item.id).first()
        if dt:
            dt.order = item.order
    db.commit()
    return {"ok": True}


# ── Section endpoints (multi-level) ──────────────────────────────────────

@router.get("/cases/{case_id}/sections-flat", response_model=list[SectionOut])
def list_all_sections_flat(case_id: str, db: Session = Depends(get_db)):
    """Return ALL sections for a case as a flat list (useful for dropdowns/pickers)."""
    dts = db.query(DocumentType).filter(DocumentType.case_id == case_id).all()
    dt_ids = [dt.id for dt in dts]
    if not dt_ids:
        return []
    secs = db.query(Section).filter(Section.document_type_id.in_(dt_ids)).order_by(Section.order).all()
    return [_section_out(s) for s in secs]


@router.post("/document-types/{dt_id}/sections", response_model=SectionOut, status_code=201)
def create_section(dt_id: str, body: SectionCreate, db: Session = Depends(get_db)):
    dt = db.query(DocumentType).filter(DocumentType.id == dt_id).first()
    if not dt:
        raise HTTPException(404, "DocumentType not found")

    # Validate parent belongs to same doc type
    if body.parent_section_id:
        parent = db.query(Section).filter(Section.id == body.parent_section_id).first()
        if not parent or parent.document_type_id != dt_id:
            raise HTTPException(400, "Parent section not found or belongs to different DocumentType")

    sec = Section(
        document_type_id=dt_id,
        parent_section_id=body.parent_section_id,
        name=body.name,
        code=body.code,
        order=body.order,
        is_required=body.is_required,
    )
    db.add(sec)
    db.flush()

    # Compute depth and path_code
    sec.depth = _compute_depth(sec, db)
    sec.path_code = _compute_path_code(sec, db)

    db.add(AuditLog(case_id=dt.case_id, action="created", entity_type="section", entity_id=sec.id,
                    details={"name": body.name, "code": body.code, "path_code": sec.path_code}))
    db.commit()
    db.refresh(sec)
    return _section_out(sec)


@router.put("/sections/{sec_id}", response_model=SectionOut)
def update_section(
    sec_id: str,
    body: SectionUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    sec = db.query(Section).filter(Section.id == sec_id).first()
    if not sec:
        raise HTTPException(404, "Section not found")
    if body.name is not None:
        sec.name = body.name
    if body.code is not None:
        sec.code = body.code
    if body.order is not None:
        sec.order = body.order
    if body.is_required is not None:
        sec.is_required = body.is_required
    if body.parent_section_id is not None:
        sec.parent_section_id = body.parent_section_id

    # Re-compute hierarchy fields
    _refresh_section_subtree(sec, db)

    db.commit()
    db.refresh(sec)
    _queue_case_reindex(background_tasks, sec.document_type.case_id if sec.document_type else None)
    return _section_out(sec)


@router.delete("/sections/{sec_id}", status_code=204)
def delete_section(sec_id: str, db: Session = Depends(get_db)):
    sec = db.query(Section).filter(Section.id == sec_id).first()
    if not sec:
        raise HTTPException(404, "Section not found")
    db.delete(sec)
    db.commit()


@router.put("/sections/reorder", status_code=200)
def reorder_sections(body: ReorderRequest, db: Session = Depends(get_db)):
    for item in body.items:
        sec = db.query(Section).filter(Section.id == item.id).first()
        if sec:
            sec.order = item.order
    db.commit()
    return {"ok": True}
