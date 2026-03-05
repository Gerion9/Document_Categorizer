"""
Export service – generates:
  1. Consolidated PDF with hierarchical index
  2. QC Compliance report from QCChecklist data
"""

import io
import os
from pathlib import Path

import fitz  # PyMuPDF
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)

from sqlalchemy.orm import Session

from ..models import (
    Case,
    DocumentType,
    Page,
    PageSectionLink,
    PageStatus,
    QCAnswerStatus,
    QCChecklist,
    QCPart,
    QCQuestion,
    QCQuestionEvidence,
    Section,
)

STORAGE_DIR = Path(__file__).resolve().parent.parent.parent / "storage"
EXPORTS_DIR = STORAGE_DIR / "exports"
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

# ── Helpers ───────────────────────────────────────────────────────────────

def _collect_sections_recursive(db: Session, dt: DocumentType) -> list[dict]:
    """Walk the section tree depth-first, returning flat list with labels."""
    all_secs = (
        db.query(Section)
        .filter(Section.document_type_id == dt.id)
        .order_by(Section.order)
        .all()
    )

    def _walk(parent_id, depth):
        results = []
        children = sorted(
            [s for s in all_secs if s.parent_section_id == parent_id],
            key=lambda s: s.order,
        )
        for sec in children:
            label = sec.path_code or f"{dt.code}.{sec.code}"
            results.append({"section": sec, "label": f"{label} – {sec.name}", "depth": depth})
            results.extend(_walk(sec.id, depth + 1))
        return results

    return _walk(None, 0)


# ── Consolidated PDF ──────────────────────────────────────────────────────

