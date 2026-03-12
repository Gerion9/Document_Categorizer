"""Router – Complex QC Checklists (hierarchical builder, manual-only)."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from datetime import datetime, timezone
import re
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..models import (
    AuditLog,
    Case,
    ExtractionStatus,
    Page,
    PageSectionLink,
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
    QCAutopilotJobOut,
    ReorderRequest,
)
from ..db_utils import get_or_404, reorder_entities
from ..services import qc_autopilot_jobs
from ..services.gemini_runtime_service import GeminiTokenTracker, create_token_tracker, log_token_summary

router = APIRouter(tags=["qc-checklist"])


_LOOKUP_TOKEN_VARIANTS: dict[str, set[str]] = {
    "application": {"applications", "app"},
    "applications": {"application", "app"},
    "app": {"application", "applications"},
    "certificate": {"cert"},
    "cert": {"certificate"},
    "document": {"documents", "docs", "doc"},
    "documents": {"document", "docs", "doc"},
    "docs": {"document", "documents", "doc"},
    "doc": {"document", "documents", "docs"},
    "record": {"records"},
    "records": {"record"},
}
_FORM_I914A_RE = re.compile(r"\bi\s*914a\b|\bsupplement\s*a\b", re.IGNORECASE)
_FORM_I914_RE = re.compile(r"\bi\s*914\b", re.IGNORECASE)


def _question_internal_key(q: QCQuestion) -> str:
    return str(q.id)


def _normalize_lookup_text(value: str) -> str:
    normalized = str(value or "").lower().replace("&", " and ")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _expand_lookup_aliases(value: str) -> set[str]:
    normalized = _normalize_lookup_text(value)
    if not normalized:
        return set()

    variants = {normalized}
    if normalized.startswith("form "):
        variants.add(normalized.removeprefix("form ").strip())

    without_prefix = re.sub(r"^(original)\s+", "", normalized).strip()
    without_suffix = re.sub(r"\s+(draft|drafts)$", "", normalized).strip()
    for candidate in (without_prefix, without_suffix):
        if candidate and candidate != normalized:
            variants.add(candidate)

    tokens = normalized.split()
    for idx, token in enumerate(tokens):
        for replacement in _LOOKUP_TOKEN_VARIANTS.get(token, set()):
            alias_tokens = tokens.copy()
            alias_tokens[idx] = replacement
            variants.add(" ".join(alias_tokens).strip())

    return {variant for variant in variants if len(variant) >= 2}


def _split_lookup_parts(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[;/(),]+", str(value or "")) if part.strip()]


def _build_case_section_alias_index(case_id: str, db: Session) -> dict[str, set[str]]:
    sections = (
        db.query(Section)
        .filter(Section.document_type.has(case_id=case_id))
        .order_by(Section.path_code.asc(), Section.name.asc())
        .all()
    )
    sections_per_doc_type: dict[str, int] = {}
    for section in sections:
        sections_per_doc_type[section.document_type_id] = sections_per_doc_type.get(section.document_type_id, 0) + 1

    alias_index: dict[str, set[str]] = {}
    for section in sections:
        doc_type = section.document_type
        raw_candidates = {
            section.name or "",
            section.path_code or "",
        }
        for part in _split_lookup_parts(section.name or ""):
            raw_candidates.add(part)
        if doc_type:
            raw_candidates.add(f"{doc_type.name} {section.name}".strip())
            if sections_per_doc_type.get(section.document_type_id, 0) == 1:
                raw_candidates.add(doc_type.name or "")

        aliases: set[str] = set()
        for candidate in raw_candidates:
            aliases.update(_expand_lookup_aliases(candidate))

        for alias in aliases:
            alias_index.setdefault(alias, set()).add(section.id)

    return alias_index


def _spans_overlap(span_a: tuple[int, int], span_b: tuple[int, int]) -> bool:
    return not (span_a[1] <= span_b[0] or span_a[0] >= span_b[1])


def _resolve_auto_link_targets(
    where_to_verify: str,
    alias_index: dict[str, set[str]],
) -> list[str]:
    normalized_text = _normalize_lookup_text(where_to_verify)
    if not normalized_text:
        return []

    matches: list[tuple[int, int, int, str]] = []
    for alias, section_ids in alias_index.items():
        if len(section_ids) != 1 or not alias:
            continue
        pattern = rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])"
        for match in re.finditer(pattern, normalized_text):
            matches.append((len(alias), match.start(), match.end(), next(iter(section_ids))))

    matches.sort(key=lambda item: (item[0], item[2] - item[1]), reverse=True)
    occupied_spans: list[tuple[int, int]] = []
    resolved_section_ids: list[str] = []

    for _, start, end, section_id in matches:
        span = (start, end)
        if any(_spans_overlap(span, occupied) for occupied in occupied_spans):
            continue
        occupied_spans.append(span)
        if section_id not in resolved_section_ids:
            resolved_section_ids.append(section_id)

    return resolved_section_ids


def _auto_link_checklist_questions(cl: QCChecklist, db: Session) -> tuple[int, int]:
    if not cl.case_id:
        return 0, 0

    alias_index = _build_case_section_alias_index(cl.case_id, db)
    if not alias_index:
        return 0, 0

    linked_questions = 0
    resolved_sections = 0
    for question in _ordered_questions_for_checklist(cl):
        if question.target_section_ids or not (question.where_to_verify or "").strip():
            continue
        resolved = _resolve_auto_link_targets(question.where_to_verify, alias_index)
        if not resolved:
            continue
        question.target_section_ids = resolved
        linked_questions += 1
        resolved_sections += len(resolved)

    return linked_questions, resolved_sections


def _infer_form_type_from_text(text: str) -> str:
    normalized_text = _normalize_lookup_text(text)
    if not normalized_text:
        return ""
    if _FORM_I914A_RE.search(normalized_text):
        return "i-914a"
    if _FORM_I914_RE.search(normalized_text):
        return "i-914"
    return ""


def _question_sections(q: QCQuestion, db: Session) -> list[Section]:
    sections_by_id: dict[str, Section] = {}
    for section_id in q.target_section_ids or []:
        section = db.query(Section).filter(Section.id == section_id).first()
        if section:
            sections_by_id[section.id] = section

    for evidence in q.evidence:
        page = db.query(Page).filter(Page.id == evidence.page_id).first()
        if not page:
            continue
        if page.section_id:
            section = db.query(Section).filter(Section.id == page.section_id).first()
            if section:
                sections_by_id[section.id] = section
        for link in page.section_links or []:
            section = getattr(link, "section", None)
            if section:
                sections_by_id[section.id] = section

    return list(sections_by_id.values())


def _infer_form_type_for_question(q: QCQuestion, db: Session) -> str:
    candidate_texts: list[str] = []
    for section in _question_sections(q, db):
        candidate_texts.extend(
            [
                section.name or "",
                section.path_code or "",
                section.document_type.name if section.document_type else "",
            ]
        )

    candidate_texts.extend(
        [
            q.where_to_verify or "",
            q.description or "",
        ]
    )

    checklist = q.part.checklist if q.part else None
    if checklist:
        candidate_texts.extend([checklist.name or "", checklist.description or ""])

    for candidate in candidate_texts:
        if _infer_form_type_from_text(candidate) == "i-914a":
            return "i-914a"
    for candidate in candidate_texts:
        if _infer_form_type_from_text(candidate) == "i-914":
            return "i-914"
    return ""


def _pages_for_target_section(section_id: str, db: Session, *, limit: int) -> list[Page]:
    links = (
        db.query(PageSectionLink)
        .filter(PageSectionLink.section_id == section_id)
        .order_by(PageSectionLink.is_primary.desc(), PageSectionLink.order_in_section.asc())
        .limit(limit)
        .all()
    )
    pages_by_id: dict[str, Page] = {}
    for link in links:
        if link.page and link.page.id not in pages_by_id:
            pages_by_id[link.page.id] = link.page

    if pages_by_id:
        return list(pages_by_id.values())

    return (
        db.query(Page)
        .filter(Page.section_id == section_id)
        .order_by(Page.order_in_section)
        .limit(limit)
        .all()
    )


class QCChecklistQueryRequest(BaseModel):
    question: str
    top_k: int = 3


class QCChecklistQueryMatchOut(BaseModel):
    id: str
    score: float
    metadata: dict


class QCChecklistQueryResponse(BaseModel):
    question: str
    total_matches: int
    matches: list[QCChecklistQueryMatchOut]


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
    _auto_link_checklist_questions(inst, db)

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
    return reorder_entities(db, QCPart, body.items)


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
    return reorder_entities(db, QCQuestion, body.items)


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

STORAGE_DIR = __import__("pathlib").Path(__file__).resolve().parent.parent.parent / "storage"


def _compact_tracker_summary(summary: dict) -> dict[str, int]:
    return {
        "input": int(summary.get("input", 0)),
        "output": int(summary.get("output", 0)),
        "cached": int(summary.get("cached", 0)),
        "thoughts": int(summary.get("thoughts", 0)),
        "embedding": int(summary.get("embedding", 0)),
        "grand_total": int(summary.get("grand_total", 0)),
    }


def _sample_case_pages(case_id: str, db: Session, *, limit: int) -> list[Page]:
    """Return a spread of pages across the whole document instead of just the first N."""
    all_pages = (
        db.query(Page)
        .filter(Page.case_id == case_id, Page.file_path.isnot(None))
        .order_by(Page.original_page_number.asc())
        .all()
    )
    if len(all_pages) <= limit:
        return all_pages
    step = max(1, len(all_pages) // limit)
    return [all_pages[i] for i in range(0, len(all_pages), step)][:limit]


def _part_sort_key(part: QCPart) -> tuple[int, str]:
    return (part.order or 0, part.code or "")


def _question_sort_key(question: QCQuestion) -> tuple[int, str]:
    return (question.order or 0, question.code or "")


def _ordered_questions_for_checklist(cl: QCChecklist) -> list[QCQuestion]:
    all_parts = list(cl.parts)
    by_id = {p.id: p for p in all_parts}
    by_parent: dict[str | None, list[QCPart]] = {}
    for part in all_parts:
        by_parent.setdefault(part.parent_part_id, []).append(part)

    for children in by_parent.values():
        children.sort(key=_part_sort_key)

    ordered_questions: list[QCQuestion] = []
    visited_parts: set[str] = set()

    def _walk(part_id: str):
        part = by_id.get(part_id)
        if not part or part.id in visited_parts:
            return
        visited_parts.add(part.id)
        ordered_questions.extend(sorted(part.questions, key=_question_sort_key))
        for child in by_parent.get(part.id, []):
            _walk(child.id)

    for root in by_parent.get(None, []):
        _walk(root.id)

    # Fallback for orphaned nodes (defensive against malformed trees).
    for orphan in sorted(all_parts, key=_part_sort_key):
        if orphan.id not in visited_parts:
            _walk(orphan.id)

    return ordered_questions


def _ordered_questions_for_part(part: QCPart, all_parts: list[QCPart]) -> list[QCQuestion]:
    by_id = {p.id: p for p in all_parts}
    by_parent: dict[str | None, list[QCPart]] = {}
    for node in all_parts:
        by_parent.setdefault(node.parent_part_id, []).append(node)

    for children in by_parent.values():
        children.sort(key=_part_sort_key)

    ordered_questions: list[QCQuestion] = []
    visited_parts: set[str] = set()

    def _walk(part_id: str):
        node = by_id.get(part_id)
        if not node or node.id in visited_parts:
            return
        visited_parts.add(node.id)
        ordered_questions.extend(sorted(node.questions, key=_question_sort_key))
        for child in by_parent.get(node.id, []):
            _walk(child.id)

    _walk(part.id)
    return ordered_questions


def _collect_question_image_paths(
    q: QCQuestion, db: Session, *, case_id: str | None = None
) -> list[str]:
    import logging
    log = logging.getLogger("qc_autopilot")
    image_paths: list[str] = []

    ev_list = list(q.evidence) if q.evidence else []
    log.debug("    collect_images [%s]: evidence=%d, target_sections=%s",
              q.code, len(ev_list), q.target_section_ids)

    # 1) Explicit evidence links
    for ev in ev_list:
        page = db.query(Page).filter(Page.id == ev.page_id).first()
        if page and page.file_path:
            image_paths.append(str(STORAGE_DIR / page.file_path))

    # 2) Mapped target sections
    if not image_paths and q.target_section_ids:
        for sid in q.target_section_ids:
            sec_pages = _pages_for_target_section(sid, db, limit=3)
            log.debug("    section %s -> %d pages", sid[:8], len(sec_pages))
            for pg in sec_pages:
                if pg.file_path:
                    image_paths.append(str(STORAGE_DIR / pg.file_path))

    # 3) Case-level fallback: sample pages spread across the document
    if not image_paths and case_id:
        case_pages = _sample_case_pages(case_id, db, limit=5)
        log.debug("    case fallback -> %d pages from case", len(case_pages))
        for pg in case_pages:
            image_paths.append(str(STORAGE_DIR / pg.file_path))

    seen: set[str] = set()
    unique_paths: list[str] = []
    for path in image_paths:
        if path in seen:
            continue
        seen.add(path)
        unique_paths.append(path)
    log.debug("    -> %d unique image paths", len(unique_paths))
    return unique_paths


def _collect_question_page_ids(
    q: QCQuestion,
    db: Session,
    *,
    case_id: str | None = None,
    include_case_fallback: bool = True,
) -> list[str]:
    page_ids: list[str] = []

    for ev in q.evidence:
        if ev.page_id:
            page_ids.append(ev.page_id)

    if not page_ids and q.target_section_ids:
        for sid in q.target_section_ids:
            sec_pages = _pages_for_target_section(sid, db, limit=5)
            for pg in sec_pages:
                page_ids.append(pg.id)

    if include_case_fallback and not page_ids and case_id:
        for pg in _sample_case_pages(case_id, db, limit=10):
            page_ids.append(pg.id)

    seen: set[str] = set()
    unique_ids: list[str] = []
    for page_id in page_ids:
        if page_id in seen:
            continue
        seen.add(page_id)
        unique_ids.append(page_id)
    return unique_ids


def _source_page_ids(source_pages: list[dict] | None) -> list[str]:
    seen: set[str] = set()
    ids: list[str] = []
    for item in source_pages or []:
        page_id = str(item.get("page_id", "")).strip()
        if not page_id or page_id in seen:
            continue
        seen.add(page_id)
        ids.append(page_id)
    return ids


def _format_source_pages_for_notes(source_pages: list[dict] | None, *, max_items: int = 8) -> str:
    rows: list[dict] = []
    seen: set[str] = set()
    for item in source_pages or []:
        page_id = str(item.get("page_id", "")).strip()
        if not page_id or page_id in seen:
            continue
        seen.add(page_id)

        page_number_raw = item.get("page_number")
        page_number: int | None = None
        try:
            if page_number_raw is not None:
                parsed = int(page_number_raw)
                page_number = parsed if parsed > 0 else None
        except (TypeError, ValueError):
            page_number = None

        rows.append(
            {
                "page_id": page_id,
                "page_number": page_number,
                "original_filename": str(item.get("original_filename", "") or ""),
            }
        )

    if not rows:
        return ""

    rows.sort(key=lambda r: (r["page_number"] is None, r["page_number"] or 0, r["page_id"]))
    labels: list[str] = []
    for row in rows[:max_items]:
        if row["page_number"] is not None:
            label = f"p.{row['page_number']}"
        else:
            label = f"id:{str(row['page_id'])[:8]}"
        if row["original_filename"]:
            label = f"{label} ({row['original_filename']})"
        labels.append(label)

    extra = len(rows) - max_items
    if extra > 0:
        labels.append(f"+{extra} mas")

    return ", ".join(labels)


def _save_ai_result(q: QCQuestion, result: dict, *, source_pages: list[dict] | None = None) -> None:
    q.ai_answer = result.get("answer", "insufficient")
    explanation = str(result.get("explanation", "") or "").strip()
    source_hint = _format_source_pages_for_notes(source_pages)
    if source_hint:
        q.ai_notes = f"{explanation}\n\nFuentes OCR: {source_hint}" if explanation else f"Fuentes OCR: {source_hint}"
    else:
        q.ai_notes = explanation
    q.ai_confidence = result.get("confidence", "low")
    q.ai_verified_at = datetime.now(timezone.utc)

    # Preserve manual answers if already set by a reviewer.
    if q.answer == QCAnswerStatus.UNANSWERED.value:
        q.answer = q.ai_answer
        q.correction = result.get("correction", "")
        confidence = str(result.get("confidence", "low") or "low")
        prefix = f"[AI {confidence}]".strip()
        note_text = f"{prefix} {explanation}".strip() if explanation else prefix
        if source_hint:
            note_text = f"{note_text}\nFuentes OCR: {source_hint}" if note_text else f"Fuentes OCR: {source_hint}"
        q.notes = note_text


def _verify_question_with_ai(
    q: QCQuestion,
    db: Session,
    *,
    tracker: GeminiTokenTracker | None = None,
) -> str:
    """
    Verify a single question using RAG evidence from Pinecone.
    No images are sent to the model -- only indexed OCR text.
    """
    import logging
    log = logging.getLogger("qc_autopilot")

    from ..services.ai_verify_service import verify_question_rag
    from ..services.checklist_index_service import upsert_qc_question_answer
    from ..services.indexing_service import is_indexing_available
    from ..services.retrieval_service import collect_evidence_bundle_for_question

    checklist = q.part.checklist if q.part else None
    case_id = checklist.case_id if checklist else None
    form_type = _infer_form_type_for_question(q, db)

    text_context = ""
    source_pages: list[dict] = []
    if case_id:
        page_ids = _collect_question_page_ids(
            q,
            db,
            case_id=case_id,
            include_case_fallback=False,
        )
        evidence_bundle = collect_evidence_bundle_for_question(
            q.description,
            case_id=case_id,
            evidence_page_ids=page_ids,
            target_section_ids=q.target_section_ids or [],
            tracker=tracker,
        )
        text_context = str(evidence_bundle.get("text_context", "") or "")
        raw_sources = evidence_bundle.get("source_pages")
        if isinstance(raw_sources, list):
            source_pages = raw_sources
        log.debug("  [%s] RAG evidence: %d chars", q.code, len(text_context))

    if not text_context:
        log.debug("  [%s] no RAG evidence available, skipping", q.code)
        return "skipped"

    result = verify_question_rag(
        q.description, q.where_to_verify or "", text_context,
        form_type=form_type,
        tracker=tracker,
        step_label=f"verify-rag-{q.id[:8]}",
    )

    _save_ai_result(q, result, source_pages=source_pages)

    if checklist and case_id and is_indexing_available():
        try:
            source_page_ids = _source_page_ids(source_pages)
            if not source_page_ids:
                source_page_ids = _collect_question_page_ids(q, db, case_id=case_id)
            upsert_qc_question_answer(
                checklist, q,
                source_page_ids=source_page_ids,
                tracker=tracker,
            )
        except Exception:
            pass

    return "verified"


# ── Batch RAG helpers ─────────────────────────────────────────────────

def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


# Autopilot configuration constants
BATCH_SIZE = max(1, _int_env("QC_AUTOPILOT_BATCH_SIZE", 25))
AUTOPILOT_EVIDENCE_TOP_K = max(1, _int_env("QC_AUTOPILOT_EVIDENCE_TOP_K", 6))
AUTOPILOT_EVIDENCE_MAX_CHARS = max(1200, _int_env("QC_AUTOPILOT_EVIDENCE_MAX_CHARS", 12000))
AUTOPILOT_EVIDENCE_WORKERS = max(1, _int_env("QC_AUTOPILOT_EVIDENCE_WORKERS", 8))
AUTOPILOT_SKIP_PREVERIFIED = _bool_env("QC_AUTOPILOT_SKIP_PREVERIFIED", True)
AUTOPILOT_FORCE_BATCH_ON_NO_EVIDENCE = _bool_env("QC_AUTOPILOT_FORCE_BATCH_ON_NO_EVIDENCE", True)
AUTOPILOT_INDEX_ANSWERS = _bool_env("QC_AUTOPILOT_INDEX_ANSWERS", False)


def _is_question_preverified(q: QCQuestion) -> bool:
    if not AUTOPILOT_SKIP_PREVERIFIED:
        return False
    if not q.ai_verified_at:
        return False
    return str(q.ai_answer or "").strip().lower() in {"yes", "no", "na", "insufficient"}


def _group_questions_for_autopilot_batches(
    questions: list[QCQuestion],
    db: Session,
    *,
    form_type_cache: Any | None = None,
    case_id: str = "",
    source_doc_ids_by_page: dict[str, str] | None = None,
) -> list[tuple[str, list[QCQuestion]]]:
    batches: list[tuple[str, list[QCQuestion]]] = []
    current_form_type = ""
    current_batch: list[QCQuestion] = []

    for question in questions:
        form_type = ""
        if form_type_cache and source_doc_ids_by_page:
            ev_doc_ids = set()
            for ev in question.evidence:
                sdid = source_doc_ids_by_page.get(str(ev.page_id or ""))
                if sdid:
                    ev_doc_ids.add(sdid)
            for sdid in ev_doc_ids:
                detected = form_type_cache.get_or_detect(sdid, case_id)
                if detected:
                    form_type = detected
                    break
        if not form_type:
            form_type = _infer_form_type_for_question(question, db)

        if current_batch and (len(current_batch) >= BATCH_SIZE or form_type != current_form_type):
            batches.append((current_form_type, current_batch))
            current_batch = []
        if not current_batch:
            current_form_type = form_type
        current_batch.append(question)

    if current_batch:
        batches.append((current_form_type, current_batch))

    return batches


def _run_batch_llm_phase(
    questions: list[QCQuestion],
    evidence_map: dict[str, Any],
    *,
    form_type: str = "",
    tracker: GeminiTokenTracker | None = None,
) -> list[dict] | None:
    """LLM-only phase: build payload, call Gemini, return normalized answers.
    Returns None on failure."""
    import logging
    log = logging.getLogger("qc_autopilot")
    from ..services.ai_verify_service import verify_question_batch_rag

    batch_input = [
        {
            "id": _question_internal_key(q),
            "description": q.description,
            "where_to_verify": q.where_to_verify or "",
        }
        for q in questions
    ]

    batch_evidence: dict[str, Any] = {}
    for q in questions:
        qid = _question_internal_key(q)
        batch_evidence[qid] = evidence_map.get(qid, "")

    try:
        answers = verify_question_batch_rag(
            batch_input,
            batch_evidence,
            form_type=form_type,
            tracker=tracker,
            step_label=f"autopilot-batch-{questions[0].id[:8]}",
        )
        return answers
    except Exception as exc:
        log.error("  Batch RAG call failed: %s", exc)
        return None


def _run_batch_persist_phase(
    questions: list[QCQuestion],
    answers: list[dict],
    evidence_source_map: dict[str, list[dict]],
    db: Session,
    checklist: QCChecklist,
    *,
    tracker: GeminiTokenTracker | None = None,
) -> tuple[int, int, int]:
    """Persistence phase: save answers to DB and optionally index them.
    Returns (verified, skipped, errors)."""
    import logging
    log = logging.getLogger("qc_autopilot")
    from ..services.checklist_index_service import upsert_qc_question_answers
    from ..services.indexing_service import is_indexing_available
    should_index_answers = AUTOPILOT_INDEX_ANSWERS and bool(checklist.case_id) and is_indexing_available()

    verified = 0
    errors_count = 0
    answers_to_index: list[tuple[QCQuestion, list[str]]] = []
    for q, ans in zip(questions, answers):
        qid = _question_internal_key(q)
        source_pages = evidence_source_map.get(qid, [])
        try:
            _save_ai_result(q, ans, source_pages=source_pages)
            verified += 1
            log.info("  [%s] -> %s (confidence=%s)", q.code, ans.get("answer"), ans.get("confidence"))

            if should_index_answers and checklist.case_id:
                source_page_ids = _source_page_ids(source_pages)
                if not source_page_ids:
                    source_page_ids = _collect_question_page_ids(q, db, case_id=checklist.case_id)
                answers_to_index.append((q, source_page_ids))
        except Exception as exc:
            errors_count += 1
            log.error("  [%s] save failed: %s", q.code, exc)

    if verified > 0:
        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            log.error("  Batch DB commit failed: %s", exc)
            return 0, 0, len(questions)

    if should_index_answers and answers_to_index:
        try:
            upsert_qc_question_answers(
                checklist,
                answers_to_index,
                tracker=tracker,
            )
        except Exception:
            pass

    return verified, 0, errors_count


def _run_autopilot_batch_rag(
    questions: list[QCQuestion],
    evidence_map: dict[str, Any],
    evidence_source_map: dict[str, list[dict]],
    db: Session,
    checklist: QCChecklist,
    *,
    form_type: str = "",
    tracker: GeminiTokenTracker | None = None,
) -> tuple[int, int, int]:
    """Process a batch: LLM call then persist results. Returns (verified, skipped, errors)."""
    answers = _run_batch_llm_phase(
        questions, evidence_map,
        form_type=form_type, tracker=tracker,
    )
    if answers is None:
        return 0, 0, len(questions)
    return _run_batch_persist_phase(
        questions, answers, evidence_source_map, db, checklist,
        tracker=tracker,
    )


# ── Autopilot job runner ──────────────────────────────────────────────

def _ensure_case_ocr_for_autopilot(case_id: str, db: Session) -> dict[str, int]:
    """
    Ensure OCR exists for all pages in the case before AI verification starts.
    Pages that are already extracted are skipped.
    """
    from ..services.indexing_service import process_page_extraction

    pages = (
        db.query(Page)
        .filter(Page.case_id == case_id)
        .order_by(Page.created_at.asc())
        .all()
    )

    total_pages = len(pages)
    extracted_pages = 0
    skipped_pages = 0
    error_pages = 0

    for page in pages:
        if not page.file_path:
            skipped_pages += 1
            continue

        has_existing_text = bool((page.ocr_text or "").strip())
        if page.extraction_status == ExtractionStatus.DONE.value and has_existing_text:
            skipped_pages += 1
            continue

        has_tables = bool(page.document_type.has_tables) if page.document_type else False
        process_page_extraction(page.id, has_tables)

        db.expire_all()
        refreshed = db.query(Page).filter(Page.id == page.id).first()
        if refreshed and refreshed.extraction_status == ExtractionStatus.DONE.value and (refreshed.ocr_text or "").strip():
            extracted_pages += 1
        else:
            error_pages += 1

    return {
        "total_pages": total_pages,
        "extracted_pages": extracted_pages,
        "skipped_pages": skipped_pages,
        "error_pages": error_pages,
    }


def _run_ai_autopilot_job(job_id: str, checklist_id: str) -> None:
    import logging
    log = logging.getLogger("qc_autopilot")
    db = SessionLocal()
    tracker = create_token_tracker(label=f"qc-autopilot-{job_id[:8]}")
    try:
        qc_autopilot_jobs.mark_running(job_id, phase="loading_questions")
        checklist = db.query(QCChecklist).filter(QCChecklist.id == checklist_id).first()
        if not checklist:
            qc_autopilot_jobs.mark_failed(job_id, "QC Checklist not found")
            return

        case_id = checklist.case_id
        ocr_stats = {
            "total_pages": 0,
            "extracted_pages": 0,
            "skipped_pages": 0,
            "error_pages": 0,
        }

        qc_autopilot_jobs.mark_running(job_id, phase="loading_questions")
        all_questions = _ordered_questions_for_checklist(checklist)
        questions = [q for q in all_questions if not _is_question_preverified(q)]
        preverified_skipped = max(0, len(all_questions) - len(questions))
        log.info(
            "Autopilot %s: total=%d pending=%d preverified=%d case=%s",
            job_id[:8],
            len(all_questions),
            len(questions),
            preverified_skipped,
            (case_id or "?")[:8],
        )
        qc_autopilot_jobs.set_total_questions(job_id, len(all_questions))
        qc_autopilot_jobs.set_evidence_total(job_id, len(questions))

        phase_summaries: dict[str, dict] = {}
        total_case_pages = 0

        if case_id:
            from ..services.case_extraction_service import extract_case_pages
            from ..services.ocr_index_service import index_case_ocr_json
            from ..services.indexing_service import is_indexing_available

            def _autopilot_progress(event: dict[str, int | str]) -> None:
                phase = str(event.get("phase", "") or "")
                if phase == "extracting_document":
                    qc_autopilot_jobs.set_ocr_total(job_id, int(event.get("ocr_total_pages", 0) or 0), phase=phase)
                    qc_autopilot_jobs.update_ocr_progress(
                        job_id,
                        processed_pages=int(event.get("ocr_processed_pages", 0) or 0),
                        error_pages=int(event.get("ocr_error_pages", 0) or 0),
                        phase=phase,
                    )
                elif phase == "writing_json":
                    qc_autopilot_jobs.mark_running(job_id, phase=phase)
                elif phase == "indexing_document":
                    qc_autopilot_jobs.set_index_total(job_id, int(event.get("index_total_chunks", 0) or 0), phase=phase)
                    qc_autopilot_jobs.update_index_progress(
                        job_id,
                        processed_chunks=int(event.get("index_processed_chunks", 0) or 0),
                        error_chunks=int(event.get("index_error_chunks", 0) or 0),
                        phase=phase,
                    )

            # debug instrumentation removed

            qc_autopilot_jobs.mark_running(job_id, phase="extracting_ocr")
            extraction_summary = extract_case_pages(
                case_id,
                only_missing=True,
                progress_callback=_autopilot_progress,
            )
            total_case_pages = extraction_summary.get("total_case_pages", extraction_summary.get("written_pages", 0))
            extracted_success = max(
                0,
                int(extraction_summary.get("processed", 0) or 0)
                - int(extraction_summary.get("errors", 0) or 0),
            )
            ocr_stats = {
                "total_pages": int(total_case_pages or 0),
                "extracted_pages": extracted_success,
                "skipped_pages": int(extraction_summary.get("already_done", 0) or 0),
                "error_pages": int(extraction_summary.get("errors", 0) or 0),
            }
            log.info(
                "Autopilot %s OCR done: %d extracted, %d already done, %d total pages, %d errors",
                job_id[:8],
                extracted_success,
                extraction_summary.get("already_done", 0),
                total_case_pages,
                extraction_summary.get("errors", 0),
            )
            phase_summaries["ocr"] = {
                "token_summary": extraction_summary.get("ocr_token_summary", {}),
                "pages_extracted": extracted_success,
                "pages_already_done": extraction_summary.get("already_done", 0),
                "pages_total": total_case_pages,
            }

            if extracted_success > 0 and is_indexing_available():
                index_tracker = create_token_tracker(label=f"qc-index-{job_id[:8]}")
                index_summary = index_case_ocr_json(
                    case_id,
                    tracker=index_tracker,
                    progress_callback=_autopilot_progress,
                )
                log.info(
                    "Autopilot %s indexing done: %d vectors, %d chunks",
                    job_id[:8],
                    index_summary.get("vectors_count", 0),
                    index_summary.get("total_chunks", 0),
                )
                phase_summaries["indexing"] = {
                    "token_summary": _compact_tracker_summary(index_tracker.get_summary()),
                    "vectors_count": index_summary.get("vectors_count", 0),
                    "total_chunks": index_summary.get("total_chunks", 0),
                }

        # 1) Gather per-question evidence (like OCRDocPinecone collectEvidence)
        qc_autopilot_jobs.mark_running(job_id, phase="gathering_evidence")
        from ..services.embedding_service import get_embedding_batch
        from ..services.rag_config import get_rag_settings
        from ..services.retrieval_service import collect_evidence_bundle_for_question

        evidence_map: dict[str, Any] = {}
        evidence_source_map: dict[str, list[dict]] = {}
        question_query_vectors: dict[str, list[float]] = {}
        source_doc_ids_by_page: dict[str, str] = {}
        has_any_evidence = False
        if case_id:
            try:
                question_ids: list[str] = []
                question_texts: list[str] = []
                for q in questions:
                    text = str(q.description or "").strip()
                    if not text:
                        continue
                    question_ids.append(_question_internal_key(q))
                    question_texts.append(text)
                if question_texts:
                    query_embeddings = get_embedding_batch(
                        question_texts,
                        task_type=get_rag_settings().embedding_task_type_query,
                        tracker=tracker,
                        step_label=f"autopilot-evidence-embeddings-{job_id[:8]}",
                    )
                    for qid, vector in zip(question_ids, query_embeddings, strict=False):
                        if vector:
                            question_query_vectors[qid] = vector
            except Exception as exc:
                log.warning("Autopilot %s query embedding batch fallback: %s", job_id[:8], exc)

            all_page_ids_for_docs: set[str] = set()
            question_targets: list[tuple[QCQuestion, str, list[str]]] = []
            for q in questions:
                qid = _question_internal_key(q)
                page_ids = _collect_question_page_ids(
                    q,
                    db,
                    case_id=case_id,
                    include_case_fallback=True,
                )
                question_targets.append((q, qid, page_ids))
                all_page_ids_for_docs.update(page_ids)

            if all_page_ids_for_docs:
                page_id_list = list(all_page_ids_for_docs)
                doc_pages = (
                    db.query(Page.id, Page.source_document_id)
                    .filter(Page.id.in_(page_id_list), Page.source_document_id.isnot(None))
                    .all()
                )
                for pid, sdid in doc_pages:
                    source_doc_ids_by_page[str(pid)] = str(sdid)

            from threading import Lock as _EvidenceLock
            _ev_lock = _EvidenceLock()
            _ev_done = [0]

            def _collect_single(target: tuple[QCQuestion, str, list[str]]) -> None:
                question, qid, page_ids = target
                try:
                    q_source_doc_ids = list({
                        source_doc_ids_by_page[pid]
                        for pid in page_ids
                        if pid in source_doc_ids_by_page
                    }) or None

                    evidence_bundle = collect_evidence_bundle_for_question(
                        question.description,
                        case_id=case_id,
                        evidence_page_ids=page_ids,
                        target_section_ids=question.target_section_ids or [],
                        source_document_ids=q_source_doc_ids,
                        top_k=AUTOPILOT_EVIDENCE_TOP_K,
                        query_vector=question_query_vectors.get(qid),
                        max_context_chars=AUTOPILOT_EVIDENCE_MAX_CHARS,
                        tracker=None,
                    )
                    structured = evidence_bundle.get("evidence", [])
                    text_fallback = str(evidence_bundle.get("text_context", "") or "")
                    raw_sources = evidence_bundle.get("source_pages")
                    with _ev_lock:
                        evidence_map[qid] = structured if structured else text_fallback
                        evidence_source_map[qid] = raw_sources if isinstance(raw_sources, list) else []
                        if structured or text_fallback.strip():
                            nonlocal has_any_evidence
                            has_any_evidence = True
                        _ev_done[0] += 1
                        local_done = _ev_done[0]
                    qc_autopilot_jobs.update_evidence_progress(
                        job_id,
                        processed_questions=local_done,
                        phase="gathering_evidence",
                    )
                    if local_done % 20 == 0 or local_done == len(question_targets):
                        log.info("  Evidence collected: %d/%d questions", local_done, len(question_targets))
                except Exception as exc:
                    log.warning("  Evidence collection failed for %s: %s", qid[:8], exc)

            with ThreadPoolExecutor(max_workers=AUTOPILOT_EVIDENCE_WORKERS) as ev_pool:
                ev_futures = [ev_pool.submit(_collect_single, target) for target in question_targets]
                for future in as_completed(ev_futures):
                    future.result()

        # debug instrumentation removed
        log.info("  Evidence collection done: %d questions, has_evidence=%s",
                 len(evidence_map), has_any_evidence)

        qc_autopilot_jobs.mark_running(job_id, phase="verifying_questions")

        verified = 0
        skipped = preverified_skipped
        errors = 0
        if preverified_skipped > 0:
            qc_autopilot_jobs.update_progress(
                job_id,
                processed_delta=preverified_skipped,
                skipped_delta=preverified_skipped,
                phase="verifying_questions",
            )

        from ..services.form_detection_service import FormTypeCache
        form_type_cache = FormTypeCache()

        if not questions:
            log.info("  No pending questions to verify (preverified=%d)", preverified_skipped)
        elif has_any_evidence or AUTOPILOT_FORCE_BATCH_ON_NO_EVIDENCE:
            if not has_any_evidence:
                log.info("  No evidence found; forcing batch RAG mode with empty evidence")
            grouped_batches = _group_questions_for_autopilot_batches(
                questions, db,
                form_type_cache=form_type_cache,
                case_id=case_id or "",
                source_doc_ids_by_page=source_doc_ids_by_page,
            )

            from ..services.rag_config import get_rag_settings as _get_rs
            llm_concurrency = _get_rs().autopilot_llm_batch_concurrency

            llm_results: list[tuple[int, str, list[QCQuestion], list[dict] | None]] = []

            def _llm_worker(batch_idx: int, form_t: str, batch: list[QCQuestion]) -> tuple[int, str, list[QCQuestion], list[dict] | None]:
                return (
                    batch_idx,
                    form_t,
                    batch,
                    _run_batch_llm_phase(batch, evidence_map, form_type=form_t, tracker=tracker),
                )

            log.info("  LLM phase: %d batches, concurrency=%d", len(grouped_batches), llm_concurrency)
            with ThreadPoolExecutor(max_workers=llm_concurrency) as llm_pool:
                llm_futures = [
                    llm_pool.submit(_llm_worker, idx, ft, bt)
                    for idx, (ft, bt) in enumerate(grouped_batches)
                ]
                for future in as_completed(llm_futures):
                    try:
                        llm_results.append(future.result())
                    except Exception as exc:
                        log.error("  LLM batch future failed: %s", exc)

            llm_results.sort(key=lambda r: r[0])

            processed_offset = 0
            for batch_idx, batch_form_type, batch, answers in llm_results:
                batch_start = processed_offset + 1
                batch_end = processed_offset + len(batch)
                processed_offset += len(batch)
                log.info(
                    "  Persist batch %d-%d (%d questions, form_type=%s)",
                    batch_start,
                    batch_end,
                    len(batch),
                    batch_form_type or "default",
                )
                bv, bs, be = 0, 0, 0
                if answers is None:
                    be = len(batch)
                    errors += be
                else:
                    try:
                        bv, bs, be = _run_batch_persist_phase(
                            batch,
                            answers,
                            evidence_source_map,
                            db,
                            checklist,
                            tracker=tracker,
                        )
                        verified += bv
                        skipped += bs
                        errors += be
                    except Exception as exc:
                        db.rollback()
                        be = len(batch)
                        errors += be
                        log.error("  Batch persist failed: %s", exc)

                qc_autopilot_jobs.update_progress(
                    job_id,
                    processed_delta=len(batch),
                    verified_delta=bv,
                    skipped_delta=bs,
                    errors_delta=be,
                    phase="verifying_questions",
                )
        else:
            log.info("  No evidence found; using per-question fallback mode")
            for q in questions:
                q_status = "skipped"
                try:
                    q_status = _verify_question_with_ai(q, db, tracker=tracker)
                    if q_status == "verified":
                        db.commit()
                        verified += 1
                    else:
                        skipped += 1
                except Exception as exc:
                    db.rollback()
                    errors += 1
                    q_status = "error"
                    log.error("  [%s] error: %s", q.code, exc)

                qc_autopilot_jobs.update_progress(
                    job_id,
                    processed_delta=1,
                    verified_delta=1 if q_status == "verified" else 0,
                    skipped_delta=1 if q_status == "skipped" else 0,
                    errors_delta=1 if q_status == "error" else 0,
                    phase="verifying_questions",
                )

        # debug instrumentation removed
        log.info("Autopilot %s done: verified=%d, skipped=%d, errors=%d",
                 job_id[:8], verified, skipped, errors)
        log_token_summary(tracker, label=f"AI Autopilot {job_id[:8]}", logger=log)

        if case_id:
            try:
                tracker_summary = tracker.get_summary()
                from ..services.json_export_service import save_final_token_summary

                phase_summaries["autopilot"] = {
                    "token_summary": _compact_tracker_summary(tracker_summary),
                    "verified": verified,
                    "skipped": skipped,
                    "errors": errors,
                    "total_questions": len(all_questions),
                }
                save_final_token_summary(
                    case_id,
                    phases=phase_summaries,
                    total_pages=total_case_pages,
                )
                # debug instrumentation removed
                db.add(
                    AuditLog(
                        case_id=case_id,
                        action="qc_autopilot_completed",
                        entity_type="qc_checklist",
                        entity_id=checklist.id,
                        details={
                            "job_id": job_id,
                            "verified": verified,
                            "skipped": skipped,
                            "errors": errors,
                            "total_questions": len(all_questions),
                            "ocr_total_pages": ocr_stats["total_pages"],
                            "ocr_extracted_pages": ocr_stats["extracted_pages"],
                            "ocr_skipped_pages": ocr_stats["skipped_pages"],
                            "ocr_error_pages": ocr_stats["error_pages"],
                            "token_summary": _compact_tracker_summary(tracker_summary),
                        },
                    )
                )
                db.commit()
            except Exception:
                db.rollback()

        qc_autopilot_jobs.mark_completed(job_id, phase="completed")
    except Exception as exc:
        db.rollback()
        qc_autopilot_jobs.mark_failed(job_id, str(exc))
    finally:
        db.close()


@router.post("/qc-checklists/{cl_id}/ai-autopilot", response_model=QCAutopilotJobOut, status_code=202)
def start_checklist_ai_autopilot(
    cl_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Start async AI Autopilot for all questions in a checklist."""
    from ..services.extraction_service import is_configured as gemini_ok

    if not gemini_ok():
        raise HTTPException(503, "GEMINI_API_KEY not configured")

    cl = db.query(QCChecklist).filter(QCChecklist.id == cl_id).first()
    if not cl:
        raise HTTPException(404, "QC Checklist not found")
    if cl.is_template or not cl.case_id:
        raise HTTPException(400, "AI Autopilot is only available for case-bound checklists")

    case_pages = db.query(Page).filter(Page.case_id == cl.case_id).all()
    if not case_pages:
        raise HTTPException(400, "No hay paginas cargadas en este caso")

    active_job = qc_autopilot_jobs.get_active_job_for_checklist(cl.id)
    if active_job:
        return QCAutopilotJobOut(**active_job)

    job_data = qc_autopilot_jobs.create_job(
        checklist_id=cl.id,
        case_id=cl.case_id,
        total_questions=len(_ordered_questions_for_checklist(cl)),
    )
    background_tasks.add_task(_run_ai_autopilot_job, job_data["id"], cl.id)
    return QCAutopilotJobOut(**job_data)


