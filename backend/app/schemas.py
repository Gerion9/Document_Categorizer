"""
Pydantic schemas for request / response validation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── Case ──────────────────────────────────────────────────────────────────

class CaseCreate(BaseModel):
    name: str
    description: str = ""

class CaseUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None

class CaseOut(BaseModel):
    id: str
    name: str
    description: str
    created_at: datetime
    updated_at: datetime
    page_count: int = 0
    classified_count: int = 0
    checklist_count: int = 0

    class Config:
        from_attributes = True


# ── DocumentType ──────────────────────────────────────────────────────────

class DocumentTypeCreate(BaseModel):
    name: str
    code: str
    order: int = 0
    has_tables: bool = False

class DocumentTypeUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    order: Optional[int] = None
    has_tables: Optional[bool] = None

class SectionOut(BaseModel):
    id: str
    document_type_id: str
    parent_section_id: Optional[str] = None
    name: str
    code: str
    path_code: str = ""
    depth: int = 0
    order: int
    is_required: bool
    page_count: int = 0
    children: list[SectionOut] = []

    class Config:
        from_attributes = True

class DocumentTypeOut(BaseModel):
    id: str
    case_id: str
    name: str
    code: str
    order: int
    has_tables: bool = False
    created_at: datetime
    sections: list[SectionOut] = []

    class Config:
        from_attributes = True


# ── Section ───────────────────────────────────────────────────────────────

class SectionCreate(BaseModel):
    name: str
    code: str
    order: int = 0
    is_required: bool = True
    parent_section_id: Optional[str] = None

class SectionUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    order: Optional[int] = None
    is_required: Optional[bool] = None
    parent_section_id: Optional[str] = None


# ── Page ──────────────────────────────────────────────────────────────────

class PageOut(BaseModel):
    id: str
    case_id: str
    original_filename: str
    original_page_number: int
    thumbnail_path: str
    file_path: str
    document_type_id: Optional[str] = None
    section_id: Optional[str] = None
    subindex: Optional[str] = None
    order_in_section: Optional[int] = None
    status: str
    metadata_json: dict = {}
    ocr_text: Optional[str] = None
    extraction_status: str = "pending"
    extraction_method: Optional[str] = None
    index_status: str = "pending"
    index_method: Optional[str] = None
    indexed_at: Optional[datetime] = None
    indexed_vector_count: int = 0
    pinecone_document_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    # Multi-section links
    section_links: list[PageSectionLinkOut] = []
    link_count: int = 0

    class Config:
        from_attributes = True

class PageClassify(BaseModel):
    document_type_id: str
    section_id: str
    order_in_section: Optional[int] = None

class PageReorder(BaseModel):
    page_id: str
    order_in_section: int

class PagesReorderBatch(BaseModel):
    section_id: str
    pages: list[PageReorder]

# ── Page Section Links (multi-section) ────────────────────────────────────

class PageSectionLinkOut(BaseModel):
    id: str
    page_id: str
    section_id: str
    is_primary: bool
    order_in_section: int
    created_at: datetime
    section_path_code: str = ""
    section_name: str = ""
    document_type_code: str = ""
    document_type_name: str = ""

    class Config:
        from_attributes = True

class PageSectionLinkCreate(BaseModel):
    section_id: str
    is_primary: bool = False

class PageSetPrimary(BaseModel):
    section_id: str


# ── Checklist ─────────────────────────────────────────────────────────────

class ChecklistCreate(BaseModel):
    name: str

class ChecklistItemCreate(BaseModel):
    description: str
    order: int = 0
    target_section_ids: list[str] = []

class ChecklistItemUpdate(BaseModel):
    description: Optional[str] = None
    status: Optional[str] = None
    order: Optional[int] = None
    notes: Optional[str] = None
    target_section_ids: Optional[list[str]] = None

class EvidenceLinkCreate(BaseModel):
    page_id: str
    notes: str = ""

class EvidenceLinkOut(BaseModel):
    id: str
    checklist_item_id: str
    page_id: str
    notes: str
    created_at: datetime
    page: Optional[PageOut] = None

    class Config:
        from_attributes = True

class SectionTargetOut(BaseModel):
    id: str
    section_id: str
    section_path_code: str = ""
    section_name: str = ""

    class Config:
        from_attributes = True

class ChecklistItemOut(BaseModel):
    id: str
    checklist_id: str
    description: str
    status: str
    order: int
    notes: str
    evidence_links: list[EvidenceLinkOut] = []
    target_sections: list[SectionTargetOut] = []

    class Config:
        from_attributes = True

class ChecklistOut(BaseModel):
    id: str
    case_id: str
    name: str
    created_at: datetime
    items: list[ChecklistItemOut] = []
    completion_pct: float = 0.0

    class Config:
        from_attributes = True


# ── AuditLog ──────────────────────────────────────────────────────────────

class AuditLogOut(BaseModel):
    id: str
    case_id: str
    action: str
    entity_type: str
    entity_id: Optional[str] = None
    details: dict = {}
    user: str
    created_at: datetime

    class Config:
        from_attributes = True


# ── QC Checklist (complex hierarchical) ───────────────────────────────────

class QCQuestionEvidenceOut(BaseModel):
    id: str
    question_id: str
    page_id: str
    notes: str
    created_at: datetime
    class Config:
        from_attributes = True

class QCQuestionCreate(BaseModel):
    code: str
    description: str
    where_to_verify: str = ""
    order: int = 0

class QCQuestionUpdate(BaseModel):
    code: Optional[str] = None
    description: Optional[str] = None
    where_to_verify: Optional[str] = None
    order: Optional[int] = None
    answer: Optional[str] = None
    correction: Optional[str] = None
    notes: Optional[str] = None
    target_section_ids: Optional[list[str]] = None

class QCQuestionOut(BaseModel):
    id: str
    part_id: str
    code: str
    description: str
    where_to_verify: str
    order: int
    answer: str = "unanswered"
    correction: str = ""
    notes: str = ""
    answered_by: Optional[str] = None
    answered_at: Optional[datetime] = None
    ai_answer: Optional[str] = None
    ai_notes: str = ""
    ai_confidence: Optional[str] = None
    ai_verified_at: Optional[datetime] = None
    target_section_ids: list[str] = []
    evidence: list[QCQuestionEvidenceOut] = []
    class Config:
        from_attributes = True

class QCPartCreate(BaseModel):
    name: str
    code: str
    order: int = 0
    parent_part_id: Optional[str] = None

class QCPartUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    order: Optional[int] = None

class QCPartOut(BaseModel):
    id: str
    checklist_id: str
    parent_part_id: Optional[str] = None
    name: str
    code: str
    order: int
    depth: int = 0
    questions: list[QCQuestionOut] = []
    children: list[QCPartOut] = []
    class Config:
        from_attributes = True

class QCChecklistCreate(BaseModel):
    name: str
    description: str = ""
    is_template: bool = False

class QCChecklistOut(BaseModel):
    id: str
    name: str
    description: str
    case_id: Optional[str] = None
    is_template: bool = False
    source_template_id: Optional[str] = None
    created_at: datetime
    parts: list[QCPartOut] = []
    total_questions: int = 0
    answered_questions: int = 0
    class Config:
        from_attributes = True

class QCEvidenceCreate(BaseModel):
    page_id: str
    notes: str = ""


# ── Section target upsert ─────────────────────────────────────────────────

class ItemTargetsUpsert(BaseModel):
    target_section_ids: list[str]


# ── Template schemas ─────────────────────────────────────────────────────

class TemplateNodeCreate(BaseModel):
    name: str
    code: str
    node_type: str = "section"   # "doc_type" | "section"
    has_tables: bool = False
    is_required: bool = True
    parent_node_id: Optional[str] = None
    order: int = 0

class TemplateNodeOut(BaseModel):
    id: str
    template_id: str
    parent_node_id: Optional[str] = None
    name: str
    code: str
    node_type: str
    has_tables: bool
    is_required: bool
    depth: int
    order: int
    children: list[TemplateNodeOut] = []
    target_item_ids: list[str] = []

    class Config:
        from_attributes = True

class TemplateChecklistItemCreate(BaseModel):
    description: str
    order: int = 0
    target_node_ids: list[str] = []

class TemplateChecklistItemOut(BaseModel):
    id: str
    description: str
    order: int
    target_node_ids: list[str] = []

    class Config:
        from_attributes = True

class TemplateChecklistCreate(BaseModel):
    name: str
    items: list[TemplateChecklistItemCreate] = []

class TemplateChecklistOut(BaseModel):
    id: str
    name: str
    items: list[TemplateChecklistItemOut] = []

    class Config:
        from_attributes = True

class TemplateCreate(BaseModel):
    name: str
    description: str = ""

class TemplateOut(BaseModel):
    id: str
    name: str
    description: str
    created_at: datetime
    nodes: list[TemplateNodeOut] = []
    checklists: list[TemplateChecklistOut] = []

    class Config:
        from_attributes = True

class ApplyTemplateRequest(BaseModel):
    template_id: str


# ── QC Link Presets ───────────────────────────────────────────────────────

class QCLinkPresetMappingOut(BaseModel):
    id: str
    question_code: str
    section_path_codes: list[str] = []

    class Config:
        from_attributes = True

class QCLinkPresetOut(BaseModel):
    id: str
    name: str
    qc_template_id: Optional[str] = None
    doc_template_id: Optional[str] = None
    created_at: datetime
    mappings: list[QCLinkPresetMappingOut] = []
    mapping_count: int = 0

    class Config:
        from_attributes = True

class QCLinkPresetCreate(BaseModel):
    name: str = ""
    doc_template_id: Optional[str] = None


# ── QC AI Autopilot ────────────────────────────────────────────────────────

class QCAutopilotJobOut(BaseModel):
    id: str
    checklist_id: str
    case_id: Optional[str] = None
    status: str
    phase: str = "queued"
    total_questions: int = 0
    processed_questions: int = 0
    verified: int = 0
    skipped: int = 0
    errors: int = 0
    progress_pct: float = 0.0
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ── Reorder helpers ───────────────────────────────────────────────────────

class ReorderItem(BaseModel):
    id: str
    order: int

class ReorderRequest(BaseModel):
    items: list[ReorderItem]