def build_consolidated_pdf(db: Session, case_id: str) -> str:
    """Build consolidated PDF using PageSectionLink for primary pages only.
    Secondary links appear as text references in the TOC, not as duplicate images."""

    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise ValueError("Case not found")

    doc_types = (
        db.query(DocumentType)
        .filter(DocumentType.case_id == case_id)
        .order_by(DocumentType.order)
        .all()
    )

    toc_entries: list[dict] = []
    page_files: list[str] = []
    inserted_page_ids: set[str] = set()  # Track pages already inserted physically
    current_page = 2  # page 1 = TOC

    for dt in doc_types:
        sec_entries = _collect_sections_recursive(db, dt)
        for entry in sec_entries:
            sec = entry["section"]

            # Get PRIMARY linked pages for this section
            primary_links = (
                db.query(PageSectionLink)
                .filter(
                    PageSectionLink.section_id == sec.id,
                    PageSectionLink.is_primary == True,
                )
                .order_by(PageSectionLink.order_in_section)
                .all()
            )
            # Get SECONDARY linked pages for this section
            secondary_links = (
                db.query(PageSectionLink)
                .filter(
                    PageSectionLink.section_id == sec.id,
                    PageSectionLink.is_primary == False,
                )
                .order_by(PageSectionLink.order_in_section)
                .all()
            )

            # Fallback: if no links exist, use legacy page.section_id
            if not primary_links and not secondary_links:
                legacy_pages = (
                    db.query(Page)
                    .filter(Page.section_id == sec.id, Page.status == PageStatus.CLASSIFIED.value)
                    .order_by(Page.order_in_section)
                    .all()
                )
                if legacy_pages:
                    primary_links_pages = legacy_pages
                else:
                    continue
            else:
                primary_links_pages = []
                for lk in primary_links:
                    pg = db.query(Page).filter(Page.id == lk.page_id).first()
                    if pg:
                        primary_links_pages.append(pg)

            # Count actual images to insert (excluding already inserted)
            new_pages = [p for p in primary_links_pages if p.id not in inserted_page_ids]
            ref_count = len(secondary_links)

            # Build label suffix for references
            ref_labels = []
            for lk in secondary_links:
                pg = db.query(Page).filter(Page.id == lk.page_id).first()
                if pg:
                    # Find primary section of this page
                    prim = (
                        db.query(PageSectionLink)
                        .filter(PageSectionLink.page_id == pg.id, PageSectionLink.is_primary == True)
                        .first()
                    )
                    if prim:
                        prim_sec = db.query(Section).filter(Section.id == prim.section_id).first()
                        prim_label = prim_sec.path_code or prim_sec.name if prim_sec else "?"
                        ref_labels.append(f"p{pg.original_page_number} (→{prim_label})")

            label = entry["label"]
            if new_pages or ref_labels:
                toc_entries.append({
                    "label": label,
                    "start_page": current_page if new_pages else None,
                    "count": len(new_pages),
                    "depth": entry["depth"],
                    "refs": ref_labels,
                })

            for p in new_pages:
                abs_path = str(STORAGE_DIR / p.file_path)
                page_files.append(abs_path)
                inserted_page_ids.add(p.id)
                current_page += 1

    # Extras / unclassified
    extras = (
        db.query(Page)
        .filter(
            Page.case_id == case_id,
            Page.status.in_([PageStatus.UNCLASSIFIED.value, PageStatus.EXTRA.value]),
        )
        .order_by(Page.created_at)
        .all()
    )
    if extras:
        toc_entries.append({"label": "Extras / Sin clasificar", "start_page": current_page, "count": len(extras), "depth": 0, "refs": []})
        for p in extras:
            page_files.append(str(STORAGE_DIR / p.file_path))
            current_page += 1

    # Build TOC page
    toc_buffer = io.BytesIO()
    toc_doc = SimpleDocTemplate(toc_buffer, pagesize=letter, topMargin=0.75 * inch)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TOCTitle", parent=styles["Title"], fontSize=18, spaceAfter=20)
    ref_style = ParagraphStyle("RefNote", parent=styles["Normal"], fontSize=7, textColor=colors.HexColor("#6366f1"), leftIndent=24)

    elements = [
        Paragraph(f"Expediente: {case.name}", title_style),
        Paragraph("Indice de Contenidos", styles["Heading2"]),
        Spacer(1, 12),
    ]

    toc_data = [["Seccion", "Pag.", "Hojas"]]
    ref_notes: list[str] = []
    for e in toc_entries:
        indent_str = "    " * e.get("depth", 0)
        start = str(e["start_page"]) if e.get("start_page") else "ref."
        toc_data.append([f"{indent_str}{e['label']}", start, str(e["count"])])
        if e.get("refs"):
            ref_notes.append(f"{indent_str}  ↳ Referencias: {', '.join(e['refs'])}")

    if len(toc_data) > 1:
        t = Table(toc_data, colWidths=[4.8 * inch, 0.7 * inch, 0.7 * inch])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        elements.append(t)

    # Add reference notes below TOC if any
    if ref_notes:
        elements.append(Spacer(1, 10))
        elements.append(Paragraph("<b>Notas de referencia:</b>", styles["Normal"]))
        for note in ref_notes:
            elements.append(Paragraph(note, ref_style))

    toc_doc.build(elements)
    toc_buffer.seek(0)

    # Merge into final PDF
    final_pdf = fitz.open("pdf", toc_buffer.read())

    for img_path in page_files:
        if os.path.exists(img_path):
            img_doc = fitz.open()
            img = fitz.Pixmap(img_path)
            rect = fitz.Rect(0, 0, img.width, img.height)
            page = img_doc.new_page(width=img.width, height=img.height)
            page.insert_image(rect, pixmap=img)
            final_pdf.insert_pdf(img_doc)
            img_doc.close()

    # Bookmarks
    toc_list = []
    for e in toc_entries:
        if e.get("start_page"):
            toc_list.append([e.get("depth", 0) + 1, e["label"], e["start_page"]])
    if toc_list:
        final_pdf.set_toc(toc_list)

    out_filename = f"expediente_{case_id[:8]}.pdf"
    out_path = EXPORTS_DIR / out_filename
    final_pdf.save(str(out_path))
    final_pdf.close()

    return str(out_path.relative_to(STORAGE_DIR))


# ── QC Compliance Report ──────────────────────────────────────────────────

