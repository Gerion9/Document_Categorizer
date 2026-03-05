"""Router – Complex QC Checklists (hierarchical builder, manual-only)."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    AuditLog,
    Case,
    Page,
    QCAnswerStatus,
    QCChecklist,
    QCLinkPreset,
    QCLinkPresetMapping,
    QCPart,
    QCQuestion,
    QCQuestionEvidence,
    Section,
)
from ..schemas import (
    QCChecklistCreate,
    QCChecklistOut,
    QCEvidenceCreate,
    QCLinkPresetCreate,
    QCLinkPresetOut,
    QCLinkPresetMappingOut,
    QCPartCreate,
    QCPartOut,
    QCPartUpdate,
    QCQuestionCreate,
    QCQuestionEvidenceOut,
    QCQuestionOut,
    QCQuestionUpdate,
    ReorderRequest,
)

router = APIRouter(tags=["qc-checklist"])


# ── helpers ───────────────────────────────────────────────────────────────

def _question_out(q: QCQuestion) -> QCQuestionOut:
    return QCQuestionOut(
        id=q.id,
        part_id=q.part_id,
        code=q.code,
        description=q.description,
        where_to_verify=q.where_to_verify or "",
        order=q.order or 0,
        answer=q.answer or QCAnswerStatus.UNANSWERED.value,
        correction=q.correction or "",
        notes=q.notes or "",
        answered_by=q.answered_by,
        answered_at=q.answered_at,
        ai_answer=q.ai_answer,
        ai_notes=q.ai_notes or "",
        ai_confidence=q.ai_confidence,
        ai_verified_at=q.ai_verified_at,
        target_section_ids=q.target_section_ids or [],
        evidence=[
            QCQuestionEvidenceOut(
                id=ev.id, question_id=ev.question_id,
                page_id=ev.page_id, notes=ev.notes or "",
                created_at=ev.created_at,
            )
            for ev in q.evidence
        ],
    )


def _part_out(part: QCPart, all_parts: list[QCPart]) -> QCPartOut:
    child_parts = sorted(
        [p for p in all_parts if p.parent_part_id == part.id],
        key=lambda p: p.order,
    )
    return QCPartOut(
        id=part.id,
        checklist_id=part.checklist_id,
        parent_part_id=part.parent_part_id,
        name=part.name,
        code=part.code,
        order=part.order or 0,
        depth=part.depth or 0,
        questions=[_question_out(q) for q in sorted(part.questions, key=lambda q: q.order)],
        children=[_part_out(c, all_parts) for c in child_parts],
    )


def _count_questions(parts: list[QCPart]) -> tuple[int, int]:
    total = 0
    answered = 0
    for p in parts:
        for q in p.questions:
            total += 1
            if q.answer and q.answer != QCAnswerStatus.UNANSWERED.value:
                answered += 1
    return total, answered


def _checklist_out(cl: QCChecklist) -> QCChecklistOut:
    all_parts = list(cl.parts)
    roots = sorted(
        [p for p in all_parts if not p.parent_part_id],
        key=lambda p: p.order,
    )
    total_q, answered_q = _count_questions(all_parts)
    return QCChecklistOut(
        id=cl.id,
        name=cl.name,
        description=cl.description or "",
        case_id=cl.case_id,
        is_template=cl.is_template or False,
        source_template_id=cl.source_template_id,
        created_at=cl.created_at,
        parts=[_part_out(r, all_parts) for r in roots],
        total_questions=total_q,
        answered_questions=answered_q,
    )


def _compute_depth(part_id: str | None, all_parts: list[QCPart]) -> int:
    if not part_id:
        return 0
    lookup = {p.id: p for p in all_parts}
    depth = 0
    cur = part_id
    while cur:
        p = lookup.get(cur)
        if not p or not p.parent_part_id:
            break
        depth += 1
        cur = p.parent_part_id
    return depth


# ── QC Checklist CRUD ─────────────────────────────────────────────────────

@router.get("/qc-templates", response_model=list[QCChecklistOut])
def list_qc_templates(db: Session = Depends(get_db)):
    """List all QC checklist templates (is_template=True)."""
    cls = db.query(QCChecklist).filter(QCChecklist.is_template == True).order_by(QCChecklist.created_at.desc()).all()
    return [_checklist_out(cl) for cl in cls]


@router.get("/cases/{case_id}/qc-checklists", response_model=list[QCChecklistOut])
def list_case_qc_checklists(case_id: str, db: Session = Depends(get_db)):
    """List QC checklists for a specific case."""
    cls = db.query(QCChecklist).filter(QCChecklist.case_id == case_id, QCChecklist.is_template == False).all()
    return [_checklist_out(cl) for cl in cls]


@router.post("/qc-checklists", response_model=QCChecklistOut, status_code=201)
def create_qc_checklist(body: QCChecklistCreate, case_id: Optional[str] = Query(None), db: Session = Depends(get_db)):
    """Create a new QC checklist.  Pass case_id=<id> for a case instance, omit for template."""
    cl = QCChecklist(
        name=body.name,
        description=body.description,
        case_id=case_id,
        is_template=body.is_template,
    )
    db.add(cl)
    db.commit()
    db.refresh(cl)
    return _checklist_out(cl)


# ── Seed I-914 Template (MUST be before {cl_id} routes) ───────────────────

@router.post("/qc-checklists/seed/i914", response_model=QCChecklistOut, status_code=201)
def seed_i914_template(db: Session = Depends(get_db)):
    """Idempotent: create the I-914 QC template if it doesn't already exist."""
    existing = (
        db.query(QCChecklist)
        .filter(QCChecklist.is_template == True, QCChecklist.name.contains("I-914"))
        .first()
    )
    if existing:
        return _checklist_out(existing)

    from ..seed_data.i914_template import I914_TEMPLATE

    tpl = QCChecklist(
        name=I914_TEMPLATE["name"],
        description=I914_TEMPLATE["description"],
        is_template=True,
    )
    db.add(tpl)
    db.flush()

    def _create_parts(parts_data: list[dict], parent_id: str | None, depth: int):
        for idx, pdata in enumerate(parts_data):
            part = QCPart(
                checklist_id=tpl.id,
                parent_part_id=parent_id,
                name=pdata["name"],
                code=pdata["code"],
                order=idx,
                depth=depth,
            )
            db.add(part)
            db.flush()

            for qidx, qdata in enumerate(pdata.get("questions", [])):
                q = QCQuestion(
                    part_id=part.id,
                    code=qdata["code"],
                    description=qdata["description"],
                    where_to_verify=qdata.get("where_to_verify", ""),
                    order=qidx,
                )
                db.add(q)

            if "subparts" in pdata:
                _create_parts(pdata["subparts"], part.id, depth + 1)

    _create_parts(I914_TEMPLATE["parts"], None, 0)

    db.commit()
    db.refresh(tpl)
    return _checklist_out(tpl)


