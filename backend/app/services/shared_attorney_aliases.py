"""Map form-specific attorney questionnaire fields to shared attorney answer IDs."""

from __future__ import annotations

from typing import Any

from ..utils.text import clean_text as _clean_text

SHARED_ATTORNEY_PREFIX = "shared_attorney."

_INTERPRETER_IDENTITY_FIELDS = frozenset(
    {
        "interpreter_family_name",
        "interpreter_given_name",
        "interpreter_business_or_organization_name",
    }
)
_INTERPRETER_MAILING_FIELDS = frozenset(
    {
        "interpreter_street_number_name",
        "interpreter_unit_type",
        "interpreter_unit_number",
        "interpreter_city",
        "interpreter_state",
        "interpreter_zip_code",
        "interpreter_province",
        "interpreter_postal_code",
        "interpreter_country",
    }
)
_INTERPRETER_CONTACT_FIELDS = frozenset(
    {
        "interpreter_daytime_telephone_number",
        "interpreter_mobile_telephone_number",
        "interpreter_email_address",
    }
)
_INTERPRETER_SIGNATURE_FIELDS = frozenset(
    {
        "interpreter_fluent_language",
        "interpreter_signature",
        "interpreter_signature_date",
    }
)
_PREPARER_IDENTITY_FIELDS = frozenset(
    {
        "preparer_family_name",
        "preparer_given_name",
        "preparer_business_or_organization_name",
    }
)
_PREPARER_MAILING_FIELDS = frozenset(
    {
        "preparer_street_number_name",
        "preparer_unit_type",
        "preparer_unit_number",
        "preparer_city",
        "preparer_state",
        "preparer_zip_code",
        "preparer_province",
        "preparer_postal_code",
        "preparer_country",
    }
)
_PREPARER_CONTACT_FIELDS = frozenset(
    {
        "preparer_daytime_telephone_number",
        "preparer_mobile_telephone_number",
        "preparer_email_address",
    }
)
_PREPARER_SIGNATURE_FIELDS = frozenset(
    {
        "preparer_signature",
        "preparer_signature_date",
    }
)
_ADDITIONAL_INFO_ENTRY_FIELDS = frozenset(
    {
        "page_number",
        "part_number",
        "item_number",
        "additional_information",
        "additional_info",
    }
)


def _mentions_any(text: str, *terms: str) -> bool:
    return any(term in text for term in terms)


def _interpreter_group_for_field(field_id: str) -> str:
    if field_id in _INTERPRETER_IDENTITY_FIELDS:
        return "interpreter_identity"
    if field_id in _INTERPRETER_MAILING_FIELDS:
        return "interpreter_mailing"
    if field_id in _INTERPRETER_CONTACT_FIELDS:
        return "interpreter_contact"
    if field_id in _INTERPRETER_SIGNATURE_FIELDS:
        return "interpreter_signature"
    return "interpreter_identity"


def _preparer_group_for_field(field_id: str) -> str:
    if field_id in _PREPARER_IDENTITY_FIELDS:
        return "preparer_identity"
    if field_id in _PREPARER_MAILING_FIELDS:
        return "preparer_mailing"
    if field_id in _PREPARER_CONTACT_FIELDS:
        return "preparer_contact"
    if field_id in _PREPARER_SIGNATURE_FIELDS:
        return "preparer_signature"
    return "preparer_identity"


def _normalize_additional_info_field(field_id: str) -> str:
    if field_id == "additional_info":
        return "additional_information"
    if field_id.startswith("part9_"):
        return f"part6_{field_id[6:]}"
    return field_id


