"""I-914-specific helpers extracted from the main form filling service."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import re
from typing import Any

_FAMILY_NAME_BLOCK_RE = re.compile(
    r"(?is)"
    r"(?:^|\n|[\.\u2022\-])\s*"
    r"(?:"
    r"name(?:\s+of\s+(?:spouse|child|son|daughter))?"
    r"|nombre(?:\s+del?\s+(?:conyuge|c[oó]nyuge|espos[oa]|hij[oa]))?"
    r")\s*[:\-]?\s*"
    r"(?P<name>[A-Za-zÁÉÍÓÚÜÑáéíóúüñ' \-]{3,120})"
    r".{0,220}?"
    r"(?:"
    r"(?:date\s+of\s+birth|dob|fecha\s+de\s+nacimiento)"
    r")\s*[:\-]?\s*"
    r"(?P<dob>"
    r"\d{1,2}[\/\-.]\d{1,2}[\/\-.]\d{2,4}"
    r"|"
    r"\d{4}[\/\-.]\d{1,2}[\/\-.]\d{1,2}"
    r"|"
    r"\d{1,2}\s+[A-Za-zÁÉÍÓÚÜáéíóúü]{3,12}\s+\d{2,4}"
    r"|"
    r"[A-Za-zÁÉÍÓÚÜáéíóúü]{3,12}\s+\d{1,2},?\s+\d{2,4}"
    r")",
)
_SPOUSE_SECTION_RE = re.compile(
    r"(?i)(esta\s+casad[oa]\??|estado\s+civil|conyuge|c[oó]nyuge|esposo|esposa|spouse|married|matrimonio)"
)
_CHILDREN_SECTION_RE = re.compile(
    r"(?i)(tiene\s+hijos|informaci[oó]n\s+(?:de|sobre)\s+hij[oa]s|children|son\s+o\s+hija|dependientes)"
)
_PARENT_EXCLUSION_RE = re.compile(
    r"(?i)(padre|madre|mother|father|progenitor|applicant|aplicante|solicitante)"
)
_NAME_TOKEN_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ'\-]+")

_I914_PART9_FIELD_IDS = (
    "page_number",
    "part_number",
    "item_number",
    "additional_information",
)
# ``manually_edited`` is an opt-in boolean the UI can set to protect a user's
# narrative from being overwritten on regeneration. It is preserved alongside
# the textual fields but never counts toward "has content" checks.
_I914_PART9_META_FIELD_IDS = ("manually_edited",)
_I914_PART9_HEADER_PREFIX_RE = re.compile(
    r"^\s*Page\s+\S+\s*,\s*Part\s+\S+\s*,\s*Item\s+\S+\s*\.\s*",
    re.IGNORECASE,
)
_I914_SPOUSE_REQUIRED_FIELDS = (
    "spouse_family_name",
    "spouse_given_name",
    "spouse_date_of_birth",
    "spouse_country_of_birth",
    "spouse_residence_city",
    "spouse_residence_country",
)
_I914_CHILD_REQUIRED_FIELDS = (
    "family_name",
    "given_name",
    "date_of_birth",
    "country_of_birth",
    "current_city",
    "current_country",
)


def split_family_member_name(full_name: str, *, clean_text) -> dict[str, str]:
    cleaned = clean_text(full_name)
    if not cleaned:
        return {"given_name": "", "middle_name": "", "family_name": ""}
    tokens = _NAME_TOKEN_RE.findall(cleaned)
    if not tokens:
        return {"given_name": "", "middle_name": "", "family_name": ""}
    count = len(tokens)
    if count == 1:
        return {"given_name": tokens[0], "middle_name": "", "family_name": ""}
    if count == 2:
        return {"given_name": tokens[0], "middle_name": "", "family_name": tokens[1]}
    if count == 3:
        return {
            "given_name": tokens[0],
            "middle_name": "",
            "family_name": " ".join(tokens[1:]),
        }
    if count == 4:
        return {
            "given_name": tokens[0],
            "middle_name": tokens[1],
            "family_name": " ".join(tokens[2:]),
        }
    return {
        "given_name": tokens[0],
        "middle_name": tokens[1],
        "family_name": " ".join(tokens[2:]),
    }


def classify_family_block_role(prefix_text: str) -> str:
    if not prefix_text:
        return ""
    window = prefix_text[-800:]
    spouse_match = None
    children_match = None
    for match in _SPOUSE_SECTION_RE.finditer(window):
        spouse_match = match
    for match in _CHILDREN_SECTION_RE.finditer(window):
        children_match = match
    spouse_pos = spouse_match.end() if spouse_match else -1
    children_pos = children_match.end() if children_match else -1
    if spouse_pos < 0 and children_pos < 0:
        return ""
    return "spouse" if spouse_pos > children_pos else "child"


def parse_i914_family_roster(
    text: str,
    *,
    clean_text,
    normalize_date_text,
) -> dict[str, Any]:
    roster: dict[str, Any] = {"spouse": None, "children": []}
    if not text:
        return roster

    seen_children: set[tuple[str, str]] = set()
    for match in _FAMILY_NAME_BLOCK_RE.finditer(text):
        raw_name = clean_text(match.group("name"))
        raw_dob = clean_text(match.group("dob"))
        if not raw_name:
            continue
        if _PARENT_EXCLUSION_RE.search(raw_name):
            continue
        prefix = text[: match.start()]
        last_newline = prefix.rfind("\n")
        line_prefix = prefix[last_newline + 1 :] if last_newline != -1 else prefix
        if _PARENT_EXCLUSION_RE.search(line_prefix):
            continue
        role = classify_family_block_role(prefix)
        if not role:
            continue
        normalized_dob = normalize_date_text(raw_dob) or clean_text(raw_dob)
        tokens = _NAME_TOKEN_RE.findall(raw_name)
        if len(tokens) < 2:
            continue
        entry = {"name": raw_name, "dob": normalized_dob, "raw_dob": raw_dob}
        if role == "spouse":
            if roster["spouse"] is None:
                roster["spouse"] = entry
            continue
        key = (raw_name.lower(), normalized_dob)
        if key in seen_children:
            continue
        seen_children.add(key)
        roster["children"].append(entry)

    return roster


def collect_part5_evidence_text(
    targets: list[dict[str, Any]],
    evidence_by_id: Mapping[str, Any],
    *,
    clean_text,
) -> str:
    seen: set[str] = set()
    chunks: list[str] = []

    def add_chunk(raw: Any) -> None:
        if raw is None:
            return
        text = str(raw).strip()
        if not text:
            return
        key = " ".join(text.split())[:500]
        if key in seen:
            return
        seen.add(key)
        chunks.append(text)

    for target in targets:
        question_id = clean_text(target.get("question_id"))
        if not (question_id.startswith("p5_1") or question_id.startswith("p5_children")):
            continue
        field_id = clean_text(target.get("id"))
        bundle = evidence_by_id.get(field_id)
        if not isinstance(bundle, Mapping):
            continue
        add_chunk(bundle.get("text_context"))
        for match in bundle.get("matches", []) or []:
            if not isinstance(match, Mapping):
                continue
            add_chunk((match.get("metadata") or {}).get("text"))
        for item in bundle.get("evidence", []) or []:
            if isinstance(item, Mapping):
                add_chunk(item.get("text"))
    return "\n\n".join(chunks)


def apply_i914_family_roster_override(
    answers: dict[str, Any],
    targets: list[dict[str, Any]],
    evidence_by_id: Mapping[str, Any],
    *,
    clean_text,
    normalize_date_text,
    logger,
) -> None:
    if not answers:
        return

    combined_text = collect_part5_evidence_text(targets, evidence_by_id, clean_text=clean_text)
    if not combined_text:
        return

    roster = parse_i914_family_roster(
        combined_text,
        clean_text=clean_text,
        normalize_date_text=normalize_date_text,
    )
    spouse_entry = roster.get("spouse")
    children_entries: list[dict[str, Any]] = list(roster.get("children") or [])

    logger.info(
        "[FORM_FILL] i914 family roster parsed: spouse=%s children=%d",
        "yes" if spouse_entry else "no",
        len(children_entries),
    )

    if spouse_entry:
        spouse_value = answers.get("p5_1")
        spouse_row = dict(spouse_value) if isinstance(spouse_value, Mapping) else {}
        name_parts = split_family_member_name(spouse_entry.get("name", ""), clean_text=clean_text)
        updated = False
        mapping = {
            "spouse_family_name": name_parts["family_name"],
            "spouse_given_name": name_parts["given_name"],
            "spouse_middle_name": name_parts["middle_name"],
        }
        for field_id, new_value in mapping.items():
            if not new_value:
                continue
            if not clean_text(spouse_row.get(field_id)):
                spouse_row[field_id] = new_value
                updated = True
        if updated:
            answers["p5_1"] = spouse_row
            logger.info(
                "[FORM_FILL] i914 roster filled spouse names from evidence (family=%s given=%s middle=%s)",
                mapping["spouse_family_name"],
                mapping["spouse_given_name"],
                mapping["spouse_middle_name"],
            )

    if not children_entries:
        return

    child_rows_value = answers.get("p5_children")
    if not isinstance(child_rows_value, list):
        return

    available_entries = list(children_entries)
    for idx, row in enumerate(child_rows_value):
        if not isinstance(row, Mapping):
            continue
        slot_dob = normalize_date_text(row.get("date_of_birth")) or clean_text(row.get("date_of_birth"))
        matched_entry: dict[str, Any] | None = None
        if slot_dob:
            for candidate in available_entries:
                if candidate.get("dob") and candidate["dob"] == slot_dob:
                    matched_entry = candidate
                    break
        if matched_entry is None and len(available_entries) == 1 and len(child_rows_value) == 1:
            matched_entry = available_entries[0]
        if matched_entry is None:
            continue
        name_parts = split_family_member_name(matched_entry.get("name", ""), clean_text=clean_text)
        if not name_parts["given_name"] and not name_parts["family_name"]:
            continue
        new_row = dict(row)
        changed_fields: list[str] = []
        mapping = {
            "family_name": name_parts["family_name"],
            "given_name": name_parts["given_name"],
            "middle_name": name_parts["middle_name"],
        }
        for field_id, new_value in mapping.items():
            current_value = clean_text(new_row.get(field_id))
            if new_value and new_value != current_value:
                new_row[field_id] = new_value
                changed_fields.append(f"{field_id}: '{current_value}' -> '{new_value}'")
            elif not new_value and current_value and field_id == "middle_name":
                new_row[field_id] = ""
                changed_fields.append(f"{field_id}: '{current_value}' -> ''")
        if changed_fields:
            child_rows_value[idx] = new_row
            logger.info(
                "[FORM_FILL] i914 roster realigned child slot %d (dob=%s): %s",
                idx,
                slot_dob,
                "; ".join(changed_fields),
            )
        if matched_entry in available_entries:
            available_entries.remove(matched_entry)


def collect_i914_family_result_field_ids(
    targets: Sequence[Mapping[str, Any]],
    *,
    clean_text,
    infer_target_repeatable_slot_index,
) -> tuple[dict[str, str], dict[int, dict[str, str]]]:
    spouse_fields: dict[str, str] = {}
    children_slots: dict[int, dict[str, str]] = {}
    for target in targets:
        target_id = clean_text(target.get("id"))
        if not target_id:
            continue
        question_id = clean_text(target.get("questionnaire_item_id") or target.get("question_id"))
        answer_field_id = clean_text(target.get("questionnaire_field_id") or target.get("answer_field_id"))
        if not question_id or not answer_field_id:
            continue
        if question_id == "p5_1":
            if answer_field_id in {"spouse_family_name", "spouse_given_name", "spouse_middle_name"}:
                spouse_fields[answer_field_id] = target_id
            continue
        if question_id != "p5_children":
            continue
        slot_index = infer_target_repeatable_slot_index(target)
        if slot_index is None:
            continue
        children_slots.setdefault(slot_index, {})[answer_field_id] = target_id
    return spouse_fields, children_slots


def postprocess_i914_family_roster(
    targets: Sequence[Mapping[str, Any]],
    results_by_id: dict[str, dict[str, str]],
    evidence_by_id: Mapping[str, Any],
    *,
    clean_text,
    normalize_date_text,
    infer_target_repeatable_slot_index,
    set_result_value,
    logger,
) -> None:
    if not targets or not results_by_id:
        return

    combined_text = collect_part5_evidence_text(list(targets), evidence_by_id, clean_text=clean_text)
    if not combined_text:
        return

    roster = parse_i914_family_roster(
        combined_text,
        clean_text=clean_text,
        normalize_date_text=normalize_date_text,
    )
    spouse_entry = roster.get("spouse")
    children_entries = list(roster.get("children") or [])
    spouse_field_ids, children_slot_fields = collect_i914_family_result_field_ids(
        targets,
        clean_text=clean_text,
        infer_target_repeatable_slot_index=infer_target_repeatable_slot_index,
    )

    logger.info(
        "[FORM_FILL] i914 roster postprocess for extraction: spouse=%s children=%d child_slots=%d",
        "yes" if spouse_entry else "no",
        len(children_entries),
        len(children_slot_fields),
    )

    if spouse_entry and spouse_field_ids:
        spouse_name = split_family_member_name(spouse_entry.get("name", ""), clean_text=clean_text)
        spouse_mapping = {
            "spouse_family_name": spouse_name.get("family_name", ""),
            "spouse_given_name": spouse_name.get("given_name", ""),
            "spouse_middle_name": spouse_name.get("middle_name", ""),
        }
        spouse_justification = (
            "Part 5 roster override: spouse name aligned with deterministic family roster extracted from evidence."
        )
        spouse_changes: list[str] = []
        for field_id, target_id in spouse_field_ids.items():
            next_value = clean_text(spouse_mapping.get(field_id))
            current_value = clean_text((results_by_id.get(target_id) or {}).get("value"))
            if not next_value and field_id != "spouse_middle_name":
                continue
            if current_value == next_value:
                continue
            set_result_value(
                results_by_id,
                target_id,
                next_value,
                confidence="high",
                justification=spouse_justification,
            )
            spouse_changes.append(f"{field_id}: '{current_value}' -> '{next_value}'")
        if spouse_changes:
            logger.info(
                "[FORM_FILL] i914 roster corrected spouse fields: %s",
                "; ".join(spouse_changes),
            )

    if not children_entries or not children_slot_fields:
        return

    children_by_dob: dict[str, list[dict[str, Any]]] = {}
    for child in children_entries:
        child_dob = normalize_date_text(child.get("dob")) or clean_text(child.get("dob"))
        if not child_dob:
            continue
        children_by_dob.setdefault(child_dob, []).append(child)

    child_justification = (
        "Part 5 roster override: child name realigned to the correct slot using Date of Birth match."
    )
    for slot_index in sorted(children_slot_fields):
        field_map = children_slot_fields.get(slot_index) or {}
        dob_target_id = field_map.get("date_of_birth")
        if not dob_target_id:
            continue
        slot_dob = normalize_date_text((results_by_id.get(dob_target_id) or {}).get("value"))
        if not slot_dob:
            continue
        candidates = children_by_dob.get(slot_dob) or []
        if not candidates:
            continue
        selected_child = candidates.pop(0)
        child_name = split_family_member_name(selected_child.get("name", ""), clean_text=clean_text)
        updates = {
            "family_name": clean_text(child_name.get("family_name")),
            "given_name": clean_text(child_name.get("given_name")),
            "middle_name": clean_text(child_name.get("middle_name")),
        }
        slot_changes: list[str] = []
        for field_id in ("family_name", "given_name", "middle_name"):
            target_id = field_map.get(field_id)
            if not target_id:
                continue
            next_value = updates[field_id]
            current_value = clean_text((results_by_id.get(target_id) or {}).get("value"))
            if not next_value and field_id != "middle_name":
                continue
            if current_value == next_value:
                continue
            set_result_value(
                results_by_id,
                target_id,
                next_value,
                confidence="high",
                justification=child_justification,
            )
            slot_changes.append(f"{field_id}: '{current_value}' -> '{next_value}'")
        if slot_changes:
            logger.info(
                "[FORM_FILL] i914 roster corrected child slot %d (dob=%s): %s",
                slot_index,
                slot_dob,
                "; ".join(slot_changes),
            )


def strip_i914_part9_header(value: Any, *, clean_text) -> str:
    text = clean_text(value)
    if not text:
        return ""
    return _I914_PART9_HEADER_PREFIX_RE.sub("", text, count=1).strip()


def normalize_i914_part9_row(value: Any, *, clean_text) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {field_id: "" for field_id in _I914_PART9_FIELD_IDS}
    row: dict[str, Any] = {
        field_id: clean_text(value.get(field_id)) for field_id in _I914_PART9_FIELD_IDS
    }
    row["additional_information"] = strip_i914_part9_header(
        row["additional_information"],
        clean_text=clean_text,
    )
    manually_edited = value.get("manually_edited")
    if isinstance(manually_edited, bool):
        row["manually_edited"] = manually_edited
    elif isinstance(manually_edited, str):
        row["manually_edited"] = manually_edited.strip().lower() in {"true", "1", "yes"}
    else:
        row["manually_edited"] = bool(manually_edited)
    return row


def i914_part9_row_has_content(row: Mapping[str, Any], *, clean_text) -> bool:
    return any(clean_text(row.get(field_id)) for field_id in _I914_PART9_FIELD_IDS)


def i914_part9_row_key(row: Mapping[str, Any], *, clean_text) -> tuple[str, str, str]:
    return (
        clean_text(row.get("page_number")),
        clean_text(row.get("part_number")),
        clean_text(row.get("item_number")),
    )


def i914_mapping_has_any_value(value: Any, *, clean_text) -> bool:
    return isinstance(value, Mapping) and any(clean_text(entry) for entry in value.values())


def i914_child_row_is_complete(
    row: Mapping[str, Any],
    *,
    clean_text,
    normalize_country_value_for_pdf,
    normalize_us_state_code,
) -> bool:
    required_fields = list(_I914_CHILD_REQUIRED_FIELDS)
    current_country = normalize_country_value_for_pdf(row.get("current_country"))
    if current_country == "United States":
        required_fields.append("current_state")

    for field_id in required_fields:
        if field_id == "current_state":
            if not normalize_us_state_code(row.get(field_id)):
                return False
            continue
        if not clean_text(row.get(field_id)):
            return False
    return True


def apply_i914_family_answer_rules(
    answers: dict[str, Any],
    *,
    clean_text,
    clone_answer_value,
    normalize_country_value_for_pdf,
    normalize_us_state_code,
) -> dict[str, Any]:
    spouse_value = answers.get("p5_1")
    if i914_mapping_has_any_value(spouse_value, clean_text=clean_text):
        spouse_row = dict(spouse_value) if isinstance(spouse_value, Mapping) else {}
        if any(not clean_text(spouse_row.get(field_id)) for field_id in _I914_SPOUSE_REQUIRED_FIELDS):
            answers["p5_1"] = {}

    raw_children = answers.get("p5_children")
    if isinstance(raw_children, Mapping):
        child_rows: list[Any] = [raw_children]
    elif isinstance(raw_children, (list, tuple)):
        child_rows = list(raw_children)
    else:
        child_rows = []

    if child_rows:
        kept_rows: list[dict[str, Any]] = []
        for raw_row in child_rows:
            if not isinstance(raw_row, Mapping):
                continue
            cloned_row = {
                clean_text(key): clone_answer_value(value)
                for key, value in raw_row.items()
                if clean_text(key)
            }
            if not i914_mapping_has_any_value(cloned_row, clean_text=clean_text):
                continue
            if i914_child_row_is_complete(
                cloned_row,
                clean_text=clean_text,
                normalize_country_value_for_pdf=normalize_country_value_for_pdf,
                normalize_us_state_code=normalize_us_state_code,
            ):
                kept_rows.append(cloned_row)
        answers["p5_children"] = kept_rows

    return answers


def apply_i914_forced_answer_rules(
    answers: dict[str, Any],
    *,
    clean_text,
) -> dict[str, Any]:
    answers["p4_4a"] = "no"
    answers["p4_7"] = "no"

    applicant_statement = clean_text(answers.get("p6_1")).upper()
    if applicant_statement in {"", "B"}:
        answers["p6_1"] = "B"
        answers["p6_1.interpreter_language"] = "Spanish"

        interpreter_value = answers.get("p7_7")
        interpreter_group = dict(interpreter_value) if isinstance(interpreter_value, Mapping) else {}
        if not clean_text(interpreter_group.get("interpreter_fluent_language")):
            interpreter_group["interpreter_fluent_language"] = "Spanish"
        answers["p7_7"] = interpreter_group

    return answers
