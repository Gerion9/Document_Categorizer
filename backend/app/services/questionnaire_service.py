"""Helpers for questionnaire definitions, answers, and blank PDF templates."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import datetime as _dt
import json
from pathlib import Path
from typing import Any

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import QuestionnaireAnswer
from ..utils.text import clean_text as _clean_text
from .form_type_matcher import available_form_types

VERIFICATION_EVIDENCE_MAX_CHARS = 1500
VERIFICATION_REASON_MAX_CHARS = 600
_ALLOWED_VERIFICATION_STATUSES = {"approved", "needs_review", "rejected"}


def _serialize_utc_datetime(value: Any) -> str | None:
    """Serialize a datetime as ISO-8601 with explicit UTC offset.

    Naive datetimes stored in the DB are assumed to be UTC (legacy rows).
    """
    if not isinstance(value, _dt.datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=_dt.timezone.utc)
    else:
        value = value.astimezone(_dt.timezone.utc)
    return value.isoformat()

SEED_DATA_DIR = Path(__file__).resolve().parent.parent / "seed_data"
QUESTIONNAIRES_DIR = SEED_DATA_DIR / "questions"
FORM_TEMPLATES_DIR = SEED_DATA_DIR / "forms"
SHARED_CLIENT_QUESTIONS_PATH = QUESTIONNAIRES_DIR / "shared_client_questions.json"

def _build_form_type_metadata() -> dict[str, dict[str, str]]:
    """Derive FORM_TYPE_METADATA from the central form registry."""
    from .form_registry import FORM_REGISTRY

    return {
        spec.form_type: {"label": spec.label, "description": spec.description}
        for spec in FORM_REGISTRY.values()
    }


FORM_TYPE_METADATA: dict[str, dict[str, str]] = _build_form_type_metadata()


from .form_registry import compact_form_type as _compact_form_type  # noqa: E402,F401  (re-export)
from .form_registry import normalize_form_type  # noqa: E402,F401  (re-export)


_SHARED_FORM_TYPE = ""


def _storage_form_type(form_type: str | None) -> str:
    return normalize_form_type(form_type) or _SHARED_FORM_TYPE


def _questionnaire_row_key(question_id: str, form_type: str | None) -> tuple[str, str]:
    return (_clean_text(question_id), _storage_form_type(form_type))


def _row_sort_key(row: QuestionnaireAnswer) -> tuple[Any, Any, str]:
    return (
        row.updated_at or row.created_at,
        row.created_at or row.updated_at,
        row.id,
    )


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Questionnaire file not found: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def _filter_pages_by_responsible_party(
    pages: list[dict[str, Any]],
    responsible_party: str,
) -> list[dict[str, Any]]:
    filtered_pages: list[dict[str, Any]] = []
    target_party = _clean_text(responsible_party).lower()

    for page in pages:
        items = [
            dict(item)
            for item in page.get("items", []) or []
            if _clean_text(item.get("responsible_party") or target_party).lower() == target_party
        ]
        if not items:
            continue
        filtered_pages.append(
            {
                "page": int(page.get("page") or 0),
                "items": items,
                "excluded_sections": list(page.get("excluded_sections", []) or []),
            }
        )

    return filtered_pages


def get_available_form_type_info() -> list[dict[str, str]]:
    infos: list[dict[str, str]] = []
    for form_type in available_form_types():
        metadata = FORM_TYPE_METADATA.get(form_type, {})
        infos.append(
            {
                "form_type": form_type,
                "label": metadata.get("label", form_type.upper()),
                "description": metadata.get("description", "Configured USCIS questionnaire"),
            }
        )
    return infos


def _extract_pages(data: Any) -> list[dict[str, Any]]:
    """Return the list of page dicts from a questionnaire JSON.

    Accepts both the legacy bare-list format `[{page: 1, ...}, ...]` and the
    wrapped format `{"pages": [{page: 1, ...}, ...]}`.
    """
    if isinstance(data, list):
        return data
    return list(data.get("pages", []) or [])


def get_shared_questions() -> list[dict[str, Any]]:
    return _extract_pages(_read_json_file(SHARED_CLIENT_QUESTIONS_PATH))


def get_form_client_questions(form_type: str) -> list[dict[str, Any]]:
    compact_form = _compact_form_type(form_type)
    if not compact_form:
        raise ValueError("Invalid form type.")
    path = QUESTIONNAIRES_DIR / f"{compact_form}_form_client.json"
    data = _read_json_file(path)
    return _filter_pages_by_responsible_party(_extract_pages(data), "client")


def get_form_attorney_questions(form_type: str) -> list[dict[str, Any]]:
    compact_form = _compact_form_type(form_type)
    if not compact_form:
        raise ValueError("Invalid form type.")
    path = QUESTIONNAIRES_DIR / f"{compact_form}_form_attorney.json"
    data = _read_json_file(path)
    return _filter_pages_by_responsible_party(_extract_pages(data), "attorney")


def _serialize_answer_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _deserialize_answer_value(raw_value: Any) -> Any:
    text = raw_value if isinstance(raw_value, str) else _clean_text(raw_value)
    if text == "":
        return ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _normalize_source(raw_source: Any, *, form_type: str | None) -> str:
    source = _clean_text(raw_source).lower()
    aliases = {
        "client": "form_client",
        "attorney": "form_attorney",
    }
    normalized = aliases.get(source, source)
    if normalized in {"shared", "form_client", "form_attorney"}:
        return normalized
    return "shared" if form_type is None else "form_client"


_SAVE_ANSWERS_MAX_RETRIES = 3


def save_answers(
    db: Session,
    case_id: str,
    answers: Iterable[Any],
) -> list[QuestionnaireAnswer]:
    normalized_entries: list[dict[str, Any]] = []
    question_ids: set[str] = set()

    for answer in answers:
        if hasattr(answer, "model_dump"):
            payload = answer.model_dump()
        elif isinstance(answer, Mapping):
            payload = dict(answer)
        else:
            continue

        question_id = _clean_text(payload.get("question_id"))
        if not question_id:
            continue

        normalized_form_type = normalize_form_type(payload.get("form_type"))
        source = _normalize_source(payload.get("source"), form_type=normalized_form_type)
        storage_form_type = _SHARED_FORM_TYPE if source == "shared" else normalized_form_type

        normalized_entry = {
            "question_id": question_id,
            "form_type": storage_form_type,
            "source": source,
            "value": _serialize_answer_value(payload.get("value")),
        }
        normalized_entries.append(normalized_entry)
        question_ids.add(question_id)

    return _save_answers_with_retry(db, case_id, normalized_entries, question_ids)


def _save_answers_with_retry(
    db: Session,
    case_id: str,
    normalized_entries: list[dict[str, Any]],
    question_ids: set[str],
) -> list[QuestionnaireAnswer]:
    previous_expire_on_commit = db.expire_on_commit
    db.expire_on_commit = False
    try:
        for attempt in range(_SAVE_ANSWERS_MAX_RETRIES):
            try:
                return _save_answers_attempt(
                    db, case_id, normalized_entries, question_ids,
                )
            except IntegrityError:
                db.rollback()
                if attempt >= _SAVE_ANSWERS_MAX_RETRIES - 1:
                    raise
    finally:
        db.expire_on_commit = previous_expire_on_commit


def _save_answers_attempt(
    db: Session,
    case_id: str,
    normalized_entries: list[dict[str, Any]],
    question_ids: set[str],
) -> list[QuestionnaireAnswer]:
    saved_rows: list[QuestionnaireAnswer] = []

    existing_rows_by_key: dict[tuple[str, str], list[QuestionnaireAnswer]] = {}
    if question_ids:
        existing_rows = (
            db.query(QuestionnaireAnswer)
            .filter(
                QuestionnaireAnswer.case_id == case_id,
                QuestionnaireAnswer.question_id.in_(sorted(question_ids)),
            )
            .order_by(QuestionnaireAnswer.updated_at.desc(), QuestionnaireAnswer.created_at.desc())
            .all()
        )
        for row in existing_rows:
            key = _questionnaire_row_key(row.question_id, row.form_type)
            existing_rows_by_key.setdefault(key, []).append(row)

    canonical_rows_by_key: dict[tuple[str, str], QuestionnaireAnswer] = {}
    for key, rows in existing_rows_by_key.items():
        rows.sort(
            key=lambda row: (
                1 if row.form_type == key[1] else 0,
                *_row_sort_key(row),
            ),
            reverse=True,
        )
        keeper = rows[0]
        if keeper.form_type != key[1]:
            keeper.form_type = key[1]
            db.add(keeper)
        canonical_rows_by_key[key] = keeper
        for duplicate in rows[1:]:
            db.delete(duplicate)

    for entry in normalized_entries:
        key = _questionnaire_row_key(entry["question_id"], entry["form_type"])
        row = canonical_rows_by_key.get(key)
        if row is None:
            row = QuestionnaireAnswer(
                case_id=case_id,
                question_id=entry["question_id"],
                value=entry["value"],
                source=entry["source"],
                form_type=entry["form_type"],
            )
            canonical_rows_by_key[key] = row
        else:
            row.value = entry["value"]
            row.source = entry["source"]
            row.form_type = entry["form_type"]

        db.add(row)
        saved_rows.append(row)

    db.commit()
    return saved_rows


def _has_meaningful_answer_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(
            isinstance(entry, dict) and any(
                isinstance(v, str) and v.strip() for v in entry.values()
            )
            for entry in value
        ) if value else False
    if isinstance(value, dict):
        return any(
            isinstance(v, str) and v.strip() for v in value.values()
        )
    return True


def get_answers(
    db: Session,
    case_id: str,
    form_type: str | None = None,
) -> dict[str, Any]:
    normalized_form_type = normalize_form_type(form_type)
    query = db.query(QuestionnaireAnswer).filter(QuestionnaireAnswer.case_id == case_id)

    if normalized_form_type:
        query = query.filter(
            or_(
                QuestionnaireAnswer.form_type == normalized_form_type,
                QuestionnaireAnswer.form_type == _SHARED_FORM_TYPE,
                QuestionnaireAnswer.form_type.is_(None),
            )
        )

    rows = query.order_by(QuestionnaireAnswer.updated_at.desc(), QuestionnaireAnswer.created_at.desc()).all()
    latest_rows_by_key: dict[tuple[str, str], QuestionnaireAnswer] = {}
    for row in rows:
        latest_rows_by_key.setdefault(_questionnaire_row_key(row.question_id, row.form_type), row)

    ordered_rows = sorted(
        latest_rows_by_key.values(),
        key=lambda row: (
            0 if _storage_form_type(row.form_type) == _SHARED_FORM_TYPE else 1,
            _clean_text(row.question_id),
            _clean_text(row.form_type),
        ),
    )

    answers: dict[str, Any] = {}
    for row in ordered_rows:
        value = _deserialize_answer_value(row.value)
        if row.question_id not in answers or _has_meaningful_answer_value(value):
            answers[row.question_id] = value
    return answers


def _normalize_verification_status(raw_status: Any) -> str | None:
    text = _clean_text(raw_status).lower()
    if text in _ALLOWED_VERIFICATION_STATUSES:
        return text
    return None


def _truncate(text: Any, max_chars: int) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""
    return cleaned[:max_chars]


def save_verifications(
    db: Session,
    case_id: str,
    *,
    verification_map: Mapping[str, Any] | None = None,
    form_verification_map: Mapping[str, Mapping[str, Any]] | None = None,
) -> int:
    """Persist verification metadata onto existing QuestionnaireAnswer rows.

    Each verification entry is stored against the row that matches
    (case_id, question_id, form_type). Rows that do not yet exist are
    created with an empty value so the verification badge survives reloads
    even before the user touches the field.

    Returns the number of rows updated/created.
    """

    entries: list[tuple[str | None, str, Mapping[str, Any]]] = []

    for question_id, payload in (verification_map or {}).items():
        if isinstance(payload, Mapping):
            entries.append((None, str(question_id), payload))

    for raw_form_type, fmap in (form_verification_map or {}).items():
        if not isinstance(fmap, Mapping):
            continue
        normalized_ft = normalize_form_type(raw_form_type)
        for question_id, payload in fmap.items():
            if isinstance(payload, Mapping):
                entries.append((normalized_ft, str(question_id), payload))

    if not entries:
        return 0

    seen_keys: set[tuple[str, str]] = set()
    deduped_entries: list[tuple[str, str, Mapping[str, Any]]] = []
    for raw_form_type, question_id, payload in entries:
        cleaned_qid = _clean_text(question_id)
        if not cleaned_qid:
            continue
        storage_ft = _storage_form_type(raw_form_type)
        key = (cleaned_qid, storage_ft)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped_entries.append((cleaned_qid, storage_ft, payload))

    if not deduped_entries:
        return 0

    try:
        question_ids = sorted({qid for qid, _, _ in deduped_entries})
        existing_rows = (
            db.query(QuestionnaireAnswer)
            .filter(
                QuestionnaireAnswer.case_id == case_id,
                QuestionnaireAnswer.question_id.in_(question_ids),
            )
            .all()
        )

        rows_by_key: dict[tuple[str, str], QuestionnaireAnswer] = {}
        for row in existing_rows:
            key = _questionnaire_row_key(row.question_id, row.form_type)
            rows_by_key.setdefault(key, row)

        now = _dt.datetime.now(_dt.timezone.utc)
        written = 0

        for question_id, storage_ft, payload in deduped_entries:
            status = _normalize_verification_status(payload.get("status"))
            if status is None:
                continue

            reason = _truncate(payload.get("reason"), VERIFICATION_REASON_MAX_CHARS)
            evidence = _truncate(payload.get("evidence"), VERIFICATION_EVIDENCE_MAX_CHARS)
            model = _clean_text(payload.get("model"))[:120]

            key = (question_id, storage_ft)
            row = rows_by_key.get(key)
            if row is None:
                row = QuestionnaireAnswer(
                    case_id=case_id,
                    question_id=question_id,
                    value="",
                    source="shared" if storage_ft == _SHARED_FORM_TYPE else "form_client",
                    form_type=storage_ft or None,
                )
                db.add(row)
                rows_by_key[key] = row

            row.verification_status = status
            row.verification_reason = reason or None
            row.verification_evidence = evidence or None
            row.verification_model = model or None
            row.verified_at = now
            written += 1

        if written:
            db.commit()
        return written
    except Exception:
        db.rollback()
        raise


def get_verifications(
    db: Session,
    case_id: str,
    form_type: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Return verification metadata as { question_id: {status, reason, evidence, ...} }."""
    normalized_form_type = normalize_form_type(form_type)
    query = db.query(QuestionnaireAnswer).filter(
        QuestionnaireAnswer.case_id == case_id,
        QuestionnaireAnswer.verification_status.isnot(None),
    )

    if normalized_form_type:
        query = query.filter(
            or_(
                QuestionnaireAnswer.form_type == normalized_form_type,
                QuestionnaireAnswer.form_type == _SHARED_FORM_TYPE,
                QuestionnaireAnswer.form_type.is_(None),
            )
        )

    rows = query.order_by(
        QuestionnaireAnswer.verified_at.desc().nullslast(),
        QuestionnaireAnswer.updated_at.desc(),
    ).all()

    verifications: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.question_id in verifications:
            continue
        verifications[row.question_id] = {
            "status": row.verification_status,
            "reason": row.verification_reason or "",
            "evidence": row.verification_evidence or "",
            "model": row.verification_model or "",
            "verified_at": _serialize_utc_datetime(row.verified_at),
        }
    return verifications


def get_form_template_path(form_type: str) -> Path:
    normalized_form_type = normalize_form_type(form_type)
    if not normalized_form_type:
        raise ValueError("Invalid form type.")

    path = FORM_TEMPLATES_DIR / f"{normalized_form_type}.pdf"
    if not path.exists():
        raise FileNotFoundError(
            "The blank PDF template for "
            f"{normalized_form_type.upper()} is missing. "
            f"Place it at backend/app/seed_data/forms/{normalized_form_type}.pdf."
        )
    return path
