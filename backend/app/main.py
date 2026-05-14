"""
FastAPI entry point for the Document Categorizer & Extractor backend.

Run with:
    cd backend
    uvicorn app.main:app --reload --port 8000
"""

import logging
import os

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from .core.config import get_runtime_settings
from .database import Base, engine, DB_CONNECTION, SessionLocal
from .models import (
    Template, TemplateNode,
    Role, Permission, RolePermission,
    User, UserRole,
    FormTemplate,
)
from .routers import cases, checklist, documents, export, pages, extraction, templates, qc_checklist, form_filling, form_templates, auth, admin, roles, permissions, teams, supervisor
from .routers.auth import get_current_user, require_role
from .services.indexing_service import recover_interrupted_processing_states
from .services.startup_validation import LAST_STARTUP_VALIDATION_REPORT, run_startup_validations


def _configure_logger(name: str, level: int) -> None:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    if not logger.handlers:
        logger.addHandler(logging.StreamHandler())
    logger.propagate = False


_BACKEND_LOG_LEVEL = getattr(logging, os.getenv("BACKEND_LOG_LEVEL", "WARNING").strip().upper(), logging.WARNING)
_configure_logger("qc_autopilot", _BACKEND_LOG_LEVEL)
_configure_logger("gemini_usage", _BACKEND_LOG_LEVEL)
_configure_logger("json_export", _BACKEND_LOG_LEVEL)
_configure_logger("extraction", _BACKEND_LOG_LEVEL)
_configure_logger("form_filling", _BACKEND_LOG_LEVEL)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
settings = get_runtime_settings()

# ---------------------------------------------------------------------------
# 1. Keep SQLite local-first, but let Alembic own PostgreSQL schemas
# ---------------------------------------------------------------------------
if DB_CONNECTION == "sqlite":
    Base.metadata.create_all(bind=engine)
else:
    logging.info("Skipping Base.metadata.create_all() because Alembic manages non-SQLite schemas.")


# ---------------------------------------------------------------------------
# 2. Legacy migrations (only needed for SQLite databases created before
#    the current schema — PostgreSQL starts fresh via create_all)
# ---------------------------------------------------------------------------
def _run_migrations():
    """Add columns that may be missing from earlier schema versions."""
    if not settings.should_run_legacy_migrations():
        logging.info("Skipping legacy startup migrations because they are disabled for this environment.")
        return

    if DB_CONNECTION != "sqlite":
        logging.info("Skipping legacy startup migrations for non-SQLite database.")
        return

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    migrations: list[str] = []

    if "cases" in existing_tables:
        case_cols = {c["name"] for c in inspector.get_columns("cases")}
        if "form_filling_source_document_ids" not in case_cols:
            migrations.append("ALTER TABLE cases ADD COLUMN form_filling_source_document_ids JSON")
        if "qc_checklist_source_document_ids" not in case_cols:
            migrations.append("ALTER TABLE cases ADD COLUMN qc_checklist_source_document_ids JSON")

    if "document_types" in existing_tables:
        dt_cols = {c["name"] for c in inspector.get_columns("document_types")}
        if "has_tables" not in dt_cols:
            migrations.append("ALTER TABLE document_types ADD COLUMN has_tables BOOLEAN DEFAULT 0")

    if "pages" in existing_tables:
        page_cols = {c["name"] for c in inspector.get_columns("pages")}
        if "ocr_text" not in page_cols:
            migrations.append("ALTER TABLE pages ADD COLUMN ocr_text TEXT")
        if "extraction_status" not in page_cols:
            migrations.append("ALTER TABLE pages ADD COLUMN extraction_status VARCHAR DEFAULT 'pending'")
        if "extraction_method" not in page_cols:
            migrations.append("ALTER TABLE pages ADD COLUMN extraction_method VARCHAR")
        if "index_status" not in page_cols:
            migrations.append("ALTER TABLE pages ADD COLUMN index_status VARCHAR DEFAULT 'pending'")
        if "index_method" not in page_cols:
            migrations.append("ALTER TABLE pages ADD COLUMN index_method VARCHAR")
        if "indexed_at" not in page_cols:
            migrations.append("ALTER TABLE pages ADD COLUMN indexed_at DATETIME")
        if "indexed_vector_count" not in page_cols:
            migrations.append("ALTER TABLE pages ADD COLUMN indexed_vector_count INTEGER DEFAULT 0")
        if "pinecone_document_id" not in page_cols:
            migrations.append("ALTER TABLE pages ADD COLUMN pinecone_document_id VARCHAR")
        if "source_document_id" not in page_cols:
            migrations.append("ALTER TABLE pages ADD COLUMN source_document_id VARCHAR")

    if "sections" in existing_tables:
        sec_cols = {c["name"] for c in inspector.get_columns("sections")}
        if "parent_section_id" not in sec_cols:
            migrations.append("ALTER TABLE sections ADD COLUMN parent_section_id VARCHAR REFERENCES sections(id)")
        if "depth" not in sec_cols:
            migrations.append("ALTER TABLE sections ADD COLUMN depth INTEGER DEFAULT 0")
        if "path_code" not in sec_cols:
            migrations.append("ALTER TABLE sections ADD COLUMN path_code VARCHAR DEFAULT ''")

    if "qc_questions" in existing_tables:
        qc_cols = {c["name"] for c in inspector.get_columns("qc_questions")}
        if "ai_answer" not in qc_cols:
            migrations.append("ALTER TABLE qc_questions ADD COLUMN ai_answer VARCHAR")
        if "ai_notes" not in qc_cols:
            migrations.append("ALTER TABLE qc_questions ADD COLUMN ai_notes TEXT DEFAULT ''")
        if "ai_confidence" not in qc_cols:
            migrations.append("ALTER TABLE qc_questions ADD COLUMN ai_confidence VARCHAR")
        if "ai_verified_at" not in qc_cols:
            migrations.append("ALTER TABLE qc_questions ADD COLUMN ai_verified_at DATETIME")
        if "target_section_ids" not in qc_cols:
            migrations.append("ALTER TABLE qc_questions ADD COLUMN target_section_ids JSON DEFAULT '[]'")

    if migrations:
        with engine.begin() as conn:
            for sql in migrations:
                conn.execute(text(sql))

    if "page_section_links" in set(inspect(engine).get_table_names()):
        with engine.begin() as conn:
            link_count = conn.execute(text("SELECT COUNT(*) FROM page_section_links")).scalar()
            if link_count == 0:
                conn.execute(text("""
                    INSERT INTO page_section_links (id, page_id, section_id, is_primary, order_in_section)
                    SELECT
                        lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-' || hex(randomblob(2)) || '-' || hex(randomblob(2)) || '-' || hex(randomblob(6))),
                        p.id,
                        p.section_id,
                        1,
                        COALESCE(p.order_in_section, 0)
                    FROM pages p
                    WHERE p.section_id IS NOT NULL
                      AND p.status = 'classified'
                """))