@router.get("/qc-checklists/{cl_id}", response_model=QCChecklistOut)
def get_qc_checklist(cl_id: str, db: Session = Depends(get_db)):
    cl = db.query(QCChecklist).filter(QCChecklist.id == cl_id).first()
    if not cl:
        raise HTTPException(404, "QC Checklist not found")
    return _checklist_out(cl)


@router.delete("/qc-checklists/{cl_id}", status_code=204)
def delete_qc_checklist(cl_id: str, db: Session = Depends(get_db)):
    cl = db.query(QCChecklist).filter(QCChecklist.id == cl_id).first()
    if not cl:
        raise HTTPException(404)
    db.delete(cl)
    db.commit()


# ── Apply template to case ────────────────────────────────────────────────

@router.post("/cases/{case_id}/qc-checklists/apply/{template_id}", response_model=QCChecklistOut, status_code=201)
def apply_qc_template(case_id: str, template_id: str, db: Session = Depends(get_db)):
    """Deep-copy a QC template into a case instance."""
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    tpl = db.query(QCChecklist).filter(QCChecklist.id == template_id, QCChecklist.is_template == True).first()
    if not tpl:
        raise HTTPException(404, "Template not found")

    # Create instance
    inst = QCChecklist(
        name=tpl.name,
        description=tpl.description,
        case_id=case_id,
        is_template=False,
        source_template_id=tpl.id,
    )
    db.add(inst)
    db.flush()

    # Deep-copy parts + questions
    part_map: dict[str, str] = {}  # old_id → new_id
    all_tpl_parts = list(tpl.parts)

    def _copy_parts(parent_old_id: str | None, parent_new_id: str | None):
        children = sorted(
            [p for p in all_tpl_parts if p.parent_part_id == parent_old_id],
            key=lambda p: p.order,
        )
        for p in children:
            new_part = QCPart(
                checklist_id=inst.id,
                parent_part_id=parent_new_id,
                name=p.name,
                code=p.code,
                order=p.order,
                depth=p.depth or 0,
            )
            db.add(new_part)
            db.flush()
            part_map[p.id] = new_part.id

            # Copy questions
            for q in sorted(p.questions, key=lambda q: q.order):
                new_q = QCQuestion(
                    part_id=new_part.id,
                    code=q.code,
                    description=q.description,
                    where_to_verify=q.where_to_verify,
                    order=q.order,
                )
                db.add(new_q)

            _copy_parts(p.id, new_part.id)

    _copy_parts(None, None)

    if case_id:
        db.add(AuditLog(case_id=case_id, action="applied_qc_template", entity_type="qc_checklist",
                        entity_id=inst.id, details={"template_name": tpl.name}))

    db.flush()

    # ── Auto-apply link preset if one exists for this QC template ──
    preset = (
        db.query(QCLinkPreset)
        .filter(QCLinkPreset.qc_template_id == tpl.id)
        .order_by(QCLinkPreset.created_at.desc())
        .first()
    )
    if preset:
        _apply_link_preset_to_checklist(inst, preset, db)

    db.commit()
    db.refresh(inst)
    return _checklist_out(inst)