@router.get("/qc-autopilot-jobs/{job_id}", response_model=QCAutopilotJobOut)
def get_checklist_ai_autopilot_job(job_id: str):
    """Get current status/progress for an AI Autopilot job."""
    job_data = qc_autopilot_jobs.get_job(job_id)
    if not job_data:
        raise HTTPException(404, "AI Autopilot job not found")
    return QCAutopilotJobOut(**job_data)


@router.post("/qc-questions/{q_id}/ai-verify", response_model=QCQuestionOut)
def ai_verify_question(q_id: str, db: Session = Depends(get_db)):
    """Use RAG evidence from Pinecone to automatically verify a QC question."""
    from ..services.extraction_service import is_configured as gemini_ok
    if not gemini_ok():
        raise HTTPException(503, "GEMINI_API_KEY not configured")

    q = db.query(QCQuestion).filter(QCQuestion.id == q_id).first()
    if not q:
        raise HTTPException(404, "Question not found")

    tracker = create_token_tracker(label=f"qc-question-{q.id[:8]}")
    status = _verify_question_with_ai(q, db, tracker=tracker)
    if status == "skipped":
        raise HTTPException(400, "No evidence pages or target section pages available for this question")

    db.commit()
    db.refresh(q)
    log_token_summary(tracker, label=f"QC Question {q.code or q.id}")
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
    tracker = create_token_tracker(label=f"qc-part-{part_id[:8]}")

    all_parts = db.query(QCPart).filter(QCPart.checklist_id == part.checklist_id).all()
    questions = _ordered_questions_for_part(part, all_parts)
    for q in questions:
        try:
            status = _verify_question_with_ai(q, db, tracker=tracker)
            if status == "verified":
                verified += 1
                db.commit()
            else:
                skipped += 1
        except Exception:
            db.rollback()
            errors += 1

    db.commit()
    log_token_summary(tracker, label=f"QC Part {part.code or part.id}")

    return {"verified": verified, "skipped": skipped, "errors": errors}