# ---------------------------------------------------------------------------
# 3. Auto-seeders – populate initial data on first run (idempotent)
# ---------------------------------------------------------------------------
def _run_seeders():
    """Seed templates, QC checklists, roles and permissions on first run."""
    if not settings.should_run_startup_seeders():
        logging.info("Skipping startup seeders for this environment.")
        return

    db = SessionLocal()
    try:
        _seed_doc_taxonomy(db)
        _seed_qc_template(db)
        _seed_roles_and_permissions(db)
        if settings.is_production() and not settings.ALLOW_PRODUCTION_ADMIN_SEED:
            logging.info("Skipping production admin-user seeding by default.")
        else:
            _seed_admin_user(db)
        _seed_form_templates(db)
    finally:
        db.close()


def _seed_doc_taxonomy(db):
    """Create the I-914 Document Taxonomy template if it doesn't exist."""
    existing = db.query(Template).filter(Template.name.contains("I-914 Document Taxonomy")).first()
    if existing:
        return

    from .seed_data.i914_doc_taxonomy import I914_DOC_TAXONOMY

    tpl = Template(name=I914_DOC_TAXONOMY["name"], description=I914_DOC_TAXONOMY["description"])
    db.add(tpl)
    db.flush()

    for dt_idx, dt_data in enumerate(I914_DOC_TAXONOMY["doc_types"]):
        dt_node = TemplateNode(
            template_id=tpl.id,
            name=dt_data["name"],
            code=dt_data["code"],
            node_type="doc_type",
            has_tables=dt_data.get("has_tables", False),
            order=dt_idx,
            depth=0,
        )
        db.add(dt_node)
        db.flush()

        for sec_idx, sec_data in enumerate(dt_data.get("sections", [])):
            sec_node = TemplateNode(
                template_id=tpl.id,
                parent_node_id=dt_node.id,
                name=sec_data["name"],
                code=sec_data["code"],
                node_type="section",
                order=sec_idx,
                depth=1,
            )
            db.add(sec_node)

    db.commit()


def _seed_qc_template(db):
    """Create or sync all bundled QC checklist templates."""
    qc_checklist.seed_i914_template(db)
    qc_checklist.seed_i914a_template(db)
    qc_checklist.seed_i765_template(db)
    qc_checklist.seed_i192_template(db)
    qc_checklist.seed_i360_template(db)
    qc_checklist.seed_g28_template(db)
    qc_checklist.seed_g1145_template(db)


def _seed_roles_and_permissions(db):
    """Ensure default roles and permissions exist (incremental / idempotent)."""

    PERMISSIONS = [
        "tab.pages",
        "tab.organize",
        "tab.qc_checklist",
        "tab.export",
        "admin.manage_roles",
    ]

    ROLES = {
        "admin": ["tab.pages", "tab.organize", "tab.qc_checklist", "tab.export", "admin.manage_roles"],
        "supervisor": ["tab.pages", "tab.organize", "tab.qc_checklist", "tab.export"],
        "casemanager": ["tab.pages", "tab.organize"],
    }

    perm_objects = {}
    for name in PERMISSIONS:
        perm = db.query(Permission).filter(Permission.name == name).first()
        if not perm:
            perm = Permission(name=name)
            db.add(perm)
            db.flush()
        perm_objects[name] = perm

    for role_name, perm_names in ROLES.items():
        role = db.query(Role).filter(Role.name == role_name).first()
        if not role:
            role = Role(name=role_name)
            db.add(role)
            db.flush()

        for perm_name in perm_names:
            exists = (
                db.query(RolePermission)
                .filter(RolePermission.role_id == role.id, RolePermission.permission_id == perm_objects[perm_name].id)
                .first()
            )
            if not exists:
                db.add(RolePermission(role_id=role.id, permission_id=perm_objects[perm_name].id))

    db.commit()


