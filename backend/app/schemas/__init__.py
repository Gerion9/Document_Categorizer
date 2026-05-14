"""
Pydantic schemas for request / response validation.
"""

from __future__ import annotations
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── Case ──────────────────────────────────────────────────────────────────

class CaseCreate(BaseModel):
    name: str
    description: str = ""

class CaseUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    form_filling_source_document_ids: Optional[list[str]] = None
    qc_checklist_source_document_ids: Optional[list[str]] = None

class CaseOut(ORMModel):
    id: str
    name: str
    description: str
    created_by: Optional[int] = None
    created_by_name: str = ""
    created_at: datetime
    updated_at: datetime
    page_count: int = 0
    classified_count: int = 0
    checklist_count: int = 0
    form_filling_source_document_ids: Optional[list[str]] = None
    qc_checklist_source_document_ids: Optional[list[str]] = None

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

class SectionOut(ORMModel):
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
    children: list[SectionOut] = Field(default_factory=list)

class DocumentTypeOut(ORMModel):
    id: str
    case_id: str
    name: str
    code: str
    order: int
    has_tables: bool = False
    created_at: datetime
    sections: list[SectionOut] = Field(default_factory=list)


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

class PageOut(ORMModel):
    id: str
    case_id: str
    source_document_id: Optional[str] = None
    original_filename: str
    original_page_number: int
    thumbnail_path: str
    file_path: str
    document_type_id: Optional[str] = None
    section_id: Optional[str] = None
    subindex: Optional[str] = None
    order_in_section: Optional[int] = None
    status: str
    metadata_json: dict[str, Any] = Field(default_factory=dict)
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
    section_links: list[PageSectionLinkOut] = Field(default_factory=list)
    link_count: int = 0
    # Presigned S3 URLs (generated at response time, 1 h TTL)
    file_url: str = ""
    thumbnail_url: str = ""

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

class PageSectionLinkOut(ORMModel):
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
    target_section_ids: list[str] = Field(default_factory=list)

class ChecklistItemUpdate(BaseModel):
    description: Optional[str] = None
    status: Optional[str] = None
    order: Optional[int] = None
    notes: Optional[str] = None
    target_section_ids: Optional[list[str]] = None

class EvidenceLinkCreate(BaseModel):
    page_id: str
    notes: str = ""

class EvidenceLinkOut(ORMModel):
    id: str
    checklist_item_id: str
    page_id: str
    notes: str
    created_at: datetime
    page: Optional[PageOut] = None

class SectionTargetOut(ORMModel):
    id: str
    section_id: str
    section_path_code: str = ""
    section_name: str = ""

class ChecklistItemOut(ORMModel):
    id: str
    checklist_id: str
    description: str
    status: str
    order: int
    notes: str
    evidence_links: list[EvidenceLinkOut] = Field(default_factory=list)
    target_sections: list[SectionTargetOut] = Field(default_factory=list)

class ChecklistOut(ORMModel):
    id: str
    case_id: str
    name: str
    created_at: datetime
    items: list[ChecklistItemOut] = Field(default_factory=list)
    completion_pct: float = 0.0


# ── AuditLog ──────────────────────────────────────────────────────────────

class AuditLogOut(ORMModel):
    id: str
    case_id: str
    action: str
    entity_type: str
    entity_id: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)
    user: str
    created_at: datetime


# ── QC Checklist (complex hierarchical) ───────────────────────────────────

class QCQuestionEvidenceOut(ORMModel):
    id: str
    question_id: str
    page_id: str
    notes: str
    created_at: datetime
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

class QCQuestionOut(ORMModel):
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
    target_section_ids: list[str] = Field(default_factory=list)
    evidence: list[QCQuestionEvidenceOut] = Field(default_factory=list)

class QCPartCreate(BaseModel):
    name: str
    code: str
    order: int = 0
    parent_part_id: Optional[str] = None

class QCPartUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    order: Optional[int] = None

class QCPartOut(ORMModel):
    id: str
    checklist_id: str
    parent_part_id: Optional[str] = None
    name: str
    code: str
    order: int
    depth: int = 0
    questions: list[QCQuestionOut] = Field(default_factory=list)
    children: list[QCPartOut] = Field(default_factory=list)

class QCChecklistCreate(BaseModel):
    name: str
    description: str = ""
    is_template: bool = False

class QCChecklistOut(ORMModel):
    id: str
    name: str
    description: str
    case_id: Optional[str] = None
    is_template: bool = False
    source_template_id: Optional[str] = None
    created_at: datetime
    parts: list[QCPartOut] = Field(default_factory=list)
    total_questions: int = 0
    answered_questions: int = 0

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

class TemplateNodeOut(ORMModel):
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
    children: list[TemplateNodeOut] = Field(default_factory=list)
    target_item_ids: list[str] = Field(default_factory=list)

class TemplateChecklistItemCreate(BaseModel):
    description: str
    order: int = 0
    target_node_ids: list[str] = Field(default_factory=list)

class TemplateChecklistItemOut(ORMModel):
    id: str
    description: str
    order: int
    target_node_ids: list[str] = Field(default_factory=list)

class TemplateChecklistCreate(BaseModel):
    name: str
    items: list[TemplateChecklistItemCreate] = Field(default_factory=list)

class TemplateChecklistOut(ORMModel):
    id: str
    name: str
    items: list[TemplateChecklistItemOut] = Field(default_factory=list)

class TemplateCreate(BaseModel):
    name: str
    description: str = ""

class TemplateOut(ORMModel):
    id: str
    name: str
    description: str
    created_at: datetime
    nodes: list[TemplateNodeOut] = Field(default_factory=list)
    checklists: list[TemplateChecklistOut] = Field(default_factory=list)

class ApplyTemplateRequest(BaseModel):
    template_id: str


# ── QC Link Presets ───────────────────────────────────────────────────────

class QCLinkPresetMappingOut(ORMModel):
    id: str
    question_code: str
    section_path_codes: list[str] = Field(default_factory=list)

class QCLinkPresetOut(ORMModel):
    id: str
    name: str
    qc_template_id: Optional[str] = None
    doc_template_id: Optional[str] = None
    created_at: datetime
    mappings: list[QCLinkPresetMappingOut] = Field(default_factory=list)
    mapping_count: int = 0

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
    ocr_total_pages: int = 0
    ocr_processed_pages: int = 0
    ocr_error_pages: int = 0
    index_total_chunks: int = 0
    index_processed_chunks: int = 0
    index_error_chunks: int = 0
    evidence_total_questions: int = 0
    evidence_processed_questions: int = 0
    total_questions: int = 0
    processed_questions: int = 0
    verified: int = 0
    skipped: int = 0
    errors: int = 0
    phase_progress_pct: float = 0.0
    overall_progress_pct: float = 0.0
    progress_pct: float = 0.0
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ── Form Templates ──────────────────────────────────────────────────────────

class FormTemplateOut(ORMModel):
    id: str
    name: str
    form_type: str
    description: str = ""
    s3_key: str
    original_filename: str
    file_size: Optional[int] = None
    created_at: datetime
    updated_at: datetime

# ── PDF Form Filling ────────────────────────────────────────────────────────

class QuestionnaireOptionOut(BaseModel):
    value: str
    label: str


class QuestionnaireFieldOut(BaseModel):
    id: str
    label: str
    type: str
    default_value: Any | None = None
    allow_literal_values: list[str] = Field(default_factory=list)
    optional: bool = False
    instruction: Optional[str] = None
    condition: Optional[str] = None
    format: Optional[str] = None
    prefix: Optional[str] = None
    options: list[QuestionnaireOptionOut | str] = Field(default_factory=list)


