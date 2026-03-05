"""Router – Checklists, checklist items, evidence links, and section target mapping."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    AuditLog,
    Case,
    Checklist,
    ChecklistItem,
    ChecklistItemSectionTarget,
    ChecklistItemStatus,
    EvidenceLink,
    Page,
    Section,
)
from ..schemas import (
    ChecklistCreate,
    ChecklistItemCreate,
    ChecklistItemOut,
    ChecklistItemUpdate,
    ChecklistOut,
    EvidenceLinkCreate,
    EvidenceLinkOut,
    ItemTargetsUpsert,
    PageOut,
    SectionTargetOut,
)

router = APIRouter(tags=["checklist"])


# ── helpers ───────────────────────────────────────────────────────────────

def _evidence_out(ev: EvidenceLink, db: Session) -> EvidenceLinkOut:
    page = db.query(Page).filter(Page.id == ev.page_id).first()
    return EvidenceLinkOut(
        id=ev.id,
        checklist_item_id=ev.checklist_item_id,
        page_id=ev.page_id,
        notes=ev.notes,
        created_at=ev.created_at,
        page=PageOut.model_validate(page) if page else None,
    )


def _target_out(t: ChecklistItemSectionTarget, db: Session) -> SectionTargetOut:
    sec = db.query(Section).filter(Section.id == t.section_id).first()
    return SectionTargetOut(
        id=t.id,
        section_id=t.section_id,
        section_path_code=sec.path_code if sec else "",
        section_name=sec.name if sec else "",
    )


def _item_out(item: ChecklistItem, db: Session) -> ChecklistItemOut:
    targets = (
        db.query(ChecklistItemSectionTarget)
        .filter(ChecklistItemSectionTarget.checklist_item_id == item.id)
        .all()
    )
    return ChecklistItemOut(
        id=item.id,
        checklist_id=item.checklist_id,
        description=item.description,
        status=item.status,
        order=item.order,
        notes=item.notes,
        evidence_links=[_evidence_out(ev, db) for ev in item.evidence_links],
        target_sections=[_target_out(t, db) for t in targets],
    )


def _checklist_out(cl: Checklist, db: Session) -> ChecklistOut:
    items = (
        db.query(ChecklistItem)
        .filter(ChecklistItem.checklist_id == cl.id)
        .order_by(ChecklistItem.order)
        .all()
    )
    total = len(items)
    complete = sum(1 for i in items if i.status == ChecklistItemStatus.COMPLETE.value)
    pct = (complete / total * 100) if total else 0.0
    return ChecklistOut(
        id=cl.id,
        case_id=cl.case_id,
        name=cl.name,
        created_at=cl.created_at,
        items=[_item_out(i, db) for i in items],
        completion_pct=round(pct, 1),
    )


def _sync_targets(item_id: str, section_ids: list[str], db: Session):
    """Replace all section targets for an item with the given list."""
    db.query(ChecklistItemSectionTarget).filter(
        ChecklistItemSectionTarget.checklist_item_id == item_id
    ).delete()
    for sid in section_ids:
        sec = db.query(Section).filter(Section.id == sid).first()
        if sec:
            db.add(ChecklistItemSectionTarget(checklist_item_id=item_id, section_id=sid))


# ── Checklist CRUD ────────────────────────────────────────────────────────

@router.get("/cases/{case_id}/checklists", response_model=list[ChecklistOut])
def list_checklists(case_id: str, db: Session = Depends(get_db)):
    cls = db.query(Checklist).filter(Checklist.case_id == case_id).all()
    return [_checklist_out(cl, db) for cl in cls]


@router.post("/cases/{case_id}/checklists", response_model=ChecklistOut, status_code=201)
def create_checklist(case_id: str, body: ChecklistCreate, db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    cl = Checklist(case_id=case_id, name=body.name)
    db.add(cl)
    db.flush()
    db.add(AuditLog(case_id=case_id, action="created", entity_type="checklist", entity_id=cl.id))
    db.commit()
    db.refresh(cl)
    return _checklist_out(cl, db)


@router.delete("/checklists/{cl_id}", status_code=204)
def delete_checklist(cl_id: str, db: Session = Depends(get_db)):
    cl = db.query(Checklist).filter(Checklist.id == cl_id).first()
    if not cl:
        raise HTTPException(404, "Checklist not found")
    db.delete(cl)
    db.commit()


# ── ChecklistItem CRUD ────────────────────────────────────────────────────

@router.post("/checklists/{cl_id}/items", response_model=ChecklistItemOut, status_code=201)
def create_checklist_item(cl_id: str, body: ChecklistItemCreate, db: Session = Depends(get_db)):
    cl = db.query(Checklist).filter(Checklist.id == cl_id).first()
    if not cl:
        raise HTTPException(404, "Checklist not found")
    item = ChecklistItem(checklist_id=cl_id, description=body.description, order=body.order)
    db.add(item)
    db.flush()
    if body.target_section_ids:
        _sync_targets(item.id, body.target_section_ids, db)
    db.add(AuditLog(case_id=cl.case_id, action="created", entity_type="checklist_item", entity_id=item.id))
    db.commit()
    db.refresh(item)
    return _item_out(item, db)


@router.put("/checklist-items/{item_id}", response_model=ChecklistItemOut)
def update_checklist_item(item_id: str, body: ChecklistItemUpdate, db: Session = Depends(get_db)):
    item = db.query(ChecklistItem).filter(ChecklistItem.id == item_id).first()
    if not item:
        raise HTTPException(404, "ChecklistItem not found")
    if body.description is not None:
        item.description = body.description
    if body.status is not None:
        item.status = body.status
    if body.order is not None:
        item.order = body.order
    if body.notes is not None:
        item.notes = body.notes
    if body.target_section_ids is not None:
        _sync_targets(item.id, body.target_section_ids, db)
    db.commit()
    db.refresh(item)
    return _item_out(item, db)


@router.delete("/checklist-items/{item_id}", status_code=204)
def delete_checklist_item(item_id: str, db: Session = Depends(get_db)):
    item = db.query(ChecklistItem).filter(ChecklistItem.id == item_id).first()
    if not item:
        raise HTTPException(404, "ChecklistItem not found")
    db.delete(item)
    db.commit()


# ── Item section targets (upsert) ────────────────────────────────────────

@router.put("/checklist-items/{item_id}/targets", response_model=ChecklistItemOut)
def upsert_item_targets(item_id: str, body: ItemTargetsUpsert, db: Session = Depends(get_db)):
    item = db.query(ChecklistItem).filter(ChecklistItem.id == item_id).first()
    if not item:
        raise HTTPException(404, "ChecklistItem not found")
    _sync_targets(item.id, body.target_section_ids, db)
    db.commit()
    db.refresh(item)
    return _item_out(item, db)


# ── EvidenceLink CRUD ─────────────────────────────────────────────────────

@router.post("/checklist-items/{item_id}/evidence", response_model=EvidenceLinkOut, status_code=201)
def create_evidence_link(item_id: str, body: EvidenceLinkCreate, db: Session = Depends(get_db)):
    item = db.query(ChecklistItem).filter(ChecklistItem.id == item_id).first()
    if not item:
        raise HTTPException(404, "ChecklistItem not found")
    page = db.query(Page).filter(Page.id == body.page_id).first()
    if not page:
        raise HTTPException(400, "Page not found")
    ev = EvidenceLink(checklist_item_id=item_id, page_id=body.page_id, notes=body.notes)
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return _evidence_out(ev, db)


@router.delete("/evidence-links/{ev_id}", status_code=204)
def delete_evidence_link(ev_id: str, db: Session = Depends(get_db)):
    ev = db.query(EvidenceLink).filter(EvidenceLink.id == ev_id).first()
    if not ev:
        raise HTTPException(404, "EvidenceLink not found")
    db.delete(ev)
    db.commit()