# ── QC Part CRUD ──────────────────────────────────────────────────────────

@router.post("/qc-checklists/{cl_id}/parts", response_model=QCPartOut, status_code=201)
def create_qc_part(cl_id: str, body: QCPartCreate, db: Session = Depends(get_db)):
    cl = db.query(QCChecklist).filter(QCChecklist.id == cl_id).first()
    if not cl:
        raise HTTPException(404, "QC Checklist not found")
    part = QCPart(
        checklist_id=cl_id,
        parent_part_id=body.parent_part_id,
        name=body.name,
        code=body.code,
        order=body.order,
    )
    db.add(part)
    db.flush()
    all_parts = list(cl.parts) + [part]
    part.depth = _compute_depth(part.parent_part_id, all_parts)
    db.commit()
    db.refresh(part)
    return _part_out(part, list(cl.parts))


@router.put("/qc-parts/{part_id}", response_model=QCPartOut)
def update_qc_part(part_id: str, body: QCPartUpdate, db: Session = Depends(get_db)):
    part = db.query(QCPart).filter(QCPart.id == part_id).first()
    if not part:
        raise HTTPException(404)
    if body.name is not None:
        part.name = body.name
    if body.code is not None:
        part.code = body.code
    if body.order is not None:
        part.order = body.order
    db.commit()
    db.refresh(part)
    cl = db.query(QCChecklist).filter(QCChecklist.id == part.checklist_id).first()
    return _part_out(part, list(cl.parts) if cl else [])


@router.delete("/qc-parts/{part_id}", status_code=204)
def delete_qc_part(part_id: str, db: Session = Depends(get_db)):
    part = db.query(QCPart).filter(QCPart.id == part_id).first()
    if not part:
        raise HTTPException(404)
    db.delete(part)
    db.commit()


@router.put("/qc-parts/reorder", status_code=200)
def reorder_qc_parts(body: ReorderRequest, db: Session = Depends(get_db)):
    for item in body.items:
        p = db.query(QCPart).filter(QCPart.id == item.id).first()
        if p:
            p.order = item.order
    db.commit()
    return {"ok": True}