def build_qc_compliance_report(db: Session, case_id: str) -> str:
    """Generate a PDF compliance report from QC checklists with
    hierarchical parts, AI verification results, and evidence references."""

    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise ValueError("Case not found")

    qc_checklists = (
        db.query(QCChecklist)
        .filter(QCChecklist.case_id == case_id, QCChecklist.is_template == False)
        .all()
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.75 * inch, bottomMargin=0.5 * inch)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("RptTitle", parent=styles["Title"], fontSize=16, spaceAfter=14)
    part_style = ParagraphStyle("PartHead", parent=styles["Heading2"], fontSize=12, spaceAfter=6, spaceBefore=12)
    subpart_style = ParagraphStyle("SubpartHead", parent=styles["Heading3"], fontSize=10, spaceAfter=4, spaceBefore=8, leftIndent=12)

    ANSWER_LABELS = {
        "unanswered": "–",
        "yes": "Yes",
        "no": "No",
        "na": "N/A",
    }
    CONFIDENCE_LABELS = {
        "high": "Alta",
        "medium": "Media",
        "low": "Baja",
    }

    # Styles for wrapping text inside table cells
    cell_style = ParagraphStyle("CellStyle", parent=styles["Normal"], fontSize=7, leading=9)
    cell_small = ParagraphStyle("CellSmall", parent=styles["Normal"], fontSize=6.5, leading=8, textColor=colors.HexColor("#4b5563"))

    elements = [
        Paragraph(f"Reporte de Cumplimiento QC: {case.name}", title_style),
        Spacer(1, 8),
    ]

    for cl in qc_checklists:
        all_parts = list(cl.parts)

        # Count totals
        total_q = 0
        answered_q = 0
        yes_q = 0
        no_q = 0
        for p in all_parts:
            for q in p.questions:
                total_q += 1
                if q.answer and q.answer != QCAnswerStatus.UNANSWERED.value:
                    answered_q += 1
                if q.answer == QCAnswerStatus.YES.value:
                    yes_q += 1
                elif q.answer == QCAnswerStatus.NO.value:
                    no_q += 1

        pct = (answered_q / total_q * 100) if total_q else 0

        elements.append(Paragraph(f"<b>{cl.name}</b>", styles["Heading2"]))
        elements.append(Paragraph(
            f"Progreso: {answered_q}/{total_q} ({pct:.0f}%) &nbsp;|&nbsp; "
            f"<font color='green'>Yes: {yes_q}</font> &nbsp;|&nbsp; "
            f"<font color='red'>No: {no_q}</font>",
            styles["Normal"],
        ))
        elements.append(Spacer(1, 8))

        # Render parts recursively
        def _render_part(part: QCPart, depth: int):
            if depth == 0:
                elements.append(Paragraph(f"{part.code} – {part.name}", part_style))
            else:
                elements.append(Paragraph(f"{'&nbsp;' * depth * 4}{part.code} – {part.name}", subpart_style))

            if part.questions:
                header_style = ParagraphStyle("HeaderCell", parent=styles["Normal"], fontSize=7, leading=9, textColor=colors.white)
                data = [[
                    Paragraph("<b>Cod.</b>", header_style),
                    Paragraph("<b>Pregunta</b>", header_style),
                    Paragraph("<b>Resp.</b>", header_style),
                    Paragraph("<b>AI</b>", header_style),
                    Paragraph("<b>Donde verificar</b>", header_style),
                    Paragraph("<b>Correccion</b>", header_style),
                ]]
                for q in sorted(part.questions, key=lambda x: x.order):
                    ans_label = ANSWER_LABELS.get(q.answer or "unanswered", "–")
                    ai_label = ""
                    if q.ai_answer:
                        conf = CONFIDENCE_LABELS.get(q.ai_confidence or "", "")
                        ai_label = f"{ANSWER_LABELS.get(q.ai_answer, '?')} ({conf})"

                    # Evidence refs
                    ev_refs = []
                    for ev in q.evidence:
                        page = db.query(Page).filter(Page.id == ev.page_id).first()
                        if page and page.subindex:
                            ev_refs.append(f"{page.subindex}")
                        elif page:
                            ev_refs.append(f"p{page.original_page_number}")

                    desc_text = q.description or ""
                    if ev_refs:
                        desc_text += f"<br/><i>[Evidencia: {', '.join(ev_refs)}]</i>"
                    if q.ai_notes:
                        desc_text += f"<br/><font color='#7c3aed' size='6'>[AI: {q.ai_notes}]</font>"

                    ans_color = "#16a34a" if ans_label == "Yes" else "#dc2626" if ans_label == "No" else "#6b7280"

                    data.append([
                        Paragraph(q.code, cell_style),
                        Paragraph(desc_text, cell_style),
                        Paragraph(f"<font color='{ans_color}'><b>{ans_label}</b></font>", cell_style),
                        Paragraph(ai_label, cell_small),
                        Paragraph(q.where_to_verify or "", cell_small),
                        Paragraph(q.correction or "", cell_small),
                    ])

                col_widths = [0.45 * inch, 2.4 * inch, 0.4 * inch, 0.6 * inch, 1.2 * inch, 1.15 * inch]
                t = Table(data, colWidths=col_widths, repeatRows=1)
                t.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 3),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                    ("TOPPADDING", (0, 1), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 1), (-1, -1), 3),
                ]))
                elements.append(t)
                elements.append(Spacer(1, 6))

            # Child parts
            child_parts = sorted(
                [p for p in all_parts if p.parent_part_id == part.id],
                key=lambda p: p.order,
            )
            for child in child_parts:
                _render_part(child, depth + 1)

        root_parts = sorted(
            [p for p in all_parts if not p.parent_part_id],
            key=lambda p: p.order,
        )
        for rp in root_parts:
            _render_part(rp, 0)

        elements.append(PageBreak())

    # Remove trailing page break
    if elements and isinstance(elements[-1], PageBreak):
        elements.pop()

    doc.build(elements)
    buf.seek(0)

    out_filename = f"qc_reporte_{case_id[:8]}.pdf"
    out_path = EXPORTS_DIR / out_filename
    out_path.write_bytes(buf.read())

    return str(out_path.relative_to(STORAGE_DIR))