def shared_attorney_answer_aliases(
    item_id: str,
    field_id: str = "",
    *,
    form_text: str = "",
    section: str = "",
    item_type: str = "",
) -> list[str]:
    """Return shared attorney question IDs that mirror this form-specific target."""
    normalized_item_id = _clean_text(item_id).lower()
    normalized_field_id = _clean_text(field_id).lower()
    normalized_form_text = _clean_text(form_text).lower()
    normalized_section = _clean_text(section).lower()
    normalized_item_type = _clean_text(item_type).lower()
    combined = " | ".join(
        part
        for part in (
            normalized_item_id,
            normalized_field_id,
            normalized_form_text,
            normalized_section,
        )
        if part
    )

    aliases: list[str] = []

    def add(question_id: str, nested_field_id: str | None = None) -> None:
        alias = (
            f"{question_id}.{nested_field_id}"
            if nested_field_id
            else question_id
        )
        if alias not in aliases:
            aliases.append(alias)

    if normalized_item_id.startswith(SHARED_ATTORNEY_PREFIX.rstrip(".")):
        return aliases

    if normalized_item_id in {"p_attorney_info", "p_global_attorney_info"} or _mentions_any(
        combined,
        "attorney or accredited representative information",
    ):
        if normalized_field_id == "g28_attached":
            add("shared_attorney.info", "g28_attached")
        elif normalized_field_id in {"attorney_state_bar_number", "attorney_state_license_bar_number"}:
            add("shared_attorney.info", "state_bar_number")
        elif normalized_field_id == "attorney_uscis_online_account_number":
            add("shared_attorney.info", "uscis_online_account_number")
        elif not normalized_field_id:
            add("shared_attorney.info")
        return aliases

    if normalized_item_id == "p1_g28_attached":
        add("shared_attorney.info", "g28_attached")
        return aliases
    if normalized_item_id == "p1_attorney_state_bar":
        add("shared_attorney.info", "state_bar_number")
        return aliases
    if normalized_item_id == "p1_attorney_uscis_account":
        add("shared_attorney.info", "uscis_online_account_number")
        return aliases

    if normalized_field_id.startswith("part6_") or normalized_field_id.startswith("part9_"):
        add(
            "shared_attorney.additional_info_header",
            _normalize_additional_info_field(normalized_field_id),
        )
        return aliases

    if normalized_item_id in {"p6_header", "p9_header"} or _mentions_any(
        combined,
        "applicant identity for additional information",
    ):
        if normalized_field_id:
            add(
                "shared_attorney.additional_info_header",
                _normalize_additional_info_field(normalized_field_id),
            )
        else:
            add("shared_attorney.additional_info_header")
        return aliases

    if normalized_item_id in {"p6_entries", "p9_entries", "p14_additional_info", "p9_additional"} or _mentions_any(
        combined,
        "additional information entries",
        "additional information overflow",
    ):
        if normalized_field_id in _ADDITIONAL_INFO_ENTRY_FIELDS:
            add(
                "shared_attorney.additional_info_entries",
                _normalize_additional_info_field(normalized_field_id),
            )
        elif not normalized_field_id:
            add("shared_attorney.additional_info_entries")
        return aliases

    if normalized_item_id in {"p5_7", "p8_7"} or (
        normalized_item_type == "single_choice"
        and "preparer" in combined
        and "statement" in combined
    ):
        if normalized_field_id == "preparer_representation_scope":
            add("shared_attorney.preparer_statement", "preparer_representation_scope")
        else:
            add("shared_attorney.preparer_statement")
        return aliases

    if normalized_item_id == "p12_interpreter_family_name":
        add("shared_attorney.interpreter_identity", "interpreter_family_name")
        return aliases
    if normalized_item_id == "p12_interpreter_given_name":
        add("shared_attorney.interpreter_identity", "interpreter_given_name")
        return aliases
    if normalized_item_id == "p12_interpreter_business":
        add("shared_attorney.interpreter_identity", "interpreter_business_or_organization_name")
        return aliases
    if normalized_item_id == "p12_interpreter_language":
        add("shared_attorney.interpreter_signature", "interpreter_fluent_language")
        return aliases

    if normalized_item_id == "p13_preparer_family_name":
        add("shared_attorney.preparer_identity", "preparer_family_name")
        return aliases
    if normalized_item_id == "p13_preparer_given_name":
        add("shared_attorney.preparer_identity", "preparer_given_name")
        return aliases
    if normalized_item_id == "p13_preparer_business":
        add("shared_attorney.preparer_identity", "preparer_business_or_organization_name")
        return aliases
    if normalized_item_id == "p13_preparer_phone":
        add("shared_attorney.preparer_contact", "preparer_daytime_telephone_number")
        return aliases
    if normalized_item_id == "p13_preparer_mobile":
        add("shared_attorney.preparer_contact", "preparer_mobile_telephone_number")
        return aliases
    if normalized_item_id == "p13_preparer_email":
        add("shared_attorney.preparer_contact", "preparer_email_address")
        return aliases
    if normalized_item_id == "p13_preparer_signature_date":
        add("shared_attorney.preparer_signature", "preparer_signature_date")
        return aliases
    if normalized_item_id == "p13_preparer_address" and normalized_field_id:
        mapped = normalized_field_id
        if not mapped.startswith("preparer_"):
            mapped = f"preparer_{mapped}"
        add("shared_attorney.preparer_mailing", mapped)
        return aliases

    if normalized_field_id.startswith("interpreter_"):
        add(
            f"shared_attorney.{_interpreter_group_for_field(normalized_field_id)}",
            normalized_field_id,
        )
        return aliases

    if normalized_field_id.startswith("preparer_"):
        add(
            f"shared_attorney.{_preparer_group_for_field(normalized_field_id)}",
            normalized_field_id,
        )
        return aliases

    if "interpreter" in normalized_item_id:
        if normalized_field_id in {"family_name", "given_name"}:
            add("shared_attorney.interpreter_identity", f"interpreter_{normalized_field_id}")
        elif normalized_item_id == "p6_interpreter_business":
            add("shared_attorney.interpreter_identity", "interpreter_business_or_organization_name")
        return aliases

    if "preparer" in normalized_item_id:
        if normalized_field_id in {"family_name", "given_name"}:
            add("shared_attorney.preparer_identity", f"preparer_{normalized_field_id}")
        elif normalized_item_id == "p7_preparer_business":
            add("shared_attorney.preparer_identity", "preparer_business_or_organization_name")
        elif normalized_item_id == "p7_preparer_daytime_phone":
            add("shared_attorney.preparer_contact", "preparer_daytime_telephone_number")
        elif normalized_item_id == "p7_preparer_email":
            add("shared_attorney.preparer_contact", "preparer_email_address")
        return aliases

    return aliases