class QuestionnaireExcludedSectionOut(BaseModel):
    name: str
    reason: str


class QuestionnaireItemOut(BaseModel):
    id: str
    code: str = ""
    section: str = ""
    responsible_party: str = "client"
    type: str
    form_text: str = ""
    default_value: Any | None = None
    instruction: Optional[str] = None
    condition: Optional[str] = None
    optional: bool = False
    format: Optional[str] = None
    prefix: Optional[str] = None
    visible_on_pages: list[int] = Field(default_factory=list)
    visible_slots: list[Any] = Field(default_factory=list)
    also_validate_with: list[str] = Field(default_factory=list)
    options: list[QuestionnaireOptionOut | str] = Field(default_factory=list)
    fields: list[QuestionnaireFieldOut] = Field(default_factory=list)
    details_fields: list[QuestionnaireFieldOut] = Field(default_factory=list)


class QuestionnairePageOut(BaseModel):
    page: int
    items: list[QuestionnaireItemOut] = Field(default_factory=list)
    excluded_sections: list[QuestionnaireExcludedSectionOut] = Field(default_factory=list)


class QuestionnaireFormTypeOut(BaseModel):
    form_type: str
    label: str
    description: str


class QuestionnaireAnswerUpsert(BaseModel):
    question_id: str
    value: Any = None
    source: str = "shared"
    form_type: Optional[str] = None


class QuestionnaireAnswersSaveRequest(BaseModel):
    answers: list[QuestionnaireAnswerUpsert] = Field(default_factory=list)


class QuestionnaireAnswersSaveResponse(BaseModel):
    saved_count: int = 0


class QuestionnaireAutofillResponse(BaseModel):
    answers: dict[str, Any] = Field(default_factory=dict)
    total_targets: int = 0
    suggested_count: int = 0
    confidence_map: dict[str, Any] = Field(default_factory=dict)
    skipped_low_confidence: int = 0
    form_answers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    form_confidence_map: dict[str, dict[str, Any]] = Field(default_factory=dict)
    forced_answers: dict[str, Any] = Field(default_factory=dict)
    forced_form_answers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    verification_map: dict[str, Any] = Field(default_factory=dict)
    form_verification_map: dict[str, dict[str, Any]] = Field(default_factory=dict)


class AutofillJobStatus(BaseModel):
    id: str
    case_id: str
    kind: str
    status: str
    progress_pct: float = 0.0
    progress_message: str = ""
    ocr_total_pages: int = 0
    ocr_processed_pages: int = 0
    error: Optional[str] = None
    result: Optional[QuestionnaireAutofillResponse] = None
    created_at: float
    started_at: Optional[float] = None
    finished_at: Optional[float] = None


class FormGenerationRequest(BaseModel):
    form_type: str


class FormFillingUploadRequest(BaseModel):
    form_type: Optional[str] = None


class FormFillingRegenerateRequest(BaseModel):
    preserve_manual_corrections: bool = True


class FormFillingFieldUpdate(BaseModel):
    extracted_value: str
    confidence: Optional[str] = None
    evidence_source: Optional[str] = None
    manually_corrected: bool = True


class FormFillingFieldOptionOut(BaseModel):
    value: str
    label: str