# ── QC Question CRUD ──────────────────────────────────────────────────────

@router.post("/qc-parts/{part_id}/questions", response_model=QCQuestionOut, status_code=201)
def create_qc_question(part_id: str, body: QCQuestionCreate, db: Session = Depends(get_db)):
    part = db.query(QCPart).filter(QCPart.id == part_id).first()
    if not part:
        raise HTTPException(404, "Part not found")
    q = QCQuestion(
        part_id=part_id,
        code=body.code,
        description=body.description,
        where_to_verify=body.where_to_verify,
        order=body.order,
    )
    db.add(q)
    db.commit()
    db.refresh(q)
    return _question_out(q)


@router.put("/qc-questions/{q_id}", response_model=QCQuestionOut)
def update_qc_question(q_id: str, body: QCQuestionUpdate, db: Session = Depends(get_db)):
    q = db.query(QCQuestion).filter(QCQuestion.id == q_id).first()
    if not q:
        raise HTTPException(404)
    if body.code is not None:
        q.code = body.code
    if body.description is not None:
        q.description = body.description
    if body.where_to_verify is not None:
        q.where_to_verify = body.where_to_verify
    if body.order is not None:
        q.order = body.order
    if body.answer is not None:
        q.answer = body.answer
        from datetime import datetime, timezone
        q.answered_at = datetime.now(timezone.utc)
    if body.correction is not None:
        q.correction = body.correction
    if body.notes is not None:
        q.notes = body.notes
    if body.target_section_ids is not None:
        q.target_section_ids = body.target_section_ids
    db.commit()
    db.refresh(q)
    return _question_out(q)


@router.delete("/qc-questions/{q_id}", status_code=204)
def delete_qc_question(q_id: str, db: Session = Depends(get_db)):
    q = db.query(QCQuestion).filter(QCQuestion.id == q_id).first()
    if not q:
        raise HTTPException(404)
    db.delete(q)
    db.commit()


@router.put("/qc-questions/reorder", status_code=200)
def reorder_qc_questions(body: ReorderRequest, db: Session = Depends(get_db)):
    for item in body.items:
        q = db.query(QCQuestion).filter(QCQuestion.id == item.id).first()
        if q:
            q.order = item.order
    db.commit()
    return {"ok": True}


# ── QC Question Evidence ──────────────────────────────────────────────────

@router.post("/qc-questions/{q_id}/evidence", response_model=QCQuestionEvidenceOut, status_code=201)
def add_qc_evidence(q_id: str, body: QCEvidenceCreate, db: Session = Depends(get_db)):
    q = db.query(QCQuestion).filter(QCQuestion.id == q_id).first()
    if not q:
        raise HTTPException(404)
    page = db.query(Page).filter(Page.id == body.page_id).first()
    if not page:
        raise HTTPException(400, "Page not found")
    ev = QCQuestionEvidence(question_id=q_id, page_id=body.page_id, notes=body.notes)
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return QCQuestionEvidenceOut(
        id=ev.id, question_id=ev.question_id,
        page_id=ev.page_id, notes=ev.notes or "",
        created_at=ev.created_at,
    )


@router.delete("/qc-evidence/{ev_id}", status_code=204)
def delete_qc_evidence(ev_id: str, db: Session = Depends(get_db)):
    ev = db.query(QCQuestionEvidence).filter(QCQuestionEvidence.id == ev_id).first()
    if not ev:
        raise HTTPException(404)
    db.delete(ev)
    db.commit()


# ── Save case checklist as reusable template ──────────────────────────────

