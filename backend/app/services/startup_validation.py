"""Startup validations for production database and form-template readiness."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import logging
import os
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core.config import RuntimeSettings, get_runtime_settings, get_settings
from ..database import DB_CONNECTION
from ..models import FormTemplate, QuestionnaireAnswer
from ..schemas.questionnaire_json import QuestionnaireDocument
from .form_registry import FORM_REGISTRY
from .form_type_matcher import available_form_types, load_questionnaire_definition
from .questionnaire_service import FORM_TEMPLATES_DIR, QUESTIONNAIRES_DIR, normalize_form_type
from .storage_service import S3StorageService

log = logging.getLogger(__name__)


@dataclass
class StartupValidationIssue:
    severity: str
    code: str
    message: str
    details: dict[str, Any] | None = None


LAST_STARTUP_VALIDATION_REPORT: dict[str, Any] = {
    "status": "not_run",
    "mode": "off",
    "warnings": [],
    "errors": [],
}
_STARTUP_VALIDATION_EXCLUDED_FORM_TYPES: set[str] = {"i-914a"}


def _is_startup_validation_excluded_form_type(form_type: str | None) -> bool:
    return (normalize_form_type(form_type) or "") in _STARTUP_VALIDATION_EXCLUDED_FORM_TYPES


def _startup_validation_form_types() -> list[str]:
    return [
        form_type
        for form_type in available_form_types()
        if not _is_startup_validation_excluded_form_type(form_type)
    ]


def _read_questionnaire_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _collect_bundle_ids(bundle: dict[str, Any]) -> tuple[set[str], list[str]]:
    seen: set[str] = set()
    duplicates: set[str] = set()

    for page in bundle.get("pages", []) or []:
        for item in page.get("items", []) or []:
            item_id = str(item.get("id") or "").strip()
            if not item_id:
                continue

            if item_id in seen:
                duplicates.add(item_id)
            seen.add(item_id)

            field_entries = list(item.get("fields") or []) + list(item.get("details_fields") or [])
            if field_entries:
                for field in field_entries:
                    field_id = str(field.get("id") or "").strip()
                    if not field_id:
                        continue
                    canonical_id = f"{item_id}.{field_id}"
                    if canonical_id in seen:
                        duplicates.add(canonical_id)
                    seen.add(canonical_id)
                continue

    return seen, sorted(duplicates)


def _supported_question_ids_by_form() -> tuple[dict[str, set[str]], list[StartupValidationIssue]]:
    issues: list[StartupValidationIssue] = []
    supported: dict[str, set[str]] = {}

    shared_bundle = _read_questionnaire_json(QUESTIONNAIRES_DIR / "shared_client_questions.json")
    shared_ids, shared_duplicates = _collect_bundle_ids(shared_bundle)
    supported[""] = shared_ids
    if shared_duplicates:
        issues.append(
            StartupValidationIssue(
                severity="error",
                code="shared_questionnaire_duplicates",
                message="Shared questionnaire contains duplicate canonical question IDs.",
                details={"duplicate_ids": shared_duplicates},
            )
        )

    for form_type in _startup_validation_form_types():
        bundle = load_questionnaire_definition(form_type)
        form_ids, duplicates = _collect_bundle_ids(bundle)
        supported[form_type] = form_ids
        if duplicates:
            issues.append(
                StartupValidationIssue(
                    severity="error",
                    code="questionnaire_duplicates",
                    message=f"Questionnaire for {form_type} contains duplicate canonical question IDs.",
                    details={"form_type": form_type, "duplicate_ids": duplicates},
                )
            )

    return supported, issues


def _validate_environment(settings: RuntimeSettings) -> list[StartupValidationIssue]:
    issues: list[StartupValidationIssue] = []
    if not settings.is_production():
        return issues

    if DB_CONNECTION != "pgsql":
        issues.append(
            StartupValidationIssue(
                severity="error",
                code="production_sqlite",
                message="Production environment is configured with SQLite instead of PostgreSQL.",
                details={"db_connection": DB_CONNECTION},
            )
        )

    allowed_origins = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "").split(",") if origin.strip()]
    if not allowed_origins:
        issues.append(
            StartupValidationIssue(
                severity="error",
                code="missing_allowed_origins",
                message="ALLOWED_ORIGINS is empty for production.",
            )
        )

    if not os.getenv("VITE_BOS_URL", "").strip():
        issues.append(
            StartupValidationIssue(
                severity="warning",
                code="missing_vite_bos_url",
                message="VITE_BOS_URL is empty; the frontend fallback redirect may point to the wrong host.",
            )
        )

    if settings.should_run_startup_seeders():
        issues.append(
            StartupValidationIssue(
                severity="warning",
                code="production_seeders_enabled",
                message="Startup seeders are enabled in production.",
            )
        )

    if settings.ALLOW_PRODUCTION_ADMIN_SEED:
        issues.append(
            StartupValidationIssue(
                severity="warning",
                code="production_admin_seed_enabled",
                message="Production admin-user seeding is enabled.",
            )
        )

    if settings.should_run_legacy_migrations():
        issues.append(
            StartupValidationIssue(
                severity="warning",
                code="legacy_migrations_enabled",
                message="Legacy startup migrations are enabled in production.",
            )
        )

    return issues


def _validate_template_files() -> list[StartupValidationIssue]:
    issues: list[StartupValidationIssue] = []
    missing_forms = [
        form_type
        for form_type in _startup_validation_form_types()
        if not (FORM_TEMPLATES_DIR / f"{form_type}.pdf").exists()
    ]
    if missing_forms:
        issues.append(
            StartupValidationIssue(
                severity="error",
                code="missing_blank_pdf_templates",
                message="Some supported forms do not have a local blank PDF template.",
                details={"missing_form_types": missing_forms},
            )
        )
    return issues


# Phase 5 severity wiring for the registry/schema validations.
#
# - `_REGISTRY_ASSETS_VALIDATION_SEVERITY` is "error" because temporarily
#   disabled forms are excluded from these checks until their assets are ready.
# - `_QUESTIONNAIRE_SCHEMA_VALIDATION_SEVERITY` is "error" because every shipped
#   JSON validates cleanly today (see tests/test_questionnaire_schema.py); any
#   regression should brick startup so it gets caught immediately.
_REGISTRY_ASSETS_VALIDATION_SEVERITY: str = "error"
_QUESTIONNAIRE_SCHEMA_VALIDATION_SEVERITY: str = "error"


def _validate_form_registry_assets() -> list[StartupValidationIssue]:
    """Cross-validate every registered form: PDF, JSONs and QC module exist on disk.

    Emits one issue per missing asset. Severity is governed by
    `_REGISTRY_ASSETS_VALIDATION_SEVERITY`.
    """
    import importlib

    issues: list[StartupValidationIssue] = []
    missing: list[dict[str, Any]] = []

    for spec in FORM_REGISTRY.values():
        if _is_startup_validation_excluded_form_type(spec.form_type):
            continue

        if not spec.pdf_path().exists():
            missing.append({"form_type": spec.form_type, "asset": "pdf", "path": str(spec.pdf_path())})
        if not spec.client_json_path().exists():
            missing.append({"form_type": spec.form_type, "asset": "client_json", "path": str(spec.client_json_path())})
        attorney_path = spec.attorney_json_path()
        if attorney_path is not None and not attorney_path.exists():
            missing.append({"form_type": spec.form_type, "asset": "attorney_json", "path": str(attorney_path)})

        try:
            module = importlib.import_module(
                f"...seed_data.{spec.qc_template_module}", package=__name__
            )
            if not hasattr(module, spec.qc_template_symbol):
                missing.append(
                    {
                        "form_type": spec.form_type,
                        "asset": "qc_template_symbol",
                        "module": spec.qc_template_module,
                        "symbol": spec.qc_template_symbol,
                    }
                )
        except ImportError as exc:
            missing.append(
                {
                    "form_type": spec.form_type,
                    "asset": "qc_template_module",
                    "module": spec.qc_template_module,
                    "error": str(exc),
                }
            )

    if missing:
        issues.append(
            StartupValidationIssue(
                severity=_REGISTRY_ASSETS_VALIDATION_SEVERITY,
                code="form_registry_missing_assets",
                message="One or more forms declared in FORM_REGISTRY are missing assets on disk.",
                details={"missing": missing},
            )
        )

    return issues


def _validate_questionnaire_json_schemas() -> list[StartupValidationIssue]:
    """Validate every registered questionnaire JSON against the Pydantic schema.

    Severity is "error" because the data has been migrated to the canonical
    shape; any regression should fail startup so it's caught immediately.
    """
    issues: list[StartupValidationIssue] = []
    failures: list[dict[str, Any]] = []

    for spec in FORM_REGISTRY.values():
        if _is_startup_validation_excluded_form_type(spec.form_type):
            continue

        for asset_name, path in (
            ("client_json", spec.client_json_path()),
            ("attorney_json", spec.attorney_json_path()),
        ):
            if path is None or not path.exists():
                continue
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                QuestionnaireDocument.model_validate_pages(raw)
            except Exception as exc:
                failures.append(
                    {
                        "form_type": spec.form_type,
                        "asset": asset_name,
                        "path": str(path),
                        "error": str(exc).splitlines()[0][:500],
                    }
                )

    if failures:
        issues.append(
            StartupValidationIssue(
                severity=_QUESTIONNAIRE_SCHEMA_VALIDATION_SEVERITY,
                code="questionnaire_json_schema",
                message="Some questionnaire JSONs do not validate against the canonical Pydantic schema.",
                details={"failures": failures},
            )
        )

    return issues


def _validate_s3_form_templates(db: Session) -> list[StartupValidationIssue]:
    issues: list[StartupValidationIssue] = []
    rows = db.query(FormTemplate).order_by(FormTemplate.form_type).all()
    if not rows:
        issues.append(
            StartupValidationIssue(
                severity="warning",
                code="no_form_templates_registered",
                message="No form templates are registered in the database.",
            )
        )
        return issues

    try:
        storage = S3StorageService(get_settings())
    except Exception as exc:
        issues.append(
            StartupValidationIssue(
                severity="error",
                code="s3_initialization_failed",
                message="Could not initialize S3 validation for form templates.",
                details={"error": str(exc)},
            )
        )
        return issues

    missing_keys = [row.s3_key for row in rows if not storage.exists(row.s3_key)]
    if missing_keys:
        issues.append(
            StartupValidationIssue(
                severity="error",
                code="missing_s3_form_templates",
                message="Some DB form templates point to missing S3 objects.",
                details={"missing_s3_keys": missing_keys},
            )
        )
    return issues


def _validate_stored_questionnaire_answers(db: Session) -> list[StartupValidationIssue]:
    issues: list[StartupValidationIssue] = []
    supported_by_form, support_issues = _supported_question_ids_by_form()
    issues.extend(support_issues)

    grouped_rows = (
        db.query(
            QuestionnaireAnswer.form_type,
            QuestionnaireAnswer.question_id,
            func.count(QuestionnaireAnswer.id),
        )
        .group_by(QuestionnaireAnswer.form_type, QuestionnaireAnswer.question_id)
        .all()
    )

    unknown_entries: list[dict[str, Any]] = []
    for form_type, question_id, row_count in grouped_rows:
        normalized_form_type = normalize_form_type(form_type) or ""
        if _is_startup_validation_excluded_form_type(normalized_form_type):
            continue

        supported_ids = supported_by_form.get(normalized_form_type)
        if supported_ids is None:
            unknown_entries.append(
                {
                    "form_type": normalized_form_type or "(shared)",
                    "question_id": question_id,
                    "row_count": int(row_count or 0),
                    "reason": "unknown_form_type",
                }
            )
            continue
        if question_id not in supported_ids:
            unknown_entries.append(
                {
                    "form_type": normalized_form_type or "(shared)",
                    "question_id": question_id,
                    "row_count": int(row_count or 0),
                }
            )

    if unknown_entries:
        issues.append(
            StartupValidationIssue(
                severity="warning",
                code="unknown_questionnaire_answers",
                message="Stored questionnaire answers reference question IDs not present in the current JSON definitions.",
                details={"entries": unknown_entries[:50], "truncated": len(unknown_entries) > 50},
            )
        )

    return issues


def collect_startup_validation_report(db: Session, settings: RuntimeSettings | None = None) -> dict[str, Any]:
    resolved_settings = settings or get_runtime_settings()
    mode = resolved_settings.startup_validation_mode()
    if mode == "off":
        return {
            "status": "skipped",
            "mode": mode,
            "warnings": [],
            "errors": [],
        }

    issues: list[StartupValidationIssue] = []
    issues.extend(_validate_environment(resolved_settings))

    if resolved_settings.VALIDATE_TEMPLATE_FILES_ON_STARTUP:
        issues.extend(_validate_template_files())
        issues.extend(_validate_form_registry_assets())
        issues.extend(_validate_questionnaire_json_schemas())
    if resolved_settings.VALIDATE_QUESTIONNAIRE_ANSWERS_ON_STARTUP:
        issues.extend(_validate_stored_questionnaire_answers(db))
    if resolved_settings.VALIDATE_S3_ON_STARTUP:
        issues.extend(_validate_s3_form_templates(db))

    warnings = [asdict(issue) for issue in issues if issue.severity == "warning"]
    errors = [asdict(issue) for issue in issues if issue.severity == "error"]
    status = "error" if errors else "warning" if warnings else "ok"
    return {
        "status": status,
        "mode": mode,
        "warnings": warnings,
        "errors": errors,
    }


def run_startup_validations(db: Session, settings: RuntimeSettings | None = None) -> dict[str, Any]:
    report = collect_startup_validation_report(db, settings=settings)
    LAST_STARTUP_VALIDATION_REPORT.clear()
    LAST_STARTUP_VALIDATION_REPORT.update(report)

    for issue in report["warnings"]:
        log.warning("Startup validation warning [%s]: %s", issue["code"], issue["message"])
    for issue in report["errors"]:
        log.error("Startup validation error [%s]: %s", issue["code"], issue["message"])

    resolved_settings = settings or get_runtime_settings()
    if resolved_settings.startup_validation_is_strict() and report["status"] != "ok":
        raise RuntimeError("Startup validation failed in strict mode.")

    return report