class FormFillingFieldOut(ORMModel):
    id: str
    job_id: str
    field_name: str
    field_label: str = ""
    field_type: str = "text"
    questionnaire_item_id: Optional[str] = None
    questionnaire_field_id: Optional[str] = None
    questionnaire_option_value: Optional[str] = None
    page_number: Optional[int] = None
    responsible_party: str = "client"
    extracted_value: str = ""
    confidence: Optional[str] = None
    evidence_source: str = ""
    manually_corrected: bool = False
    section: str = ""
    form_text: str = ""
    instruction: Optional[str] = None
    condition: Optional[str] = None
    optional: bool = False
    requires_manual_confirmation: bool = False
    questionnaire_options: list[FormFillingFieldOptionOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

class FormFillingJobOut(ORMModel):
    id: str
    case_id: str
    form_type: Optional[str] = None
    status: str
    phase: str = "queued"
    progress_pct: float = 0.0
    original_pdf_path: str = ""
    filled_pdf_path: str = ""
    field_count: int = 0
    filled_count: int = 0
    client_field_count: int = 0
    client_filled_count: int = 0
    attorney_field_count: int = 0
    attorney_filled_count: int = 0
    error_message: Optional[str] = None
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    fields: list[FormFillingFieldOut] = Field(default_factory=list)

# ── Reorder helpers ───────────────────────────────────────────────────────

class ReorderItem(BaseModel):
    id: str
    order: int

class ReorderRequest(BaseModel):
    items: list[ReorderItem]

class SSOLoginRequest(BaseModel):
    email: str
    name: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    signature: str


class PermissionOut(ORMModel):
    id: int
    name: str

class RoleOut(ORMModel):
    id: int
    name: str

class UserOut(ORMModel):
    id: int
    email: str
    name: str
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)


class SSOLoginResponse(BaseModel):
    token: str
    user: UserOut


# ── Admin: User & Role management ────────────────────────────────────────

class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None

class UserDetail(ORMModel):
    id: int
    email: str
    name: str
    roles: list[RoleOut] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None

class SyncRolesRequest(BaseModel):
    role_ids: list[int]

class AddRoleRequest(BaseModel):
    role_id: int


# ── Roles CRUD ────────────────────────────────────────────────────────────

class RoleCreate(BaseModel):
    name: str

class RoleUpdate(BaseModel):
    name: str

class RoleDetailOut(ORMModel):
    """Rol con sus permisos asociados — usado en GET /roles y respuestas CRUD."""
    id: int
    name: str
    permissions: list[PermissionOut] = Field(default_factory=list)
    created_at: Optional[datetime] = None

class SyncPermissionsRequest(BaseModel):
    """Lista de IDs de permisos que reemplazarán los actuales del rol."""
    permission_ids: list[int]


# ── Teams & Supervision ──────────────────────────────────────────────────

class TeamMemberInput(BaseModel):
    """Input item when creating/updating a team: identifies the case manager."""
    id: int
    is_primary: bool = False

class TeamMemberUpdateInput(BaseModel):
    """Input item for PUT /teams/{uuid}: may include existing uuid_team_user."""
    id: int
    uuid_team_user: Optional[str] = None
    is_primary: bool = False

class TeamCreate(BaseModel):
    name: str
    users: list[TeamMemberInput] = Field(default_factory=list)

class TeamUpdate(BaseModel):
    name: Optional[str] = None
    users: list[TeamMemberUpdateInput] = Field(default_factory=list)

class TeamOut(ORMModel):
    uuid: str
    name: str
    members_count: int = 0

class TeamMemberOut(ORMModel):
    uuid_team_user: str
    id: int
    name: str
    email: str
    is_primary: bool

class SupervisorOut(ORMModel):
    id: int
    name: str

class TeamDetailOut(ORMModel):
    team_uuid: str
    team_name: str
    supervisor: SupervisorOut
    members: list[TeamMemberOut] = Field(default_factory=list)


# ── Case ↔ User (assignment pivot) ───────────────────────────────────────

class CaseUserOut(ORMModel):
    uuid: str
    case_id: str
    user_id: int
    user_name: str = ""
    user_email: str = ""
    created_at: datetime

# ── Supervisor: case view ─────────────────────────────────────────────────

class CaseManagerInfo(ORMModel):
    id: int
    name: str

class TeamInfo(ORMModel):
    uuid: str
    name: str

class SupervisorCaseOut(ORMModel):
    case_id: str
    case_uuid: str
    name: str
    description: str = ""
    case_manager: CaseManagerInfo
    team: TeamInfo
    created_at: datetime
    updated_at: datetime