# ── Legacy compliance report (kept for backward compat) ───────────────────

def build_compliance_report(db: Session, case_id: str) -> str:
    """Generate a compliance report from old-style checklists."""
    from ..models import Checklist, ChecklistItem, ChecklistItemStatus, EvidenceLink

    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise ValueError("Case not found")

    checklists = db.query(Checklist).filter(Checklist.case_id == case_id).all()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.75 * inch)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("RptTitle", parent=styles["Title"], fontSize=18, spaceAfter=20)

    elements = [
        Paragraph(f"Reporte de Cumplimiento: {case.name}", title_style),
        Spacer(1, 12),
    ]

    STATUS_LABELS = {"pending": "Pendiente", "complete": "Completo", "incomplete": "Incompleto", "na": "N/A"}

    for cl in checklists:
        elements.append(Paragraph(f"Checklist: {cl.name}", styles["Heading2"]))
        elements.append(Spacer(1, 8))

        items = db.query(ChecklistItem).filter(ChecklistItem.checklist_id == cl.id).order_by(ChecklistItem.order).all()
        total = len(items)
        complete = sum(1 for i in items if i.status == ChecklistItemStatus.COMPLETE.value)
        pct = (complete / total * 100) if total else 0
        elements.append(Paragraph(f"Progreso: {complete}/{total} ({pct:.0f}%)", styles["Normal"]))
        elements.append(Spacer(1, 8))

        data = [["#", "Descripcion", "Estado", "Evidencia"]]
        for idx, item in enumerate(items, 1):
            evidence = db.query(EvidenceLink).filter(EvidenceLink.checklist_item_id == item.id).all()
            ev_labels = []
            for ev in evidence:
                page = db.query(Page).filter(Page.id == ev.page_id).first()
                if page and page.subindex:
                    ev_labels.append(f"{page.subindex} p{page.order_in_section or '?'}")
                elif page:
                    ev_labels.append(f"{page.original_filename} p{page.original_page_number}")
            ev_text = ", ".join(ev_labels) if ev_labels else "—"
            status_text = STATUS_LABELS.get(item.status, item.status)
            data.append([str(idx), item.description, status_text, ev_text])

        t = Table(data, colWidths=[0.4 * inch, 3.2 * inch, 1.1 * inch, 1.8 * inch])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 20))

    doc.build(elements)
    buf.seek(0)

    out_filename = f"reporte_{case_id[:8]}.pdf"
    out_path = EXPORTS_DIR / out_filename
    out_path.write_bytes(buf.read())

    return str(out_path.relative_to(STORAGE_DIR))
