"""Router -- Upload, classify, reorder pages + multi-section linking."""

import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    AuditLog,
    Case,
    DocumentType,
    Page,
    PageSectionLink,
    PageStatus,
    Section,
)
from ..schemas import (
    PageClassify,
    PageOut,
    PageSectionLinkCreate,
    PageSectionLinkOut,
    PageSetPrimary,
    PagesReorderBatch,
)
from ..services.indexing_service import index_existing_page_ocr, is_indexing_available
from ..services.ocr_index_service import delete_page_ocr_chunks
from ..services.pdf_service import process_image, save_uploaded_file, split_pdf

router = APIRouter(tags=["pages"])

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp"}


# ── Helper: build PageOut with section_links ──────────────────────────────

def _link_out(lk: PageSectionLink) -> PageSectionLinkOut:
    sec = lk.section
    dt = sec.document_type if sec else None
    return PageSectionLinkOut(
        id=lk.id,
        page_id=lk.page_id,
        section_id=lk.section_id,
        is_primary=lk.is_primary,
        order_in_section=lk.order_in_section or 0,
        created_at=lk.created_at,
        section_path_code=sec.path_code or "" if sec else "",
        section_name=sec.name if sec else "",
        document_type_code=dt.code if dt else "",
        document_type_name=dt.name if dt else "",
    )


def _page_out(p: Page) -> PageOut:
    links = sorted(p.section_links, key=lambda l: (not l.is_primary, l.order_in_section or 0))
    link_outs = [_link_out(lk) for lk in links]
    d = {
        "id": p.id,
        "case_id": p.case_id,
        "source_document_id": p.source_document_id,
        "original_filename": p.original_filename,
        "original_page_number": p.original_page_number,
        "thumbnail_path": p.thumbnail_path,
        "file_path": p.file_path,
        "document_type_id": p.document_type_id,
        "section_id": p.section_id,
        "subindex": p.subindex,
        "order_in_section": p.order_in_section,
        "status": p.status,
        "metadata_json": p.metadata_json or {},
        "ocr_text": p.ocr_text,
        "extraction_status": p.extraction_status or "pending",
        "extraction_method": p.extraction_method,
        "index_status": p.index_status or "pending",
        "index_method": p.index_method,
        "indexed_at": p.indexed_at,
        "indexed_vector_count": p.indexed_vector_count or 0,
        "pinecone_document_id": p.pinecone_document_id,
        "created_at": p.created_at,
        "updated_at": p.updated_at,
        "section_links": link_outs,
        "link_count": len(link_outs),
    }
    return PageOut(**d)


def _queue_reindex_if_needed(background_tasks: BackgroundTasks, page: Page | None) -> None:
    if not page:
        return
    if not page.ocr_text or not page.ocr_text.strip():
        return
    if not is_indexing_available():
        return
    background_tasks.add_task(index_existing_page_ocr, page.id)


def _sync_legacy_fields(page: Page, db: Session):
    """Keep legacy page.section_id / document_type_id in sync with primary link."""
    primary = (
        db.query(PageSectionLink)
        .filter(PageSectionLink.page_id == page.id, PageSectionLink.is_primary == True)
        .first()
    )
    if primary:
        sec = db.query(Section).filter(Section.id == primary.section_id).first()
        if sec:
            page.section_id = sec.id
            page.document_type_id = sec.document_type_id
            dt = sec.document_type
            page.subindex = f"{dt.code}{sec.code}" if dt else sec.code
            page.order_in_section = primary.order_in_section
            page.status = PageStatus.CLASSIFIED.value
    else:
        has_any = db.query(PageSectionLink).filter(PageSectionLink.page_id == page.id).first()
        if not has_any:
            page.section_id = None
            page.document_type_id = None
            page.subindex = None
            page.order_in_section = None
            page.status = PageStatus.UNCLASSIFIED.value
        else:
            page.status = PageStatus.CLASSIFIED.value