@router.post("/qc-checklists/{cl_id}/save-as-template", response_model=QCChecklistOut, status_code=201)
def save_qc_as_template(cl_id: str, db: Session = Depends(get_db)):
    """Clone a case-bound QC checklist into a reusable template."""
    source = db.query(QCChecklist).filter(QCChecklist.id == cl_id).first()
    if not source:
        raise HTTPException(404, "QC Checklist not found")

    tpl = QCChecklist(
        name=f"{source.name} (plantilla)",
        description=source.description or "",
        is_template=True,
    )
    db.add(tpl)
    db.flush()

    all_parts = list(source.parts)
    part_map: dict[str, str] = {}

    def _copy(parent_old: str | None, parent_new: str | None):
        children = sorted([p for p in all_parts if p.parent_part_id == parent_old], key=lambda p: p.order)
        for p in children:
            np = QCPart(checklist_id=tpl.id, parent_part_id=parent_new, name=p.name, code=p.code, order=p.order, depth=p.depth or 0)
            db.add(np)
            db.flush()
            part_map[p.id] = np.id
            for q in sorted(p.questions, key=lambda x: x.order):
                db.add(QCQuestion(part_id=np.id, code=q.code, description=q.description,
                                  where_to_verify=q.where_to_verify, order=q.order,
                                  target_section_ids=q.target_section_ids or []))
            _copy(p.id, np.id)

    _copy(None, None)
    db.commit()
    db.refresh(tpl)
    return _checklist_out(tpl)


# ── AI Verification ───────────────────────────────────────────────────────

@router.post("/qc-questions/{q_id}/ai-verify", response_model=QCQuestionOut)
def ai_verify_question(q_id: str, db: Session = Depends(get_db)):
    """Use Gemini Vision to automatically verify a QC question against its evidence pages."""
    from ..services.extraction_service import is_configured as gemini_ok
    if not gemini_ok():
        raise HTTPException(503, "GEMINI_API_KEY not configured")

    q = db.query(QCQuestion).filter(QCQuestion.id == q_id).first()
    if not q:
        raise HTTPException(404, "Question not found")

    from ..services.ai_verify_service import verify_question_multi_page, verify_question

    STORAGE_DIR = __import__("pathlib").Path(__file__).resolve().parent.parent.parent / "storage"

    # Collect page images: from evidence links or from target sections
    image_paths: list[str] = []
    for ev in q.evidence:
        page = db.query(Page).filter(Page.id == ev.page_id).first()
        if page and page.file_path:
            abs_path = str(STORAGE_DIR / page.file_path)
            image_paths.append(abs_path)

    # If no evidence, try pages from target sections
    if not image_paths and q.target_section_ids:
        from ..models import Section as SectionModel
        for sid in q.target_section_ids:
            sec_pages = db.query(Page).filter(Page.section_id == sid).order_by(Page.order_in_section).all()
            for p in sec_pages[:3]:
                if p.file_path:
                    image_paths.append(str(STORAGE_DIR / p.file_path))

    if not image_paths:
        raise HTTPException(400, "No evidence pages or target section pages available for this question")

    # Call Gemini
    if len(image_paths) == 1:
        result = verify_question(image_paths[0], q.description, q.where_to_verify or "")
    else:
        result = verify_question_multi_page(image_paths, q.description, q.where_to_verify or "")

    # Save AI result
    from datetime import datetime, timezone
    q.ai_answer = result["answer"]
    q.ai_notes = result.get("explanation", "")
    q.ai_confidence = result.get("confidence", "low")
    q.ai_verified_at = datetime.now(timezone.utc)

    # If no manual answer yet, auto-fill as suggestion
    if q.answer == QCAnswerStatus.UNANSWERED.value:
        q.answer = result["answer"]
        q.correction = result.get("correction", "")
        q.notes = f"[AI {result.get('confidence', '')}] {result.get('explanation', '')}"

    db.commit()
    db.refresh(q)
    return _question_out(q)