def shared_attorney_answer_aliases_for_item(item: dict[str, Any]) -> list[str]:
    return shared_attorney_answer_aliases(
        _clean_text(item.get("id")),
        form_text=_clean_text(item.get("form_text")),
        section=_clean_text(item.get("section")),
        item_type=_clean_text(item.get("type")),
    )


def shared_attorney_answer_aliases_for_field(
    item: dict[str, Any],
    field: dict[str, Any],
) -> list[str]:
    return shared_attorney_answer_aliases(
        _clean_text(item.get("id")),
        _clean_text(field.get("id")),
        form_text=_clean_text(item.get("form_text")),
        section=_clean_text(item.get("section")),
        item_type=_clean_text(item.get("type")),
    )


def shared_attorney_answer_candidates(
    target: dict[str, Any],
    occurrence_index: int,
) -> list[tuple[str, str | None, int | None]]:
    item_id = _clean_text(target.get("questionnaire_item_id"))
    field_id = _clean_text(target.get("questionnaire_field_id"))
    form_text = _clean_text(target.get("questionnaire_form_text"))
    section = _clean_text(target.get("questionnaire_section"))
    item_type = _clean_text(target.get("questionnaire_item_type"))

    aliases = shared_attorney_answer_aliases(
        item_id,
        field_id,
        form_text=form_text,
        section=section,
        item_type=item_type,
    )
    candidates: list[tuple[str, str | None, int | None]] = []
    for alias in aliases:
        if "." in alias:
            question_id, nested_field_id = alias.rsplit(".", 1)
            candidate = (question_id, nested_field_id, occurrence_index if nested_field_id else None)
        else:
            candidate = (alias, None, occurrence_index)
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates
