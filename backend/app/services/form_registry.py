"""Single source of truth for every USCIS form supported by the autofill pipeline.

Every other module that needs to enumerate forms or look up form-specific data
(PDF filename, questionnaire JSONs, QC template module, prompt rules module,
Document AI hints) must consult this registry instead of redeclaring the
information locally.

Wiring points that must derive from this registry (no parallel hardcoded lists):
- `app.services.questionnaire_service.FORM_TYPE_METADATA`
- `app.services.template_sync_service.FORM_TEMPLATES_SEED`
- `app.services.template_sync_service.QC_TEMPLATE_SPECS`
- `app.main._FORM_TEMPLATES_SEED`
- `app.services.form_type_matcher._load_qc_template_bundle`
- `app.services.form_detection_service.SUPPORTED_FORM_TYPES`
- `app.prompts.forms.<form>_rules.FormPromptSpec`

To add a new form:
1. Drop the PDF in `app/seed_data/forms/<form>.pdf`.
2. Drop questionnaire JSONs in `app/seed_data/questions/<compact>_form_client.json`
   and `<compact>_form_attorney.json` (or `attorney_json=None` if not applicable).
3. Create `app/seed_data/<compact>_template.py` with `<UPPER>_TEMPLATE`.
4. Create `app/prompts/forms/<compact>_rules.py` with `FORM_PROMPT_SPEC`.
5. Add the FormSpec entry below.
6. Restart; startup validation will fail fast if anything is missing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ..utils.text import clean_text as _clean_text


_BACKEND_APP_DIR = Path(__file__).resolve().parent.parent
_FORMS_DIR = _BACKEND_APP_DIR / "seed_data" / "forms"
_QUESTIONS_DIR = _BACKEND_APP_DIR / "seed_data" / "questions"


def normalize_form_type(form_type: str | None) -> str | None:
    """Canonical form-type normalization for the entire backend.

    Accepts strings like 'I-914', 'i914', 'form I-914A', 'g 1145', etc. and
    returns the canonical `letter-digits` form (e.g. 'i-914', 'i-914a', 'g-1145').
    Returns None when the input is empty or unrecognizable.

    Every callsite that needs to normalize a form_type MUST import this function
    instead of redefining it locally. Re-exported from `questionnaire_service`
    for legacy import paths.
    """
    cleaned = _clean_text(form_type)
    if not cleaned:
        return None
    compact = "".join(ch for ch in cleaned.lower() if ch.isalnum())
    if compact.startswith("form"):
        compact = compact[4:]
    if not compact:
        return None

    series_match = re.match(r"^([a-z])(\d+[a-z]?)$", compact)
    if series_match:
        return f"{series_match.group(1)}-{series_match.group(2)}"

    if compact.startswith("i"):
        suffix = compact[1:]
        return f"i-{suffix}" if suffix else None
    return compact


def compact_form_type(form_type: str | None) -> str:
    """Return the form code without separators (e.g. 'i-914a' -> 'i914a')."""
    return (normalize_form_type(form_type) or "").replace("-", "")


FormCategory = Literal["visa-t", "cgis"]


@dataclass(frozen=True)
class FormSpec:
    """Static metadata for a single supported USCIS form.

    All paths are relative to `app/seed_data/`. `attorney_json` is None when the
    form has no attorney-completed section (G-1145 is the only such case today).
    """

    form_type: str
    label: str
    description: str
    category: FormCategory
    pdf_filename: str
    client_json: str
    attorney_json: str | None
    qc_template_module: str
    qc_template_name: str
    qc_template_match_token: str
    qc_template_symbol: str
    prompt_module: str
    detection_keywords: tuple[str, ...] = ()
    doc_ai_hints: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def pdf_path(self) -> Path:
        return _FORMS_DIR / self.pdf_filename

    def client_json_path(self) -> Path:
        return _QUESTIONS_DIR / self.client_json

    def attorney_json_path(self) -> Path | None:
        if not self.attorney_json:
            return None
        return _QUESTIONS_DIR / self.attorney_json


FORM_REGISTRY: dict[str, FormSpec] = {
    "i-914": FormSpec(
        form_type="i-914",
        label="I-914",
        description="Application for T Nonimmigrant Status",
        category="visa-t",
        pdf_filename="i-914.pdf",
        client_json="i914_form_client.json",
        attorney_json="i914_form_attorney.json",
        qc_template_module="i914_template",
        qc_template_name="QC Checklist – I-914 (T-1)",
        qc_template_match_token="I-914",
        qc_template_symbol="I914_TEMPLATE",
        prompt_module="i914_rules",
        detection_keywords=(
            "form i-914",
            "i-914",
            "application for t nonimmigrant status",
            "t nonimmigrant status",
        ),
        doc_ai_hints={
            "p2_1": ("legal name", "full legal name", "applicant name", "family name", "given name"),
            "p2_4": ("safe mailing", "in care of", "c/o", "in care of name"),
            "p2_5": ("a#", "a number", "alien no", "alien registration", "alien number"),
            "p2_6": ("uscis online account", "myuscis", "online account number"),
            "p2_7": ("social security", "ssn", "ss#"),
            "p2_10": ("date of birth", "dob", "birth date"),
            "p2_passport": ("passport no", "passport number", "travel document number"),
            "p2_last_entry": ("date of last arrival", "last arrival", "i-94", "arrival departure record"),
        },
    ),
    # I-914A is temporarily disabled until `seed_data/forms/i-914a.pdf` exists.
    "i-765": FormSpec(
        form_type="i-765",
        label="I-765",
        description="Application for Employment Authorization",
        category="visa-t",
        pdf_filename="i-765.pdf",
        client_json="i765_form_client.json",
        attorney_json="i765_form_attorney.json",
        qc_template_module="i765_template",
        qc_template_name="QC Checklist - I-765",
        qc_template_match_token="I-765",
        qc_template_symbol="I765_TEMPLATE",
        prompt_module="i765_rules",
        detection_keywords=(
            "form i-765",
            "i-765",
            "application for employment authorization",
            "employment authorization document",
        ),
        doc_ai_hints={
            "p2_1": ("legal name", "full legal name", "family name", "given name"),
            "p2_8": ("a#", "a number", "alien no", "alien registration"),
            "p2_9": ("uscis online account", "online account number"),
            "p2_13": ("social security", "ssn"),
            "p2_16": ("date of birth", "dob"),
            "p2_17": ("i-94", "arrival departure", "arrival/departure"),
            "p2_18": ("passport no", "passport number"),
            "p2_22": ("date of last arrival", "last arrival", "arrival in the united states"),
            "p2_26": ("sevis", "n0"),
            "p2_27": ("eligibility category", "(c)(", "(a)("),
        },
    ),
    "i-192": FormSpec(
        form_type="i-192",
        label="I-192",
        description="Application for Advance Permission to Enter as Nonimmigrant",
        category="visa-t",
        pdf_filename="i-192.pdf",
        client_json="i192_form_client.json",
        attorney_json="i192_form_attorney.json",
        qc_template_module="i192_template",
        qc_template_name="QC Checklist - I-192",
        qc_template_match_token="I-192",
        qc_template_symbol="I192_TEMPLATE",
        prompt_module="i192_rules",
        detection_keywords=(
            "form i-192",
            "i-192",
            "advance permission to enter",
            "application for advance permission",
        ),
        doc_ai_hints={
            "p2_1": ("legal name", "full legal name", "family name", "given name"),
            "p2_3": ("a#", "a number", "alien no", "alien registration"),
            "p2_4": ("uscis online account", "online account number"),
            "p2_5": ("date of birth", "dob"),
            "p2_9": ("mailing address", "safe address", "safe mailing"),
            "p2_14": ("spouse legal name", "spouse name", "current spouse"),
            "p2_15": ("spouse a-number", "spouse alien number"),
            "p3_contact": ("daytime telephone", "email address", "contact information"),
        },
    ),
    "i-360": FormSpec(
        form_type="i-360",
        label="I-360",
        description="Petition for Amerasian, Widow(er), or Special Immigrant (SIJS)",
        category="cgis",
        pdf_filename="i-360.pdf",
        client_json="i360_form_client.json",
        attorney_json="i360_form_attorney.json",
        qc_template_module="i360_template",
        qc_template_name="QC Checklist - I-360 (SIJS)",
        qc_template_match_token="I-360",
        qc_template_symbol="I360_TEMPLATE",
        prompt_module="i360_rules",
        detection_keywords=(
            "form i-360",
            "i-360",
            "petition for amerasian",
            "special immigrant juvenile",
            "sijs",
            "sij",
        ),
        doc_ai_hints={
            "p1_petitioner_name": ("petitioner", "petitioner name", "petitioner's full legal name"),
            "p1_a_number": ("a#", "a number", "alien no", "alien registration"),
            "p1_uscis_account": ("uscis online account", "online account number"),
            "p1_ssn": ("social security", "ssn"),
            "p3_beneficiary_name": ("beneficiary", "beneficiary name", "beneficiary's full legal name"),
            "p3_date_of_birth": ("date of birth", "dob"),
            "p3_a_number": ("a#", "a number", "alien no"),
            "p3_ssn": ("social security", "ssn"),
            "p3_i94": ("i-94", "arrival/departure", "arrival departure record"),
            "p3_passport": ("passport no", "passport number"),
            "p8_sij_current_name": ("sij current legal name", "sij current name", "current legal name"),
            "p8_sij_name_on_court_order": ("name on the state court order", "name on court order"),
        },
    ),
    "g-28": FormSpec(
        form_type="g-28",
        label="G-28",
        description="Notice of Entry of Appearance as Attorney or Accredited Representative",
        category="visa-t",
        pdf_filename="g-28.pdf",
        client_json="g28_form_client.json",
        attorney_json="g28_form_attorney.json",
        qc_template_module="g28_template",
        qc_template_name="QC Checklist - G-28",
        qc_template_match_token="G-28",
        qc_template_symbol="G28_TEMPLATE",
        prompt_module="g28_rules",
        detection_keywords=(
            "form g-28",
            "g-28",
            "notice of entry of appearance as attorney",
            "accredited representative",
        ),
        doc_ai_hints={
            "p1_attorney_name": ("attorney name", "name of attorney", "accredited representative"),
            "p1_attorney_address": ("attorney address", "law firm address"),
            "p1_attorney_contact": ("attorney telephone", "attorney email", "attorney fax"),
            "p2_eligibility": ("bar number", "licensing authority", "state bar"),
            "p2_other": ("law firm", "recognized organization"),
            "p3_client_name": ("client full legal name", "client name", "applicant"),
            "p3_client_identity": ("uscis online account", "alien registration", "a number"),
            "p3_client_contact": ("client telephone", "client email"),
            "p3_client_mailing_address": ("client mailing address", "mailing address of client"),
        },
    ),
    "g-1145": FormSpec(
        form_type="g-1145",
        label="G-1145",
        description="E-Notification of Application/Petition Acceptance",
        category="visa-t",
        pdf_filename="g-1145.pdf",
        client_json="g1145_form_client.json",
        attorney_json="g1145_form_attorney.json",
        qc_template_module="g1145_template",
        qc_template_name="QC Checklist - G-1145",
        qc_template_match_token="G-1145",
        qc_template_symbol="G1145_TEMPLATE",
        prompt_module="g1145_rules",
        detection_keywords=(
            "form g-1145",
            "g-1145",
            "e-notification of application",
            "e-notification of petition acceptance",
        ),
        doc_ai_hints={
            "p1_applicant_name": ("applicant full name", "applicant name", "family name", "given name"),
            "p1_email": ("email address", "applicant email"),
            "p1_mobile": ("mobile phone", "text message", "cell phone"),
        },
    ),
}


def get_form_spec(form_type: str | None) -> FormSpec:
    """Return the FormSpec for `form_type` after normalization.

    Raises KeyError with a clear message when the form is not registered. The
    caller can catch this when the operation must degrade gracefully; the
    autofill pipeline relies on startup validation to ensure every registered
    form has its assets in place.
    """
    normalized = normalize_form_type(form_type) or ""
    spec = FORM_REGISTRY.get(normalized)
    if spec is None:
        raise KeyError(
            f"Unknown form_type '{form_type}' (normalized to '{normalized}'). "
            f"Registered forms: {sorted(FORM_REGISTRY)}"
        )
    return spec


def get_form_spec_or_none(form_type: str | None) -> FormSpec | None:
    try:
        return get_form_spec(form_type)
    except KeyError:
        return None


def supported_form_types() -> set[str]:
    return set(FORM_REGISTRY)


def iter_form_specs() -> list[FormSpec]:
    return list(FORM_REGISTRY.values())