@router.post("/qc-parts/{part_id}/ai-verify-all")
def ai_verify_part(part_id: str, db: Session = Depends(get_db)):
    """Queue AI verification for ALL questions in a part (and subparts)."""
    from ..services.extraction_service import is_configured as gemini_ok
    if not gemini_ok():
        raise HTTPException(503, "GEMINI_API_KEY not configured")

    part = db.query(QCPart).filter(QCPart.id == part_id).first()
    if not part:
        raise HTTPException(404, "Part not found")

    verified = 0
    skipped = 0
    errors = 0

    def _verify_part_questions(p: QCPart):
        nonlocal verified, skipped, errors
        for q in p.questions:
            try:
                # Call the single-question endpoint logic
                STORAGE_DIR = __import__("pathlib").Path(__file__).resolve().parent.parent.parent / "storage"
                image_paths: list[str] = []
                for ev in q.evidence:
                    page = db.query(Page).filter(Page.id == ev.page_id).first()
                    if page and page.file_path:
                        image_paths.append(str(STORAGE_DIR / page.file_path))
                if not image_paths and q.target_section_ids:
                    for sid in (q.target_section_ids or []):
                        sec_pages = db.query(Page).filter(Page.section_id == sid).order_by(Page.order_in_section).all()
                        for pg in sec_pages[:3]:
                            if pg.file_path:
                                image_paths.append(str(STORAGE_DIR / pg.file_path))

                if not image_paths:
                    skipped += 1
                    continue

                from ..services.ai_verify_service import verify_question_multi_page, verify_question
                if len(image_paths) == 1:
                    result = verify_question(image_paths[0], q.description, q.where_to_verify or "")
                else:
                    result = verify_question_multi_page(image_paths, q.description, q.where_to_verify or "")

                from datetime import datetime, timezone
                q.ai_answer = result["answer"]
                q.ai_notes = result.get("explanation", "")
                q.ai_confidence = result.get("confidence", "low")
                q.ai_verified_at = datetime.now(timezone.utc)
                if q.answer == QCAnswerStatus.UNANSWERED.value:
                    q.answer = result["answer"]
                    q.correction = result.get("correction", "")
                    q.notes = f"[AI {result.get('confidence', '')}] {result.get('explanation', '')}"
                verified += 1
            except Exception:
                errors += 1

        # Recurse into child parts
        children = db.query(QCPart).filter(QCPart.parent_part_id == p.id).all()
        for child in children:
            _verify_part_questions(child)

    _verify_part_questions(part)
    db.commit()

    return {"verified": verified, "skipped": skipped, "errors": errors}


# ── QC Link Preset helpers ────────────────────────────────────────────────

def _preset_out(preset: QCLinkPreset) -> QCLinkPresetOut:
    return QCLinkPresetOut(
        id=preset.id,
        name=preset.name,
        qc_template_id=preset.qc_template_id,
        doc_template_id=preset.doc_template_id,
        created_at=preset.created_at,
        mappings=[
            QCLinkPresetMappingOut(
                id=m.id,
                question_code=m.question_code,
                section_path_codes=m.section_path_codes or [],
            )
            for m in preset.mappings
        ],
        mapping_count=len(preset.mappings),
    )


def _resolve_path_code_to_section_id(path_code: str, case_id: str, db: Session) -> str | None:
    """Find a section in this case whose path_code matches."""
    from ..models import DocumentType
    sec = (
        db.query(Section)
        .join(DocumentType, DocumentType.id == Section.document_type_id)
        .filter(DocumentType.case_id == case_id, Section.path_code == path_code)
        .first()
    )
    return sec.id if sec else None


def _apply_link_preset_to_checklist(cl: QCChecklist, preset: QCLinkPreset, db: Session):
    """Apply a link preset to a case-bound checklist, resolving path_codes → section IDs."""
    if not cl.case_id:
        return

    # Build lookup: question_code → list of path_codes
    code_to_paths: dict[str, list[str]] = {}
    for m in preset.mappings:
        code_to_paths[m.question_code] = m.section_path_codes or []

    # Walk all questions in the checklist
    all_parts = list(cl.parts)
    for part in all_parts:
        for q in part.questions:
            paths = code_to_paths.get(q.code)
            if not paths:
                continue
            # Resolve each path_code to a section_id in this case
            resolved: list[str] = []
            for pc in paths:
                sid = _resolve_path_code_to_section_id(pc, cl.case_id, db)
                if sid:
                    resolved.append(sid)
            if resolved:
                q.target_section_ids = resolved