def _next_order(db: Session, section_id: str, exclude_page_id: str | None = None) -> int:
    """Get next order_in_section for a section's links."""
    q = db.query(PageSectionLink.order_in_section).filter(
        PageSectionLink.section_id == section_id
    )
    if exclude_page_id:
        q = q.filter(PageSectionLink.page_id != exclude_page_id)
    max_row = q.order_by(PageSectionLink.order_in_section.desc()).first()
    return (max_row[0] or 0) + 1 if max_row else 1


# ── Upload ────────────────────────────────────────────────────────────────

@router.post("/cases/{case_id}/upload", response_model=list[PageOut], status_code=201)
async def upload_files(
    case_id: str,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """Upload one or more PDF / image files. PDFs are split into individual pages."""
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")

    created_pages: list[Page] = []

    for f in files:
        content = await f.read()
        filename = f.filename or "unknown"
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        upload_path = save_uploaded_file(content, filename)

        if ext == ".pdf":
            page_infos = split_pdf(upload_path)
        elif ext in IMAGE_EXTENSIONS:
            page_infos = [process_image(upload_path)]
        else:
            raise HTTPException(400, f"Unsupported file type: {ext}")

        file_source_document_id = str(uuid.uuid4())

        for info in page_infos:
            page = Page(
                case_id=case_id,
                source_document_id=file_source_document_id,
                original_filename=filename,
                original_page_number=info["page_number"],
                file_path=info["file_path"],
                thumbnail_path=info["thumbnail_path"],
                status=PageStatus.UNCLASSIFIED.value,
            )
            db.add(page)
            created_pages.append(page)

    db.flush()
    db.add(
        AuditLog(
            case_id=case_id,
            action="uploaded",
            entity_type="page",
            details={"count": len(created_pages)},
        )
    )
    db.commit()
    for p in created_pages:
        db.refresh(p)
    return [_page_out(p) for p in created_pages]


# ── List pages ────────────────────────────────────────────────────────────

@router.get("/cases/{case_id}/pages", response_model=list[PageOut])
def list_pages(
    case_id: str,
    status: Optional[str] = Query(None),
    section_id: Optional[str] = Query(None),
    document_type_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(Page).filter(Page.case_id == case_id)
    if status:
        q = q.filter(Page.status == status)
    if section_id:
        # Include pages linked to this section (via page_section_links)
        linked_ids = (
            db.query(PageSectionLink.page_id)
            .filter(PageSectionLink.section_id == section_id)
            .subquery()
        )
        q = q.filter(Page.id.in_(linked_ids))
    if document_type_id:
        q = q.filter(Page.document_type_id == document_type_id)
    pages = q.order_by(Page.order_in_section.asc().nullslast(), Page.created_at).all()
    return [_page_out(p) for p in pages]


# ── Classify a page (moves primary to target section) ────────────────────

@router.put("/pages/{page_id}/classify", response_model=PageOut)
def classify_page(
    page_id: str,
    body: PageClassify,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    page = db.query(Page).filter(Page.id == page_id).first()
    if not page:
        raise HTTPException(404, "Page not found")

    sec = db.query(Section).filter(Section.id == body.section_id).first()
    if not sec:
        raise HTTPException(400, "Section not found")

    # Remove any existing primary link
    db.query(PageSectionLink).filter(
        PageSectionLink.page_id == page_id,
        PageSectionLink.is_primary == True,
    ).delete(synchronize_session="fetch")

    # Remove link to this section if it already existed as secondary
    db.query(PageSectionLink).filter(
        PageSectionLink.page_id == page_id,
        PageSectionLink.section_id == body.section_id,
    ).delete(synchronize_session="fetch")

    order = body.order_in_section if body.order_in_section is not None else _next_order(db, body.section_id, page_id)

    link = PageSectionLink(
        page_id=page_id,
        section_id=body.section_id,
        is_primary=True,
        order_in_section=order,
    )
    db.add(link)
    db.flush()

    # Keep legacy fields in sync
    _sync_legacy_fields(page, db)

    db.add(
        AuditLog(
            case_id=page.case_id,
            action="classified",
            entity_type="page",
            entity_id=page.id,
            details={"section": sec.name, "section_id": sec.id},
        )
    )
    db.commit()
    db.refresh(page)
    _queue_reindex_if_needed(background_tasks, page)
    return _page_out(page)


# ── Unclassify a page (remove ALL links) ──────────────────────────────────

@router.put("/pages/{page_id}/unclassify", response_model=PageOut)
def unclassify_page(
    page_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    page = db.query(Page).filter(Page.id == page_id).first()
    if not page:
        raise HTTPException(404, "Page not found")

    # Remove all section links
    db.query(PageSectionLink).filter(PageSectionLink.page_id == page_id).delete(synchronize_session="fetch")

    page.document_type_id = None
    page.section_id = None
    page.subindex = None
    page.order_in_section = None
    page.status = PageStatus.UNCLASSIFIED.value
    db.add(AuditLog(case_id=page.case_id, action="unclassified", entity_type="page", entity_id=page.id))
    db.commit()
    db.refresh(page)
    _queue_reindex_if_needed(background_tasks, page)
    return _page_out(page)


# ── Mark page as extra ────────────────────────────────────────────────────

@router.put("/pages/{page_id}/extra", response_model=PageOut)
def mark_extra(
    page_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    page = db.query(Page).filter(Page.id == page_id).first()
    if not page:
        raise HTTPException(404, "Page not found")
    # Remove all section links
    db.query(PageSectionLink).filter(PageSectionLink.page_id == page_id).delete(synchronize_session="fetch")
    page.document_type_id = None
    page.section_id = None
    page.subindex = None
    page.order_in_section = None
    page.status = PageStatus.EXTRA.value
    db.commit()
    db.refresh(page)
    _queue_reindex_if_needed(background_tasks, page)
    return _page_out(page)


# ── Multi-section link endpoints ──────────────────────────────────────────

@router.get("/pages/{page_id}/section-links", response_model=list[PageSectionLinkOut])
def get_page_links(page_id: str, db: Session = Depends(get_db)):
    """Get all section links for a page."""
    links = (
        db.query(PageSectionLink)
        .filter(PageSectionLink.page_id == page_id)
        .order_by(PageSectionLink.is_primary.desc(), PageSectionLink.order_in_section)
        .all()
    )
    return [_link_out(lk) for lk in links]


@router.post("/pages/{page_id}/section-links", response_model=PageOut, status_code=201)
def add_section_link(
    page_id: str,
    body: PageSectionLinkCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Link a page to a section. If is_primary=True, demotes any existing primary."""
    page = db.query(Page).filter(Page.id == page_id).first()
    if not page:
        raise HTTPException(404, "Page not found")
    sec = db.query(Section).filter(Section.id == body.section_id).first()
    if not sec:
        raise HTTPException(400, "Section not found")

    # Check if link already exists
    existing = (
        db.query(PageSectionLink)
        .filter(PageSectionLink.page_id == page_id, PageSectionLink.section_id == body.section_id)
        .first()
    )
    if existing:
        # Update primary status if needed
        if body.is_primary and not existing.is_primary:
            db.query(PageSectionLink).filter(
                PageSectionLink.page_id == page_id, PageSectionLink.is_primary == True
            ).update({"is_primary": False}, synchronize_session="fetch")
            existing.is_primary = True
        db.flush()
        _sync_legacy_fields(page, db)
        db.commit()
        db.refresh(page)
        _queue_reindex_if_needed(background_tasks, page)
        return _page_out(page)

    # If this is primary, demote any existing primary
    if body.is_primary:
        db.query(PageSectionLink).filter(
            PageSectionLink.page_id == page_id, PageSectionLink.is_primary == True
        ).update({"is_primary": False}, synchronize_session="fetch")

    # If page has no links at all, make this one primary regardless
    has_any = db.query(PageSectionLink).filter(PageSectionLink.page_id == page_id).first()
    make_primary = body.is_primary or not has_any

    link = PageSectionLink(
        page_id=page_id,
        section_id=body.section_id,
        is_primary=make_primary,
        order_in_section=_next_order(db, body.section_id, page_id),
    )
    db.add(link)
    db.flush()

    if make_primary:
        # Ensure only one primary
        db.query(PageSectionLink).filter(
            PageSectionLink.page_id == page_id,
            PageSectionLink.is_primary == True,
            PageSectionLink.id != link.id,
        ).update({"is_primary": False}, synchronize_session="fetch")

    _sync_legacy_fields(page, db)

    page.status = PageStatus.CLASSIFIED.value
    db.add(AuditLog(case_id=page.case_id, action="linked_section", entity_type="page", entity_id=page.id,
                    details={"section_id": body.section_id, "is_primary": make_primary}))
    db.commit()
    db.refresh(page)
    _queue_reindex_if_needed(background_tasks, page)
    return _page_out(page)


@router.delete("/pages/{page_id}/section-links/{section_id}", response_model=PageOut)
def remove_section_link(
    page_id: str,
    section_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Remove a page's link to a section. If removing primary, promote another link."""
    page = db.query(Page).filter(Page.id == page_id).first()
    if not page:
        raise HTTPException(404, "Page not found")

    link = (
        db.query(PageSectionLink)
        .filter(PageSectionLink.page_id == page_id, PageSectionLink.section_id == section_id)
        .first()
    )
    if not link:
        raise HTTPException(404, "Link not found")

    was_primary = link.is_primary
    db.delete(link)
    db.flush()

    # If we removed the primary, promote the oldest remaining link
    if was_primary:
        remaining = (
            db.query(PageSectionLink)
            .filter(PageSectionLink.page_id == page_id)
            .order_by(PageSectionLink.created_at)
            .first()
        )
        if remaining:
            remaining.is_primary = True

    _sync_legacy_fields(page, db)
    db.add(AuditLog(case_id=page.case_id, action="unlinked_section", entity_type="page", entity_id=page.id,
                    details={"section_id": section_id, "was_primary": was_primary}))
    db.commit()
    db.refresh(page)
    _queue_reindex_if_needed(background_tasks, page)
    return _page_out(page)


@router.put("/pages/{page_id}/section-links/primary", response_model=PageOut)
def set_primary_link(
    page_id: str,
    body: PageSetPrimary,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Change which section is the primary for this page."""
    page = db.query(Page).filter(Page.id == page_id).first()
    if not page:
        raise HTTPException(404, "Page not found")

    link = (
        db.query(PageSectionLink)
        .filter(PageSectionLink.page_id == page_id, PageSectionLink.section_id == body.section_id)
        .first()
    )
    if not link:
        raise HTTPException(404, "Link to this section not found. Add it first.")

    # Demote all, promote this one
    db.query(PageSectionLink).filter(
        PageSectionLink.page_id == page_id, PageSectionLink.is_primary == True
    ).update({"is_primary": False}, synchronize_session="fetch")

    link.is_primary = True
    _sync_legacy_fields(page, db)
    db.commit()
    db.refresh(page)
    _queue_reindex_if_needed(background_tasks, page)
    return _page_out(page)


# ── Reorder pages within a section (batch) ────────────────────────────────

@router.put("/pages/reorder", status_code=200)
def reorder_pages(body: PagesReorderBatch, db: Session = Depends(get_db)):
    for item in body.pages:
        # Update both legacy field and link table
        page = db.query(Page).filter(Page.id == item.page_id).first()
        if page:
            page.order_in_section = item.order_in_section
        link = (
            db.query(PageSectionLink)
            .filter(
                PageSectionLink.page_id == item.page_id,
                PageSectionLink.section_id == body.section_id,
            )
            .first()
        )
        if link:
            link.order_in_section = item.order_in_section
    db.commit()
    return {"ok": True}


# ── Delete a page ─────────────────────────────────────────────────────────

@router.delete("/pages/{page_id}", status_code=204)
def delete_page(page_id: str, db: Session = Depends(get_db)):
    page = db.query(Page).filter(Page.id == page_id).first()
    if not page:
        raise HTTPException(404, "Page not found")
    if is_indexing_available():
        try:
            delete_page_ocr_chunks(page.id, page.case_id)
        except Exception:
            pass
    db.add(AuditLog(case_id=page.case_id, action="deleted", entity_type="page", entity_id=page.id))
    db.delete(page)
    db.commit()