@router.post("/qc-checklists/{cl_id}/semantic-query", response_model=QCChecklistQueryResponse)
def semantic_query_checklist(cl_id: str, body: QCChecklistQueryRequest, db: Session = Depends(get_db)):
    """Query indexed checklist answers for a case-bound checklist."""
    from ..services.indexing_service import is_indexing_available
    from ..services.retrieval_service import query_checklist_rag

    checklist = db.query(QCChecklist).filter(QCChecklist.id == cl_id).first()
    if not checklist:
        raise HTTPException(404, "QC Checklist not found")
    if not checklist.case_id:
        raise HTTPException(400, "Semantic query is only available for case-bound checklists")
    if not is_indexing_available():
        raise HTTPException(503, "Pinecone indexing is not configured")

    matches = query_checklist_rag(
        body.question,
        case_id=checklist.case_id,
        checklist_id=checklist.id,
        top_k=body.top_k,
    )
    return QCChecklistQueryResponse(
        question=body.question,
        total_matches=len(matches),
        matches=[QCChecklistQueryMatchOut(**match) for match in matches],
    )


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
    linked_questions, resolved_sections = _auto_link_checklist_questions(cl, db)

    db.add(AuditLog(case_id=case_id, action="applied_link_preset", entity_type="qc_link_preset",
                    entity_id=preset.id, details={
                        "preset_name": preset.name,
                        "checklist_id": cl.id,
                        "auto_linked_questions": linked_questions,
                        "auto_linked_sections": resolved_sections,
                    }))
    db.commit()
    db.refresh(cl)
    return _checklist_out(cl)


@router.post("/cases/{case_id}/qc-checklists/{cl_id}/auto-link-sections", response_model=QCChecklistOut)
def auto_link_checklist_sections(case_id: str, cl_id: str, db: Session = Depends(get_db)):
    """Auto-link unresolved QC questions from where_to_verify against this case's taxonomy."""
    cl = db.query(QCChecklist).filter(QCChecklist.id == cl_id, QCChecklist.case_id == case_id).first()
    if not cl:
        raise HTTPException(404, "QC Checklist not found in this case")
    if cl.is_template:
        raise HTTPException(400, "Auto-link is only available for case-bound checklists")

    linked_questions, resolved_sections = _auto_link_checklist_questions(cl, db)
    db.add(
        AuditLog(
            case_id=case_id,
            action="auto_linked_qc_sections",
            entity_type="qc_checklist",
            entity_id=cl.id,
            details={
                "linked_questions": linked_questions,
                "resolved_sections": resolved_sections,
            },
        )
    )
    db.commit()
    db.refresh(cl)
    return _checklist_out(cl)