# ── QC Link Preset endpoints ──────────────────────────────────────────────

@router.post("/qc-checklists/{cl_id}/link-presets", response_model=QCLinkPresetOut, status_code=201)
def save_link_preset(cl_id: str, body: QCLinkPresetCreate, db: Session = Depends(get_db)):
    """Save a reusable link preset from a case-bound QC checklist's current target_section_ids."""
    cl = db.query(QCChecklist).filter(QCChecklist.id == cl_id).first()
    if not cl:
        raise HTTPException(404, "QC Checklist not found")
    if not cl.case_id:
        raise HTTPException(400, "Can only save presets from a case-bound checklist")

    preset_name = body.name or f"Preset - {cl.name}"
    preset = QCLinkPreset(
        name=preset_name,
        qc_template_id=cl.source_template_id,
        doc_template_id=body.doc_template_id,
    )
    db.add(preset)
    db.flush()

    # Walk all questions, convert target_section_ids → section_path_codes
    all_parts = list(cl.parts)
    for part in all_parts:
        for q in part.questions:
            sids = q.target_section_ids or []
            if not sids:
                continue
            path_codes: list[str] = []
            for sid in sids:
                sec = db.query(Section).filter(Section.id == sid).first()
                if sec and sec.path_code:
                    path_codes.append(sec.path_code)
            if path_codes:
                db.add(QCLinkPresetMapping(
                    preset_id=preset.id,
                    question_code=q.code,
                    section_path_codes=path_codes,
                ))

    if cl.case_id:
        db.add(AuditLog(case_id=cl.case_id, action="saved_link_preset", entity_type="qc_link_preset",
                        entity_id=preset.id, details={"preset_name": preset_name}))

    db.commit()
    db.refresh(preset)
    return _preset_out(preset)


@router.get("/qc-link-presets", response_model=list[QCLinkPresetOut])
def list_link_presets(qc_template_id: Optional[str] = Query(None), db: Session = Depends(get_db)):
    """List all link presets, optionally filtered by QC template."""
    q = db.query(QCLinkPreset).order_by(QCLinkPreset.created_at.desc())
    if qc_template_id:
        q = q.filter(QCLinkPreset.qc_template_id == qc_template_id)
    return [_preset_out(p) for p in q.all()]


@router.get("/qc-link-presets/{preset_id}", response_model=QCLinkPresetOut)
def get_link_preset(preset_id: str, db: Session = Depends(get_db)):
    preset = db.query(QCLinkPreset).filter(QCLinkPreset.id == preset_id).first()
    if not preset:
        raise HTTPException(404, "Preset not found")
    return _preset_out(preset)


@router.delete("/qc-link-presets/{preset_id}", status_code=204)
def delete_link_preset(preset_id: str, db: Session = Depends(get_db)):
    preset = db.query(QCLinkPreset).filter(QCLinkPreset.id == preset_id).first()
    if not preset:
        raise HTTPException(404, "Preset not found")
    db.delete(preset)
    db.commit()


@router.post("/cases/{case_id}/qc-checklists/{cl_id}/apply-link-preset/{preset_id}", response_model=QCChecklistOut)
def apply_link_preset(case_id: str, cl_id: str, preset_id: str, db: Session = Depends(get_db)):
    """Manually apply a link preset to a case-bound QC checklist."""
    cl = db.query(QCChecklist).filter(QCChecklist.id == cl_id, QCChecklist.case_id == case_id).first()
    if not cl:
        raise HTTPException(404, "QC Checklist not found in this case")

    preset = db.query(QCLinkPreset).filter(QCLinkPreset.id == preset_id).first()
    if not preset:
        raise HTTPException(404, "Preset not found")

    _apply_link_preset_to_checklist(cl, preset, db)

    db.add(AuditLog(case_id=case_id, action="applied_link_preset", entity_type="qc_link_preset",
                    entity_id=preset.id, details={"preset_name": preset.name, "checklist_id": cl.id}))
    db.commit()
    db.refresh(cl)
    return _checklist_out(cl)