def _seed_admin_user(db):
    """Ensure all predefined admin users exist and have the 'admin' role.

    Idempotent: skips user creation if already present,
    skips role assignment if already linked.
    """
    admin_users = settings.ADMIN_SEED_USERS
    if not admin_users:
        logging.info("No ADMIN_SEED_USERS configured; skipping admin-user seeding.")
        return

    admin_role = db.query(Role).filter(Role.name == "admin").first()
    if not admin_role:
        return

    for admin_data in admin_users:
        admin_email = admin_data.email.strip()
        admin_name = admin_data.name.strip()
        if not admin_email or not admin_name:
            logging.warning("Skipping invalid ADMIN_SEED_USERS entry with missing email or name.")
            continue

        user = db.query(User).filter(User.email == admin_email).first()
        if not user:
            user = User(name=admin_name, email=admin_email)
            db.add(user)
            db.flush()

        already_assigned = (
            db.query(UserRole)
            .filter(UserRole.user_id == user.id, UserRole.role_id == admin_role.id)
            .first()
        )
        if not already_assigned:
            db.add(UserRole(user_id=user.id, role_id=admin_role.id))

    db.commit()


def _form_templates_seed():
    """Derive the form-template seeding list from the central form registry."""
    from .services.form_registry import FORM_REGISTRY

    return [
        {
            "name": spec.label,
            "form_type": spec.form_type,
            "filename": spec.pdf_filename,
            "description": spec.description,
        }
        for spec in FORM_REGISTRY.values()
    ]


_FORM_TEMPLATES_SEED = _form_templates_seed()


def _seed_form_templates(db):
    """Upload bundled PDF forms to S3 and register them in the DB (idempotent)."""
    from pathlib import Path
    from .services.paths import FORMS_PREFIX
    from .core.config import get_settings
    from .services.storage_service import S3StorageService

    seed_dir = Path(__file__).resolve().parent / "seed_data" / "forms"
    if not seed_dir.exists():
        logging.warning("seed_data/forms directory not found – skipping form template seeding")
        return

    try:
        s3 = S3StorageService(get_settings())
    except Exception as exc:
        logging.warning("Could not initialise S3 for form template seeding: %s", exc)
        return

    for tpl_data in _FORM_TEMPLATES_SEED:
        existing = db.query(FormTemplate).filter(FormTemplate.form_type == tpl_data["form_type"]).first()
        if existing:
            continue

        pdf_path = seed_dir / tpl_data["filename"]
        if not pdf_path.exists():
            logging.warning("PDF not found for seeding: %s", pdf_path)
            continue

        content = pdf_path.read_bytes()
        s3_key = f"{FORMS_PREFIX}/{tpl_data['filename']}"
        s3.upload_bytes(content, s3_key, "application/pdf")

        db.add(FormTemplate(
            name=tpl_data["name"],
            form_type=tpl_data["form_type"],
            description=tpl_data["description"],
            s3_key=s3_key,
            original_filename=tpl_data["filename"],
            file_size=len(content),
        ))

    db.commit()


# ---------------------------------------------------------------------------
# Execute startup sequence
# ---------------------------------------------------------------------------
_run_migrations()
_run_seeders()
with SessionLocal() as _startup_validation_db:
    run_startup_validations(_startup_validation_db, settings=settings)
recover_interrupted_processing_states()

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Document Categorizer & Extractor",
    description="Legal document indexing, classification, checklist tracking, and export.",
    version="0.1.0",
)

_allowed_origins = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Protected routers (require valid JWT)
app.include_router(cases.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(documents.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(pages.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(checklist.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(export.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(extraction.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(templates.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(qc_checklist.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(form_filling.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(form_templates.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(admin.router, prefix="/api", dependencies=[Depends(get_current_user), Depends(require_role("admin"))])
app.include_router(roles.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(permissions.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(teams.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(supervisor.router, prefix="/api", dependencies=[Depends(get_current_user)])

# Public router (login endpoint, no auth required)
app.include_router(auth.router, prefix="/api")


@app.get("/")
def root():
    return {"status": "ok", "service": "document-categorizer-api", "version": "0.1.0"}


@app.get("/api/health")
def health():
    return {"status": "ok", "startup_validation": LAST_STARTUP_VALIDATION_REPORT["status"]}


@app.get("/api/health/startup")
def startup_health():
    return LAST_STARTUP_VALIDATION_REPORT