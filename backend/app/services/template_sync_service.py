"""Explicit synchronizers for form and QC templates."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..models import FormTemplate, QCChecklist, QCPart, QCQuestion
from .paths import FORMS_PREFIX
from .storage_service import S3StorageService

log = logging.getLogger(__name__)

def _build_form_templates_seed() -> list[dict[str, Any]]:
    from .form_registry import FORM_REGISTRY

    return [
        {
            "name": spec.label,
            "form_type": spec.form_type,
            "filename": spec.pdf_filename,
            "description": spec.description,
        }
        for spec in FORM_REGISTRY.values()
    ]


def _build_qc_template_specs() -> tuple[tuple[str, str, str, str, str], ...]:
    from .form_registry import FORM_REGISTRY

    return tuple(
        (
            spec.form_type,
            spec.qc_template_match_token,
            spec.qc_template_name,
            spec.qc_template_symbol,
            spec.qc_template_module,
        )
        for spec in FORM_REGISTRY.values()
    )


FORM_TEMPLATES_SEED = _build_form_templates_seed()
QC_TEMPLATE_SPECS = _build_qc_template_specs()


def _seed_forms_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "seed_data" / "forms"


def _load_qc_template_specs() -> list[dict[str, Any]]:
    """Dynamically import each form's QC template module declared in FORM_REGISTRY.

    No hardcoded list of imports here — adding a new form to the registry is
    enough to make it appear in the sync pipeline.
    """
    import importlib

    from .form_registry import FORM_REGISTRY

    specs: list[dict[str, Any]] = []
    for spec in FORM_REGISTRY.values():
        module = importlib.import_module(f"..seed_data.{spec.qc_template_module}", package=__package__)
        template = getattr(module, spec.qc_template_symbol)
        specs.append(
            {
                "form_type": spec.form_type,
                "match_token": spec.qc_template_match_token,
                "name": spec.qc_template_name,
                "template": template,
            }
        )
    return specs


def _find_existing_qc_template(db: Session, *, expected_name: str, match_token: str) -> QCChecklist | None:
    existing = (
        db.query(QCChecklist)
        .filter(
            QCChecklist.is_template == True,  # noqa: E712
            QCChecklist.case_id.is_(None),
            QCChecklist.name == expected_name,
        )
        .first()
    )
    if existing:
        return existing

    return (
        db.query(QCChecklist)
        .filter(
            QCChecklist.is_template == True,  # noqa: E712
            QCChecklist.case_id.is_(None),
            QCChecklist.name.contains(match_token),
        )
        .first()
    )


def _rebuild_qc_checklist_structure(db: Session, checklist: QCChecklist, template_data: dict[str, Any]) -> None:
    checklist.name = template_data["name"]
    checklist.description = template_data.get("description", "")
    checklist.is_template = True
    checklist.case_id = None

    for part in sorted(list(checklist.parts), key=lambda item: ((item.depth or 0), (item.order or 0)), reverse=True):
        db.delete(part)
    db.flush()

    def _create_parts(parts_data: list[dict[str, Any]], parent_id: str | None, depth: int) -> None:
        for idx, part_data in enumerate(parts_data):
            part = QCPart(
                checklist_id=checklist.id,
                parent_part_id=parent_id,
                name=part_data.get("name", ""),
                code=part_data.get("code", ""),
                order=idx,
                depth=depth,
            )
            db.add(part)
            db.flush()

            for question_idx, question_data in enumerate(part_data.get("questions", [])):
                db.add(
                    QCQuestion(
                        part_id=part.id,
                        code=question_data.get("code", ""),
                        description=question_data.get("description", ""),
                        where_to_verify=question_data.get("where_to_verify", ""),
                        order=question_idx,
                    )
                )

            if "subparts" in part_data:
                _create_parts(part_data["subparts"], part.id, depth + 1)

    _create_parts(template_data.get("parts", []), None, 0)


def sync_form_templates(
    db: Session,
    *,
    storage: S3StorageService | None = None,
    seed_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved_storage = storage or S3StorageService(get_settings())
    resolved_seed_items = seed_items or FORM_TEMPLATES_SEED
    seed_dir = _seed_forms_dir()
    results: list[dict[str, Any]] = []

    if not seed_dir.exists():
        raise FileNotFoundError(f"Missing forms seed directory: {seed_dir}")

    for seed_item in resolved_seed_items:
        pdf_path = seed_dir / seed_item["filename"]
        if not pdf_path.exists():
            raise FileNotFoundError(f"Missing bundled PDF for {seed_item['form_type']}: {pdf_path}")

        content = pdf_path.read_bytes()
        s3_key = f"{FORMS_PREFIX}/{seed_item['filename']}"
        resolved_storage.upload_bytes(content, s3_key, "application/pdf")

        existing = db.query(FormTemplate).filter(FormTemplate.form_type == seed_item["form_type"]).first()
        action = "updated"
        if not existing:
            existing = FormTemplate(form_type=seed_item["form_type"])
            db.add(existing)
            action = "created"

        existing.name = seed_item["name"]
        existing.description = seed_item["description"]
        existing.s3_key = s3_key
        existing.original_filename = seed_item["filename"]
        existing.file_size = len(content)

        results.append(
            {
                "form_type": seed_item["form_type"],
                "action": action,
                "s3_key": s3_key,
                "file_size": len(content),
            }
        )

    db.commit()
    return {"ok": True, "form_templates": results}


def sync_qc_templates(
    db: Session,
    *,
    specs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved_specs = specs or _load_qc_template_specs()
    results: list[dict[str, Any]] = []

    for spec in resolved_specs:
        existing = _find_existing_qc_template(
            db,
            expected_name=spec["template"]["name"],
            match_token=spec["match_token"],
        )
        action = "updated"
        if not existing:
            existing = QCChecklist(
                name=spec["template"]["name"],
                description=spec["template"].get("description", ""),
                is_template=True,
                case_id=None,
            )
            db.add(existing)
            db.flush()
            action = "created"

        _rebuild_qc_checklist_structure(db, existing, spec["template"])
        db.commit()
        db.refresh(existing)
        results.append(
            {
                "form_type": spec["form_type"],
                "action": action,
                "id": existing.id,
                "name": existing.name,
                "part_count": len(existing.parts),
            }
        )

    return {"ok": True, "qc_templates": results}


def sync_all_templates(db: Session, *, storage: S3StorageService | None = None) -> dict[str, Any]:
    form_summary = sync_form_templates(db, storage=storage)
    qc_summary = sync_qc_templates(db)
    return {
        "ok": True,
        "form_templates": form_summary["form_templates"],
        "qc_templates": qc_summary["qc_templates"],
    }
