"""Router – Global template library and apply-to-case workflow."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    AuditLog,
    Case,
    Checklist,
    ChecklistItem,
    ChecklistItemSectionTarget,
    DocumentType,
    Section,
    Template,
    TemplateChecklist,
    TemplateChecklistItem,
    TemplateItemNodeLink,
    TemplateNode,
)
from ..schemas import (
    ApplyTemplateRequest,
    TemplateChecklistCreate,
    TemplateChecklistItemCreate,
    TemplateChecklistItemOut,
    TemplateChecklistOut,
    TemplateCreate,
    TemplateNodeCreate,
    TemplateNodeOut,
    TemplateOut,
)

router = APIRouter(tags=["templates"])


# ── helpers ───────────────────────────────────────────────────────────────

def _node_out(node: TemplateNode, all_nodes: list[TemplateNode]) -> TemplateNodeOut:
    child_nodes = sorted(
        [n for n in all_nodes if n.parent_node_id == node.id],
        key=lambda n: n.order,
    )
    return TemplateNodeOut(
        id=node.id,
        template_id=node.template_id,
        parent_node_id=node.parent_node_id,
        name=node.name,
        code=node.code,
        node_type=node.node_type or "section",
        has_tables=node.has_tables or False,
        is_required=node.is_required if node.is_required is not None else True,
        depth=node.depth or 0,
        order=node.order or 0,
        children=[_node_out(c, all_nodes) for c in child_nodes],
        target_item_ids=[lnk.item_id for lnk in node.item_links],
    )


def _checklist_item_out(item: TemplateChecklistItem) -> TemplateChecklistItemOut:
    return TemplateChecklistItemOut(
        id=item.id,
        description=item.description,
        order=item.order or 0,
        target_node_ids=[lnk.node_id for lnk in item.node_links],
    )


def _checklist_out(cl: TemplateChecklist) -> TemplateChecklistOut:
    return TemplateChecklistOut(
        id=cl.id,
        name=cl.name,
        items=[_checklist_item_out(i) for i in cl.items],
    )


def _template_out(tpl: Template) -> TemplateOut:
    all_nodes = list(tpl.nodes)
    roots = sorted(
        [n for n in all_nodes if not n.parent_node_id],
        key=lambda n: n.order,
    )
    return TemplateOut(
        id=tpl.id,
        name=tpl.name,
        description=tpl.description or "",
        created_at=tpl.created_at,
        nodes=[_node_out(r, all_nodes) for r in roots],
        checklists=[_checklist_out(cl) for cl in tpl.checklists],
    )


def _compute_node_depth(node_id: str | None, all_nodes: list[TemplateNode]) -> int:
    if not node_id:
        return 0
    lookup = {n.id: n for n in all_nodes}
    depth = 0
    cur = node_id
    while cur:
        n = lookup.get(cur)
        if not n or not n.parent_node_id:
            break
        depth += 1
        cur = n.parent_node_id
    return depth


# ── Template CRUD ─────────────────────────────────────────────────────────

@router.get("/templates", response_model=list[TemplateOut])
def list_templates(db: Session = Depends(get_db)):
    return [_template_out(t) for t in db.query(Template).order_by(Template.created_at.desc()).all()]


@router.post("/templates", response_model=TemplateOut, status_code=201)
def create_template(body: TemplateCreate, db: Session = Depends(get_db)):
    tpl = Template(name=body.name, description=body.description)
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return _template_out(tpl)


@router.get("/templates/{tpl_id}", response_model=TemplateOut)
def get_template(tpl_id: str, db: Session = Depends(get_db)):
    tpl = db.query(Template).filter(Template.id == tpl_id).first()
    if not tpl:
        raise HTTPException(404, "Template not found")
    return _template_out(tpl)


@router.delete("/templates/{tpl_id}", status_code=204)
def delete_template(tpl_id: str, db: Session = Depends(get_db)):
    tpl = db.query(Template).filter(Template.id == tpl_id).first()
    if not tpl:
        raise HTTPException(404, "Template not found")
    db.delete(tpl)
    db.commit()


# ── Template Node CRUD ────────────────────────────────────────────────────

@router.post("/templates/{tpl_id}/nodes", response_model=TemplateNodeOut, status_code=201)
def create_template_node(tpl_id: str, body: TemplateNodeCreate, db: Session = Depends(get_db)):
    tpl = db.query(Template).filter(Template.id == tpl_id).first()
    if not tpl:
        raise HTTPException(404, "Template not found")
    node = TemplateNode(
        template_id=tpl_id,
        parent_node_id=body.parent_node_id,
        name=body.name,
        code=body.code,
        node_type=body.node_type,
        has_tables=body.has_tables,
        is_required=body.is_required,
        order=body.order,
    )
    db.add(node)
    db.flush()
    all_nodes = list(tpl.nodes) + [node]
    node.depth = _compute_node_depth(node.parent_node_id, all_nodes)
    db.commit()
    db.refresh(node)
    return _node_out(node, list(tpl.nodes))


@router.delete("/template-nodes/{node_id}", status_code=204)
def delete_template_node(node_id: str, db: Session = Depends(get_db)):
    node = db.query(TemplateNode).filter(TemplateNode.id == node_id).first()
    if not node:
        raise HTTPException(404)
    db.delete(node)
    db.commit()


# ── Template Checklist CRUD ───────────────────────────────────────────────

@router.post("/templates/{tpl_id}/checklists", response_model=TemplateChecklistOut, status_code=201)
def create_template_checklist(tpl_id: str, body: TemplateChecklistCreate, db: Session = Depends(get_db)):
    tpl = db.query(Template).filter(Template.id == tpl_id).first()
    if not tpl:
        raise HTTPException(404, "Template not found")
    cl = TemplateChecklist(template_id=tpl_id, name=body.name)
    db.add(cl)
    db.flush()
    for i_body in body.items:
        item = TemplateChecklistItem(checklist_id=cl.id, description=i_body.description, order=i_body.order)
        db.add(item)
        db.flush()
        for nid in i_body.target_node_ids:
            db.add(TemplateItemNodeLink(item_id=item.id, node_id=nid))
    db.commit()
    db.refresh(cl)
    return _checklist_out(cl)


@router.post("/template-checklists/{cl_id}/items", response_model=TemplateChecklistItemOut, status_code=201)
def add_template_checklist_item(cl_id: str, body: TemplateChecklistItemCreate, db: Session = Depends(get_db)):
    cl = db.query(TemplateChecklist).filter(TemplateChecklist.id == cl_id).first()
    if not cl:
        raise HTTPException(404)
    item = TemplateChecklistItem(checklist_id=cl_id, description=body.description, order=body.order)
    db.add(item)
    db.flush()
    for nid in body.target_node_ids:
        db.add(TemplateItemNodeLink(item_id=item.id, node_id=nid))
    db.commit()
    db.refresh(item)
    return _checklist_item_out(item)


# ── Apply template to case ────────────────────────────────────────────────

@router.post("/cases/{case_id}/apply-template", status_code=201)
def apply_template(case_id: str, body: ApplyTemplateRequest, db: Session = Depends(get_db)):
    """Instantiate a template into a case: create doc types, sections, checklists, items, and targets."""
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    tpl = db.query(Template).filter(Template.id == body.template_id).first()
    if not tpl:
        raise HTTPException(404, "Template not found")

    # Map template_node_id → created section/doctype id
    node_to_section: dict[str, str] = {}
    node_to_dt: dict[str, str] = {}

    # Build doc types and sections from template nodes
    all_nodes = list(tpl.nodes)
    root_nodes = sorted([n for n in all_nodes if not n.parent_node_id], key=lambda n: n.order)

    def _create_tree(nodes: list[TemplateNode], parent_section_id: str | None, dt_id: str, dt_code: str):
        for node in nodes:
            sec = Section(
                document_type_id=dt_id,
                parent_section_id=parent_section_id,
                name=node.name,
                code=node.code,
                order=node.order,
                is_required=node.is_required if node.is_required is not None else True,
                depth=node.depth or 0,
            )
            db.add(sec)
            db.flush()
            # Build path_code
            parts = []
            cur = sec
            while cur.parent_section_id:
                p = db.query(Section).filter(Section.id == cur.parent_section_id).first()
                if not p:
                    break
                parts.insert(0, p.code)
                cur = p
            parts.insert(0, dt_code)
            parts.append(sec.code)
            sec.path_code = ".".join(parts)

            node_to_section[node.id] = sec.id
            child_nodes = sorted([n for n in all_nodes if n.parent_node_id == node.id], key=lambda n: n.order)
            if child_nodes:
                _create_tree(child_nodes, sec.id, dt_id, dt_code)

    for rn in root_nodes:
        if rn.node_type == "doc_type":
            dt = DocumentType(
                case_id=case_id,
                name=rn.name,
                code=rn.code,
                order=rn.order,
                has_tables=rn.has_tables or False,
            )
            db.add(dt)
            db.flush()
            node_to_dt[rn.id] = dt.id
            # Create child sections under this doc type
            child_nodes = sorted([n for n in all_nodes if n.parent_node_id == rn.id], key=lambda n: n.order)
            _create_tree(child_nodes, None, dt.id, dt.code)
        else:
            # If root is a section, create a default doc type
            dt = DocumentType(case_id=case_id, name=rn.name, code=rn.code, order=rn.order)
            db.add(dt)
            db.flush()
            node_to_dt[rn.id] = dt.id
            sec = Section(document_type_id=dt.id, name=rn.name, code=rn.code, order=0, is_required=True, depth=0, path_code=f"{rn.code}.{rn.code}")
            db.add(sec)
            db.flush()
            node_to_section[rn.id] = sec.id

    # Create checklists, items, and targets
    for tcl in tpl.checklists:
        cl = Checklist(case_id=case_id, name=tcl.name)
        db.add(cl)
        db.flush()
        for titem in tcl.items:
            item = ChecklistItem(checklist_id=cl.id, description=titem.description, order=titem.order)
            db.add(item)
            db.flush()
            # Create targets from template links
            for lnk in titem.node_links:
                sec_id = node_to_section.get(lnk.node_id)
                if sec_id:
                    db.add(ChecklistItemSectionTarget(checklist_item_id=item.id, section_id=sec_id))

    db.add(AuditLog(
        case_id=case_id,
        action="applied_template",
        entity_type="template",
        entity_id=tpl.id,
        details={"template_name": tpl.name},
    ))
    db.commit()

    return {"ok": True, "template_name": tpl.name, "doc_types_created": len(node_to_dt), "sections_created": len(node_to_section)}


# ── Seed I-914 Document Taxonomy ──────────────────────────────────────────

@router.post("/templates/seed/i914-docs", status_code=201)
def seed_i914_doc_taxonomy(db: Session = Depends(get_db)):
    """Idempotent: create the I-914 document taxonomy template."""
    existing = db.query(Template).filter(Template.name.contains("I-914 Document Taxonomy")).first()
    if existing:
        return {"ok": True, "template_id": existing.id, "message": "Already exists"}

    from ..seed_data.i914_doc_taxonomy import I914_DOC_TAXONOMY

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
    return {"ok": True, "template_id": tpl.id, "doc_types": len(I914_DOC_TAXONOMY["doc_types"])}


@router.post("/cases/{case_id}/save-doc-template", status_code=201)
def save_case_doc_as_template(case_id: str, name: str = "Saved Document Template", db: Session = Depends(get_db)):
    """Clone the current case's document taxonomy (doc types + sections) into a reusable template."""
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")

    tpl = Template(name=name, description=f"From case: {case.name}")
    db.add(tpl)
    db.flush()

    doc_types = db.query(DocumentType).filter(DocumentType.case_id == case_id).order_by(DocumentType.order).all()

    for dt in doc_types:
        dt_node = TemplateNode(
            template_id=tpl.id, name=dt.name, code=dt.code,
            node_type="doc_type", has_tables=dt.has_tables or False,
            order=dt.order, depth=0,
        )
        db.add(dt_node)
        db.flush()

        all_secs = db.query(Section).filter(Section.document_type_id == dt.id).order_by(Section.order).all()
        sec_map: dict[str, str] = {}

        def _copy_secs(parent_sec_id, parent_node_id, depth):
            children = sorted([s for s in all_secs if s.parent_section_id == parent_sec_id], key=lambda s: s.order)
            for sec in children:
                node = TemplateNode(
                    template_id=tpl.id, parent_node_id=parent_node_id,
                    name=sec.name, code=sec.code, node_type="section",
                    is_required=sec.is_required, order=sec.order, depth=depth,
                )
                db.add(node)
                db.flush()
                sec_map[sec.id] = node.id
                _copy_secs(sec.id, node.id, depth + 1)

        _copy_secs(None, dt_node.id, 1)

    db.commit()
    return {"ok": True, "template_id": tpl.id, "template_name": tpl.name}

