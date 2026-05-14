"""
SQLAlchemy ORM models – defines the complete taxonomy:

  Case
   ├── DocumentType  (e.g. "FBI Records", code "11")
   │    └── Section  (e.g. "Introduction", code "a"  → subindex "11a")
   │         └── Page assignments
   ├── Page          (individual page extracted from uploaded files)
   ├── Checklist
   │    └── ChecklistItem
   │         └── EvidenceLink  → Page
   └── AuditLog
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PageStatus(str, enum.Enum):
    UNCLASSIFIED = "unclassified"
    CLASSIFIED = "classified"
    EXTRA = "extra"


class ChecklistItemStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    NOT_APPLICABLE = "na"


class FormFillingJobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Case(Base):
    __tablename__ = "cases"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    form_filling_source_document_ids = Column(JSON, nullable=True)
    qc_checklist_source_document_ids = Column(JSON, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    creator = relationship("User", foreign_keys=[created_by])
    case_users = relationship("CaseUser", back_populates="case", cascade="all, delete-orphan")
    document_types = relationship(
        "DocumentType", back_populates="case", cascade="all, delete-orphan",
        order_by="DocumentType.order",
    )
    pages = relationship(
        "Page", back_populates="case", cascade="all, delete-orphan",
    )
    checklists = relationship(
        "Checklist", back_populates="case", cascade="all, delete-orphan",
    )
    form_filling_jobs = relationship(
        "FormFillingJob", back_populates="case", cascade="all, delete-orphan",
    )
    questionnaire_answers = relationship(
        "QuestionnaireAnswer", back_populates="case", cascade="all, delete-orphan",
    )
    audit_logs = relationship(
        "AuditLog", back_populates="case", cascade="all, delete-orphan",
    )


class DocumentType(Base):
    __tablename__ = "document_types"

    id = Column(String, primary_key=True, default=_uuid)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False)
    name = Column(String, nullable=False)
    code = Column(String, nullable=False)
    order = Column(Integer, default=0)
    has_tables = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_utcnow)

    case = relationship("Case", back_populates="document_types")
    sections = relationship(
        "Section", back_populates="document_type", cascade="all, delete-orphan",
        order_by="Section.order",
    )
    pages = relationship("Page", back_populates="document_type")


class Section(Base):
    __tablename__ = "sections"

    id = Column(String, primary_key=True, default=_uuid)
    document_type_id = Column(String, ForeignKey("document_types.id"), nullable=False)
    parent_section_id = Column(String, ForeignKey("sections.id"), nullable=True)
    name = Column(String, nullable=False)
    code = Column(String, nullable=False)
    path_code = Column(String, default="")   # e.g. "B.1.2" – computed
    depth = Column(Integer, default=0)
    order = Column(Integer, default=0)
    is_required = Column(Boolean, default=True)

    document_type = relationship("DocumentType", back_populates="sections")
    parent = relationship("Section", remote_side="Section.id", backref="children")
    pages = relationship(
        "Page", back_populates="section", order_by="Page.order_in_section",
    )
    page_links = relationship(
        "PageSectionLink", back_populates="section", cascade="all, delete-orphan",
    )
    checklist_targets = relationship(
        "ChecklistItemSectionTarget", back_populates="section", cascade="all, delete-orphan",
    )


class ExtractionStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"


class IndexStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"
    SKIPPED = "skipped"


class Page(Base):
    __tablename__ = "pages"

    id = Column(String, primary_key=True, default=_uuid)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False)
    source_document_id = Column(String, nullable=True)
    original_filename = Column(String, nullable=False)
    original_page_number = Column(Integer, default=1)
    thumbnail_path = Column(String, default="")
    file_path = Column(String, default="")
    document_type_id = Column(String, ForeignKey("document_types.id"), nullable=True)
    section_id = Column(String, ForeignKey("sections.id"), nullable=True)
    subindex = Column(String, nullable=True)
    order_in_section = Column(Integer, nullable=True)
    status = Column(String, default=PageStatus.UNCLASSIFIED.value)
    metadata_json = Column(JSON, default=dict)
    # ── Extraction / OCR fields ──
    ocr_text = Column(Text, nullable=True)
    extraction_status = Column(String, default=ExtractionStatus.PENDING.value)
    extraction_method = Column(String, nullable=True)  # "gemini_tables" | "gemini_ocr"
    index_status = Column(String, default=IndexStatus.PENDING.value)
    index_method = Column(String, nullable=True)
    indexed_at = Column(DateTime, nullable=True)
    indexed_vector_count = Column(Integer, default=0)
    pinecone_document_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    deleted_at = Column(DateTime, nullable=True)

    case = relationship("Case", back_populates="pages")
    document_type = relationship("DocumentType", back_populates="pages")
    section = relationship("Section", back_populates="pages")
    evidence_links = relationship(
        "EvidenceLink", back_populates="page", cascade="all, delete-orphan",
    )
    section_links = relationship(
        "PageSectionLink", back_populates="page", cascade="all, delete-orphan",
    )


# ---------------------------------------------------------------------------
# Page ↔ Section links (many-to-many with primary flag)
# ---------------------------------------------------------------------------

class PageSectionLink(Base):
    """Many-to-many: a page can be linked to one or more sections.
    Exactly one link per page must have is_primary=True."""
    __tablename__ = "page_section_links"

    id = Column(String, primary_key=True, default=_uuid)
    page_id = Column(String, ForeignKey("pages.id"), nullable=False)
    section_id = Column(String, ForeignKey("sections.id"), nullable=False)
    is_primary = Column(Boolean, default=False)
    order_in_section = Column(Integer, default=0)
    created_at = Column(DateTime, default=_utcnow)

    page = relationship("Page", back_populates="section_links")
    section = relationship("Section", back_populates="page_links")


class Checklist(Base):  # noqa: E302
    __tablename__ = "checklists"

    id = Column(String, primary_key=True, default=_uuid)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=_utcnow)

    case = relationship("Case", back_populates="checklists")
    items = relationship(
        "ChecklistItem", back_populates="checklist", cascade="all, delete-orphan",
        order_by="ChecklistItem.order",
    )


class ChecklistItem(Base):
    __tablename__ = "checklist_items"

    id = Column(String, primary_key=True, default=_uuid)
    checklist_id = Column(String, ForeignKey("checklists.id"), nullable=False)
    description = Column(Text, nullable=False)
    status = Column(String, default=ChecklistItemStatus.PENDING.value)
    order = Column(Integer, default=0)
    notes = Column(Text, default="")

    checklist = relationship("Checklist", back_populates="items")
    evidence_links = relationship(
        "EvidenceLink", back_populates="checklist_item", cascade="all, delete-orphan",
    )
    section_targets = relationship(
        "ChecklistItemSectionTarget", back_populates="checklist_item", cascade="all, delete-orphan",
    )


class EvidenceLink(Base):
    __tablename__ = "evidence_links"

    id = Column(String, primary_key=True, default=_uuid)
    checklist_item_id = Column(String, ForeignKey("checklist_items.id"), nullable=False)
    page_id = Column(String, ForeignKey("pages.id"), nullable=False)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)

    checklist_item = relationship("ChecklistItem", back_populates="evidence_links")
    page = relationship("Page", back_populates="evidence_links")


# ---------------------------------------------------------------------------
# Checklist ↔ Section target mapping
# ---------------------------------------------------------------------------

class ChecklistItemSectionTarget(Base):
    """Many-to-many: a checklist item points to one or more sections where
    evidence should be searched."""
    __tablename__ = "checklist_item_section_targets"

    id = Column(String, primary_key=True, default=_uuid)
    checklist_item_id = Column(String, ForeignKey("checklist_items.id"), nullable=False)
    section_id = Column(String, ForeignKey("sections.id"), nullable=False)
    created_at = Column(DateTime, default=_utcnow)

    checklist_item = relationship("ChecklistItem", back_populates="section_targets")
    section = relationship("Section", back_populates="checklist_targets")


# ---------------------------------------------------------------------------
# Global Template Library
# ---------------------------------------------------------------------------

class Template(Base):
    """Reusable template that bundles a taxonomy tree + checklists."""
    __tablename__ = "templates"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)

    nodes = relationship("TemplateNode", back_populates="template", cascade="all, delete-orphan",
                         order_by="TemplateNode.order")
    checklists = relationship("TemplateChecklist", back_populates="template", cascade="all, delete-orphan")


class TemplateNode(Base):
    """A node in a template taxonomy tree (doc type or section at any depth)."""
    __tablename__ = "template_nodes"

    id = Column(String, primary_key=True, default=_uuid)
    template_id = Column(String, ForeignKey("templates.id"), nullable=False)
    parent_node_id = Column(String, ForeignKey("template_nodes.id"), nullable=True)
    name = Column(String, nullable=False)
    code = Column(String, nullable=False)
    node_type = Column(String, default="section")  # "doc_type" | "section"
    has_tables = Column(Boolean, default=False)
    is_required = Column(Boolean, default=True)
    depth = Column(Integer, default=0)
    order = Column(Integer, default=0)

    template = relationship("Template", back_populates="nodes")
    parent = relationship("TemplateNode", remote_side="TemplateNode.id", backref="children_nodes")
    item_links = relationship("TemplateItemNodeLink", back_populates="node", cascade="all, delete-orphan")


class TemplateChecklist(Base):
    __tablename__ = "template_checklists"

    id = Column(String, primary_key=True, default=_uuid)
    template_id = Column(String, ForeignKey("templates.id"), nullable=False)
    name = Column(String, nullable=False)

    template = relationship("Template", back_populates="checklists")
    items = relationship("TemplateChecklistItem", back_populates="checklist", cascade="all, delete-orphan",
                         order_by="TemplateChecklistItem.order")


class TemplateChecklistItem(Base):
    __tablename__ = "template_checklist_items"

    id = Column(String, primary_key=True, default=_uuid)
    checklist_id = Column(String, ForeignKey("template_checklists.id"), nullable=False)
    description = Column(Text, nullable=False)
    order = Column(Integer, default=0)

    checklist = relationship("TemplateChecklist", back_populates="items")
    node_links = relationship("TemplateItemNodeLink", back_populates="item", cascade="all, delete-orphan")


class TemplateItemNodeLink(Base):
    """Pre-configured mapping: template checklist item → template node (section)."""
    __tablename__ = "template_item_node_links"

    id = Column(String, primary_key=True, default=_uuid)
    item_id = Column(String, ForeignKey("template_checklist_items.id"), nullable=False)
    node_id = Column(String, ForeignKey("template_nodes.id"), nullable=False)

    item = relationship("TemplateChecklistItem", back_populates="node_links")
    node = relationship("TemplateNode", back_populates="item_links")


# ---------------------------------------------------------------------------
# Complex QC Checklists (hierarchical: Parts → Subparts → Questions)
# ---------------------------------------------------------------------------

class QCAnswerStatus(str, enum.Enum):
    UNANSWERED = "unanswered"
    YES = "yes"
    NO = "no"
    NA = "na"
    INSUFFICIENT = "insufficient"


class QCChecklist(Base):
    """Complex QC checklist – can be a reusable template (case_id=NULL) or a
    case-bound instance.  E.g. 'QC Checklist – I-914 (T-1)'."""
    __tablename__ = "qc_checklists"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    case_id = Column(String, ForeignKey("cases.id"), nullable=True)
    is_template = Column(Boolean, default=False)
    source_template_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    case = relationship("Case", backref="qc_checklists")
    parts = relationship("QCPart", back_populates="checklist", cascade="all, delete-orphan",
                         order_by="QCPart.order")


class QCPart(Base):
    """Hierarchical grouping node.  E.g. 'Part 4', '4.1 Criminal', '4.3.1 Acts'."""
    __tablename__ = "qc_parts"

    id = Column(String, primary_key=True, default=_uuid)
    checklist_id = Column(String, ForeignKey("qc_checklists.id"), nullable=False)
    parent_part_id = Column(String, ForeignKey("qc_parts.id"), nullable=True)
    name = Column(String, nullable=False)
    code = Column(String, nullable=False)
    order = Column(Integer, default=0)
    depth = Column(Integer, default=0)

    checklist = relationship("QCChecklist", back_populates="parts")
    parent = relationship("QCPart", remote_side="QCPart.id", backref="children_parts")
    questions = relationship("QCQuestion", back_populates="part", cascade="all, delete-orphan",
                             order_by="QCQuestion.order")


class QCQuestion(Base):
    """A single verification question.  E.g. code='4.1.A', 'Did you verify whether…'."""
    __tablename__ = "qc_questions"

    id = Column(String, primary_key=True, default=_uuid)
    part_id = Column(String, ForeignKey("qc_parts.id"), nullable=False)
    code = Column(String, nullable=False)           # e.g. "4.1.A"
    description = Column(Text, nullable=False)      # exact question text
    where_to_verify = Column(Text, default="")      # e.g. "Intake; Bio Call; Declaration"
    order = Column(Integer, default=0)

    # ── Runtime answer fields (only filled when in a case instance) ──
    answer = Column(String, default=QCAnswerStatus.UNANSWERED.value)
    correction = Column(Text, default="")
    notes = Column(Text, default="")
    answered_by = Column(String, nullable=True)
    answered_at = Column(DateTime, nullable=True)
    # ── AI verification fields ──
    ai_answer = Column(String, nullable=True)       # "yes" | "no" | "na"
    ai_notes = Column(Text, default="")              # AI explanation
    ai_confidence = Column(String, nullable=True)    # "high" | "medium" | "low"
    ai_verified_at = Column(DateTime, nullable=True)
    # ── Section targets (JSON list of section_ids) ──
    target_section_ids = Column(JSON, default=list)

    part = relationship("QCPart", back_populates="questions")
    evidence = relationship("QCQuestionEvidence", back_populates="question", cascade="all, delete-orphan")


class QCQuestionEvidence(Base):
    """Evidence link: QC question → page from the case."""
    __tablename__ = "qc_question_evidence"

    id = Column(String, primary_key=True, default=_uuid)
    question_id = Column(String, ForeignKey("qc_questions.id"), nullable=False)
    page_id = Column(String, ForeignKey("pages.id"), nullable=False)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)

    question = relationship("QCQuestion", back_populates="evidence")
    page = relationship("Page")


# ---------------------------------------------------------------------------
# QC Link Presets (reusable QC-question → document-section mappings)
# ---------------------------------------------------------------------------

class QCLinkPreset(Base):
    """A saved preset that maps QC question codes → document section path_codes.
    Created from a case-bound QC checklist, reusable across cases."""
    __tablename__ = "qc_link_presets"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    qc_template_id = Column(String, nullable=True)   # source QC template id (for auto-match)
    doc_template_id = Column(String, nullable=True)   # source doc template id (informational)
    created_at = Column(DateTime, default=_utcnow)

    mappings = relationship(
        "QCLinkPresetMapping", back_populates="preset", cascade="all, delete-orphan",
    )


class QCLinkPresetMapping(Base):
    """One row per QC question → list of section path_codes."""
    __tablename__ = "qc_link_preset_mappings"

    id = Column(String, primary_key=True, default=_uuid)
    preset_id = Column(String, ForeignKey("qc_link_presets.id"), nullable=False)
    question_code = Column(String, nullable=False)
    section_path_codes = Column(JSON, default=list)   # ["B.1.a", "B.2.b"]

    preset = relationship("QCLinkPreset", back_populates="mappings")


# ---------------------------------------------------------------------------
# Form Templates (pre-loaded PDF forms in S3)
# ---------------------------------------------------------------------------

class FormTemplate(Base):
    __tablename__ = "form_templates"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    form_type = Column(String, nullable=False, unique=True)
    description = Column(String, default="")
    s3_key = Column(String, nullable=False)
    original_filename = Column(String, nullable=False)
    file_size = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


# ---------------------------------------------------------------------------
# Questionnaire Answers
# ---------------------------------------------------------------------------

class QuestionnaireAnswer(Base):
    __tablename__ = "questionnaire_answers"
    __table_args__ = (
        UniqueConstraint("case_id", "question_id", "form_type"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False)
    question_id = Column(String, nullable=False)
    value = Column(Text, default="")
    source = Column(String, default="shared")
    form_type = Column(String, nullable=True)
    verification_status = Column(String, nullable=True)
    verification_reason = Column(Text, nullable=True)
    verification_evidence = Column(Text, nullable=True)
    verification_model = Column(String, nullable=True)
    verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    case = relationship("Case", back_populates="questionnaire_answers")

# ---------------------------------------------------------------------------
# Form Filling Jobs
# ---------------------------------------------------------------------------

class FormFillingJob(Base):
    __tablename__ = "form_filling_jobs"

    id = Column(String, primary_key=True, default=_uuid)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False)
    form_type = Column(String, nullable=True)
    status = Column(String, default=FormFillingJobStatus.QUEUED.value)
    phase = Column(String, default="queued")
    progress_pct = Column(Float, default=0.0)
    original_pdf_path = Column(String, default="")
    filled_pdf_path = Column(String, default="")
    field_count = Column(Integer, default=0)
    filled_count = Column(Integer, default=0)
    client_field_count = Column(Integer, default=0)
    client_filled_count = Column(Integer, default=0)
    attorney_field_count = Column(Integer, default=0)
    attorney_filled_count = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    warnings = Column(JSON, default=list)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    case = relationship("Case", back_populates="form_filling_jobs")
    fields = relationship(
        "FormFillingField", back_populates="job", cascade="all, delete-orphan",
        order_by="FormFillingField.created_at",
    )


class FormFillingField(Base):
    __tablename__ = "form_filling_fields"

    id = Column(String, primary_key=True, default=_uuid)
    job_id = Column(String, ForeignKey("form_filling_jobs.id"), nullable=False)
    field_name = Column(String, nullable=False)
    field_label = Column(String, default="")
    field_type = Column(String, default="text")
    questionnaire_item_id = Column(String, nullable=True)
    questionnaire_field_id = Column(String, nullable=True)
    questionnaire_option_value = Column(String, nullable=True)
    page_number = Column(Integer, nullable=True)
    responsible_party = Column(String, default="client")
    extracted_value = Column(Text, default="")
    confidence = Column(String, nullable=True)
    evidence_source = Column(Text, default="")
    manually_corrected = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    job = relationship("FormFillingJob", back_populates="fields")


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, default=_uuid)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False)
    action = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)
    entity_id = Column(String, nullable=True)
    details = Column(JSON, default=dict)
    user = Column(String, default="system")
    created_at = Column(DateTime, default=_utcnow)

    case = relationship("Case", back_populates="audit_logs")


# ---------------------------------------------------------------------------
# Teams & Supervision
# ---------------------------------------------------------------------------

class Team(Base):
    """Supervision team owned by a supervisor. Groups case managers."""
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, autoincrement=True)
    uuid = Column(String, unique=True, nullable=False, default=_uuid)
    name = Column(String, nullable=False)
    supervisor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    deleted_at = Column(DateTime, nullable=True)

    supervisor = relationship("User", back_populates="teams")
    members = relationship("TeamUser", back_populates="team", cascade="all, delete-orphan")


class TeamUser(Base):
    """Pivot: which case managers belong to which team."""
    __tablename__ = "team_user"
    __table_args__ = (UniqueConstraint("team_id", "user_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    uuid = Column(String, unique=True, nullable=False, default=_uuid)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    is_primary = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    deleted_at = Column(DateTime, nullable=True)

    team = relationship("Team", back_populates="members")
    user = relationship("User", back_populates="team_memberships")


class CaseUser(Base):
    """Pivot: which user is currently responsible for a case.
    Soft-deleted rows preserve reassignment history."""
    __tablename__ = "case_user"

    id = Column(Integer, primary_key=True, autoincrement=True)
    uuid = Column(String, unique=True, nullable=False, default=_uuid)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    deleted_at = Column(DateTime, nullable=True)

    case = relationship("Case", back_populates="case_users")
    user = relationship("User", back_populates="case_assignments")


# ---------------------------------------------------------------------------
# RBAC – Users, Roles, Permissions
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    user_roles = relationship("UserRole", back_populates="user", cascade="all, delete-orphan")
    user_permissions = relationship("UserPermission", back_populates="user", cascade="all, delete-orphan")
    teams = relationship("Team", back_populates="supervisor")
    team_memberships = relationship("TeamUser", back_populates="user")
    case_assignments = relationship("CaseUser", back_populates="user")


class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    role_permissions = relationship("RolePermission", back_populates="role", cascade="all, delete-orphan")
    user_roles = relationship("UserRole", back_populates="role", cascade="all, delete-orphan")


class Permission(Base):
    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    role_permissions = relationship("RolePermission", back_populates="permission", cascade="all, delete-orphan")
    user_permissions = relationship("UserPermission", back_populates="permission", cascade="all, delete-orphan")


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)

    user = relationship("User", back_populates="user_roles")
    role = relationship("Role", back_populates="user_roles")


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    permission_id = Column(Integer, ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False)

    role = relationship("Role", back_populates="role_permissions")
    permission = relationship("Permission", back_populates="role_permissions")


class UserPermission(Base):
    __tablename__ = "user_permissions"
    __table_args__ = (UniqueConstraint("user_id", "permission_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    permission_id = Column(Integer, ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False)

    user = relationship("User", back_populates="user_permissions")
    permission = relationship("Permission", back_populates="user_permissions")

