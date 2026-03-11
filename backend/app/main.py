"""
FastAPI entry point for the Document Categorizer & Extractor backend.

Run with:
    cd backend
    uvicorn app.main:app --reload --port 8000
"""

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from sqlalchemy import inspect, text

from .database import Base, engine, DB_CONNECTION, SessionLocal
from .models import (
    Template, TemplateNode,
    QCChecklist, QCPart, QCQuestion,
    Role, Permission, RolePermission,
)
from .routers import cases, checklist, documents, export, pages, extraction, templates, qc_checklist, auth
from .routers.auth import get_current_user

# ---------------------------------------------------------------------------
# 1. Create all tables on startup
# ---------------------------------------------------------------------------
Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------------------------
# 2. Legacy migrations (only needed for SQLite databases created before
#    the current schema — PostgreSQL starts fresh via create_all)
# ---------------------------------------------------------------------------
def _run_migrations():
    """Add columns that may be missing from earlier SQLite schema versions."""
    if DB_CONNECTION != "sqlite":
        return

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    migrations: list[str] = []

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
    db = SessionLocal()
    try:
        _seed_doc_taxonomy(db)
        _seed_qc_template(db)
        _seed_roles_and_permissions(db)
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
    """Create the I-914 QC Checklist template if it doesn't exist."""
    existing = (
        db.query(QCChecklist)
        .filter(QCChecklist.is_template == True, QCChecklist.name.contains("I-914"))
        .first()
    )
    if existing:
        return

    from .seed_data.i914_template import I914_TEMPLATE

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


def _seed_roles_and_permissions(db):
    """Create default roles (admin, supervisor) and tab permissions."""
    if db.query(Role).first():
        return

    PERMISSIONS = [
        "tab.pages",
        "tab.organize",
        "tab.qc_checklist",
        "tab.export",
    ]

    perm_objects = {}
    for name in PERMISSIONS:
        p = Permission(name=name)
        db.add(p)
        db.flush()
        perm_objects[name] = p

    ROLES = {
        "admin": ["tab.pages", "tab.organize", "tab.qc_checklist", "tab.export"],
        "supervisor": ["tab.pages", "tab.organize"],
    }

    for role_name, perm_names in ROLES.items():
        role = Role(name=role_name)
        db.add(role)
        db.flush()

        for perm_name in perm_names:
            db.add(RolePermission(role_id=role.id, permission_id=perm_objects[perm_name].id))

    db.commit()


# ---------------------------------------------------------------------------
# Execute startup sequence
# ---------------------------------------------------------------------------
_run_migrations()
_run_seeders()

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Document Categorizer & Extractor",
    description="Legal document indexing, classification, checklist tracking, and export.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5174", "http://127.0.0.1:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STORAGE_DIR = Path(__file__).resolve().parent.parent / "storage"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/storage", StaticFiles(directory=str(STORAGE_DIR)), name="storage")

# Protected routers (require valid JWT)
app.include_router(cases.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(documents.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(pages.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(checklist.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(export.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(extraction.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(templates.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(qc_checklist.router, prefix="/api", dependencies=[Depends(get_current_user)])

# Public router (login endpoint, no auth required)
app.include_router(auth.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}
