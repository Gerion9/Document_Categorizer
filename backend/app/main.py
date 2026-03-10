"""
FastAPI entry point for the Document Categorizer & Extractor backend.

Run with:
    cd backend
    uvicorn app.main:app --reload --port 8000
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from sqlalchemy import inspect, text

from .database import Base, engine
from .routers import cases, checklist, documents, export, pages, extraction, templates, qc_checklist


def _configure_logger(name: str, level: int) -> None:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    if not logger.handlers:
        logger.addHandler(logging.StreamHandler())
    logger.propagate = False


_configure_logger("qc_autopilot", logging.INFO)
_configure_logger("gemini_usage", logging.INFO)
_configure_logger("json_export", logging.INFO)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

# Create all tables on startup
Base.metadata.create_all(bind=engine)


def _run_migrations():
    """Add columns that may be missing from earlier schema versions."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    migrations: list[str] = []

    # DocumentType: has_tables
    if "document_types" in existing_tables:
        dt_cols = {c["name"] for c in inspector.get_columns("document_types")}
        if "has_tables" not in dt_cols:
            migrations.append("ALTER TABLE document_types ADD COLUMN has_tables BOOLEAN DEFAULT 0")

    # Page: ocr_text, extraction_status, extraction_method
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

    # Section: parent_section_id, depth, path_code (hierarchy)
    if "sections" in existing_tables:
        sec_cols = {c["name"] for c in inspector.get_columns("sections")}
        if "parent_section_id" not in sec_cols:
            migrations.append("ALTER TABLE sections ADD COLUMN parent_section_id VARCHAR REFERENCES sections(id)")
        if "depth" not in sec_cols:
            migrations.append("ALTER TABLE sections ADD COLUMN depth INTEGER DEFAULT 0")
        if "path_code" not in sec_cols:
            migrations.append("ALTER TABLE sections ADD COLUMN path_code VARCHAR DEFAULT ''")

    # QCQuestion: AI fields + target_section_ids
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

    # ── Backfill page_section_links from legacy page.section_id ──
    if "page_section_links" in set(inspect(engine).get_table_names()):
        with engine.begin() as conn:
            result = conn.execute(text(
                "SELECT COUNT(*) FROM page_section_links"
            ))
            link_count = result.scalar()
            if link_count == 0:
                # Migrate existing classified pages into the new links table
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


_run_migrations()

app = FastAPI(
    title="Document Categorizer & Extractor",
    description="Legal document indexing, classification, checklist tracking, and export.",
    version="0.1.0",
)

# CORS – allow the Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5174", "http://127.0.0.1:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve thumbnails and page images as static files
STORAGE_DIR = Path(__file__).resolve().parent.parent / "storage"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/storage", StaticFiles(directory=str(STORAGE_DIR)), name="storage")

# Register routers
app.include_router(cases.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(pages.router, prefix="/api")
app.include_router(checklist.router, prefix="/api")
app.include_router(export.router, prefix="/api")
app.include_router(extraction.router, prefix="/api")
app.include_router(templates.router, prefix="/api")
app.include_router(qc_checklist.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}

