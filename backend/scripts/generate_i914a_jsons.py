"""Generate the initial questionnaire JSONs for I-914A (Supplement A, derivative T).

This script writes `i914a_form_client.json` and `i914a_form_attorney.json` based
on the I-914A form structure (8 Parts) mirrored from the supervisor-approved
I-914A QC checklist (`app/seed_data/i914a_template.py`). The generated JSONs
are starter templates and follow the same conventions as the I-360 questionnaires:

- 8 Parts: Family Member For Whom Filing, General Info About Principal,
  Info About Derivative, Processing Information, Declaration, Interpreter,
  Preparer, Additional Information.
- Client questions cover Parts 1-3 + 5 + 8.
- Attorney questions cover the firm/admin sections (Part 4 processing, Part 6
  interpreter, Part 7 preparer).
- Semantic `id` (snake_case), compact `code` (matching the form).
- `where_to_verify` is populated; `instruction` is added per item.

Once a real `i-914a.pdf` is dropped into `app/seed_data/forms/` the field
metadata (Acroform names, choice values) should be cross-checked with
`scripts/inspect_pdf_fields.py` (TODO) and added to these JSONs.

Usage:
    python -m scripts.generate_i914a_jsons --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


_QUESTIONS_DIR = Path(__file__).resolve().parent.parent / "app" / "seed_data" / "questions"


def _client_pages() -> list[dict[str, Any]]:
    return [
        {
            "page": 1,
            "items": [
                {
                    "id": "p1_relationship",
                    "code": "1",
                    "label": "Family Member Relationship",
                    "form_text": "Select the relationship between you (the derivative family member) and the I-914 principal applicant.",
                    "section": "Part 1. Family Member For Whom You Are Filing",
                    "responsible_party": "client",
                    "type": "single_choice",
                    "options": [
                        {"label": "Spouse", "value": "spouse"},
                        {"label": "Child", "value": "child"},
                        {"label": "Parent", "value": "parent"},
                        {"label": "Unmarried Sibling Under 18 Years of Age", "value": "sibling_under_18"},
                    ],
                    "instruction": "Select exactly one box. Verify against the I-914 principal's family composition.",
                    "where_to_verify": "Intake; Bio Call; Birth Certificate(s); Marriage Certificate (if spouse)",
                },
                {
                    "id": "p1_present_danger_relationship",
                    "code": "2",
                    "label": "Present-Danger Relationship",
                    "form_text": "If filing as an adult or minor child who faces a present danger of retaliation, select the relationship to the principal family member.",
                    "section": "Part 1. Family Member For Whom You Are Filing",
                    "responsible_party": "client",
                    "type": "single_choice",
                    "optional": True,
                    "condition": "If you face a present danger of retaliation",
                    "options": [
                        {"label": "Child of my spouse", "value": "child_of_spouse"},
                        {"label": "Child of my child (my grandchild)", "value": "grandchild"},
                        {"label": "Child of my parent (my sibling over 18)", "value": "sibling_over_18"},
                        {"label": "Child of my unmarried sibling under 18 (my niece/nephew)", "value": "niece_nephew"},
                    ],
                    "instruction": "Only complete when the present-danger basis is asserted. Otherwise leave blank.",
                    "where_to_verify": "Intake; Bio Call; Declaration; Birth Certificate(s)",
                },
            ],
        },
        {
            "page": 2,
            "items": [
                {
                    "id": "p2_principal_full_name",
                    "code": "1",
                    "label": "Principal Applicant Full Legal Name",
                    "form_text": "Full legal name of the I-914 principal applicant (your qualifying family member).",
                    "section": "Part 2. General Information About You (the principal)",
                    "responsible_party": "client",
                    "type": "group",
                    "fields": [
                        {"id": "family_name", "label": "Family Name (Last Name)", "type": "text"},
                        {"id": "given_name", "label": "Given Name (First Name)", "type": "text"},
                        {"id": "middle_name", "label": "Middle Name", "type": "text", "optional": True},
                    ],
                    "instruction": "Must match the principal's I-914 Part 2 Item 1 exactly.",
                    "where_to_verify": "Form I-914; Birth Certificate; Passport; Bio Call",
                },
                {
                    "id": "p2_principal_date_of_birth",
                    "code": "2",
                    "label": "Principal Date of Birth",
                    "form_text": "Date of birth of the I-914 principal applicant.",
                    "section": "Part 2. General Information About You (the principal)",
                    "responsible_party": "client",
                    "type": "date",
                    "format": "Mmm DD YYYY",
                    "instruction": "Must match the principal's I-914 Part 2 DOB exactly.",
                    "where_to_verify": "Form I-914; Birth Certificate; Passport; Bio Call",
                },
                {
                    "id": "p2_principal_a_number",
                    "code": "3",
                    "label": "Principal A-Number",
                    "form_text": "Alien Registration Number of the I-914 principal applicant.",
                    "section": "Part 2. General Information About You (the principal)",
                    "responsible_party": "client",
                    "type": "text",
                    "optional": True,
                    "instruction": "Provide 7-9 digits without the leading 'A'. Leave blank if the principal has no A-Number yet.",
                    "where_to_verify": "USCIS Receipt; I-797; Form I-914; Bio Call",
                },
                {
                    "id": "p2_principal_i914_status",
                    "code": "4",
                    "label": "Principal I-914 Status",
                    "form_text": "Status of the principal's Form I-914, Application for T Nonimmigrant Status.",
                    "section": "Part 2. General Information About You (the principal)",
                    "responsible_party": "client",
                    "type": "single_choice",
                    "options": [
                        {"label": "Filing this Form I-914, Supplement A together", "value": "filed_together"},
                        {"label": "Pending", "value": "pending"},
                        {"label": "Approved", "value": "approved"},
                    ],
                    "instruction": "Select exactly one. If pending or approved, attach the latest USCIS receipt or approval notice.",
                    "where_to_verify": "USCIS Notice (I-797); USCIS Online Account; Case File; Intake",
                },
            ],
        },
        {
            "page": 3,
            "items": [
                {
                    "id": "p3_full_name",
                    "code": "1",
                    "label": "Your Full Legal Name (Derivative)",
                    "form_text": "Your full legal name (the derivative family member filing this Supplement A).",
                    "section": "Part 3. Information About Your Family Member (the derivative)",
                    "responsible_party": "client",
                    "type": "group",
                    "fields": [
                        {"id": "family_name", "label": "Family Name (Last Name)", "type": "text"},
                        {"id": "given_name", "label": "Given Name (First Name)", "type": "text"},
                        {"id": "middle_name", "label": "Middle Name", "type": "text", "optional": True},
                    ],
                    "instruction": "Match against the derivative's birth certificate or passport.",
                    "where_to_verify": "Birth Certificate; Passport; Bio Call; Other ID",
                },
                {
                    "id": "p3_other_names",
                    "code": "2",
                    "label": "Other Names Used",
                    "form_text": "List any other names you have used (aliases, maiden, nicknames).",
                    "section": "Part 3. Information About Your Family Member (the derivative)",
                    "responsible_party": "client",
                    "type": "repeatable_group",
                    "repeatable": True,
                    "optional": True,
                    "fields": [
                        {"id": "family_name", "label": "Family Name (Last Name)", "type": "text"},
                        {"id": "given_name", "label": "Given Name (First Name)", "type": "text"},
                        {"id": "middle_name", "label": "Middle Name", "type": "text", "optional": True},
                    ],
                    "instruction": "Add one entry per alias or maiden name. Leave the section blank if there are none.",
                    "where_to_verify": "Bio Call; Passport/ID; Previous Docs; FBI Records (if any)",
                },
                {
                    "id": "p3_physical_address",
                    "code": "3",
                    "label": "U.S. Physical or Intended Physical Address",
                    "form_text": "Your U.S. physical address or intended U.S. address (if currently abroad).",
                    "section": "Part 3. Information About Your Family Member (the derivative)",
                    "responsible_party": "client",
                    "type": "group",
                    "fields": [
                        {"id": "street", "label": "Street Number and Name", "type": "text"},
                        {"id": "unit_type", "label": "Unit Type", "type": "single_choice", "optional": True, "options": [
                            {"label": "Apt.", "value": "Apt."},
                            {"label": "Ste.", "value": "Ste."},
                            {"label": "Flr.", "value": "Flr."},
                        ]},
                        {"id": "unit_number", "label": "Unit Number", "type": "text", "optional": True},
                        {"id": "city", "label": "City or Town", "type": "text"},
                        {"id": "state", "label": "State", "type": "text"},
                        {"id": "zip_code", "label": "ZIP Code", "type": "text"},
                    ],
                    "instruction": "Use the actual residence. The safe mailing address goes in the next item.",
                    "where_to_verify": "Bio Call; Proof of Address; Google Maps; Intake",
                },
                {
                    "id": "p3_safe_mailing_address",
                    "code": "4",
                    "label": "Safe U.S. Mailing Address",
                    "form_text": "Safe mailing address (only if different from your physical address).",
                    "section": "Part 3. Information About Your Family Member (the derivative)",
                    "responsible_party": "client",
                    "type": "group",
                    "optional": True,
                    "fields": [
                        {"id": "in_care_of", "label": "In Care Of Name", "type": "text", "optional": True, "default_value": "Law Offices of Manuel E. Solis, PLLC"},
                        {"id": "street", "label": "Street Number and Name", "type": "text", "default_value": "P.O. Box 231704"},
                        {"id": "city", "label": "City or Town", "type": "text", "default_value": "Houston"},
                        {"id": "state", "label": "State", "type": "text", "default_value": "TX"},
                        {"id": "zip_code", "label": "ZIP Code", "type": "text", "default_value": "77223"},
                    ],
                    "instruction": "Use the firm's safe-mailing address by default unless the client specifies a different secure mailbox.",
                    "where_to_verify": "Firm Records; Bio Call; Intake",
                },
                {"id": "p3_a_number", "code": "5", "label": "A-Number", "section": "Part 3", "responsible_party": "client", "type": "text", "optional": True, "instruction": "7-9 digits. Leave blank if none.", "where_to_verify": "USCIS Receipt; I-797; Bio Call"},
                {"id": "p3_uscis_account", "code": "6", "label": "USCIS Online Account Number", "section": "Part 3", "responsible_party": "client", "type": "text", "optional": True, "instruction": "Exact value from myUSCIS.", "where_to_verify": "USCIS Online Account; Bio Call"},
                {"id": "p3_ssn", "code": "7", "label": "U.S. Social Security Number", "section": "Part 3", "responsible_party": "client", "type": "text", "optional": True, "instruction": "9 digits, no dashes.", "where_to_verify": "SSN Card; Tax Records; Bio Call"},
                {"id": "p3_sex", "code": "8", "label": "Sex", "section": "Part 3", "responsible_party": "client", "type": "single_choice", "options": [{"label": "Male", "value": "M"}, {"label": "Female", "value": "F"}], "instruction": "Use the value reported in the derivative's identity document.", "where_to_verify": "Passport; Birth Certificate; Bio Call"},
                {"id": "p3_marital_status", "code": "9", "label": "Marital Status", "section": "Part 3", "responsible_party": "client", "type": "single_choice", "options": [
                    {"label": "Single / Never Married", "value": "single"},
                    {"label": "Married", "value": "married"},
                    {"label": "Divorced", "value": "divorced"},
                    {"label": "Widowed", "value": "widowed"},
                    {"label": "Annulled", "value": "annulled"},
                ], "instruction": "Current status as of filing.", "where_to_verify": "Marriage Certificate; Divorce Decree; Bio Call"},
                {"id": "p3_prior_marriages", "code": "10", "label": "Prior Marriages", "section": "Part 3", "responsible_party": "client", "type": "repeatable_group", "repeatable": True, "optional": True, "condition": "If you have any prior marriages", "fields": [
                    {"id": "former_spouse_name", "label": "Name of Former Spouse", "type": "text"},
                    {"id": "date_ended", "label": "Date Marriage Ended", "type": "date", "format": "Mmm DD YYYY"},
                    {"id": "where_ended", "label": "Where Marriage Ended (City / State / Country)", "type": "text"},
                    {"id": "how_ended", "label": "How Marriage Ended", "type": "single_choice", "options": [
                        {"label": "Annulled", "value": "annulled"},
                        {"label": "Divorced", "value": "divorced"},
                        {"label": "Separated", "value": "separated"},
                        {"label": "Widowed", "value": "widowed"},
                    ]},
                ], "instruction": "Attach divorce decree or death certificate for each entry.", "where_to_verify": "Divorce Decree; Death Certificate; Marriage Certificate; Bio Call"},
                {"id": "p3_date_of_birth", "code": "11", "label": "Date of Birth", "section": "Part 3", "responsible_party": "client", "type": "date", "format": "Mmm DD YYYY", "instruction": "Match the birth certificate or passport exactly.", "where_to_verify": "Birth Certificate; Passport; Bio Call"},
                {"id": "p3_place_of_birth", "code": "12", "label": "Place of Birth (City / State / Country)", "section": "Part 3", "responsible_party": "client", "type": "group", "fields": [
                    {"id": "city", "label": "City or Town", "type": "text"},
                    {"id": "state", "label": "State or Province", "type": "text", "optional": True},
                    {"id": "country", "label": "Country", "type": "text"},
                ], "instruction": "Match the country name as it appears on the passport.", "where_to_verify": "Birth Certificate; Passport; Bio Call"},
                {"id": "p3_country_of_citizenship", "code": "13", "label": "Country of Citizenship or Nationality", "section": "Part 3", "responsible_party": "client", "type": "text", "instruction": "Country name; not a nationality adjective.", "where_to_verify": "Passport; Birth Certificate; Bio Call"},
                {"id": "p3_passport_number", "code": "14", "label": "Passport / Travel Document Number", "section": "Part 3", "responsible_party": "client", "type": "text", "optional": True, "instruction": "Exact number from the bio page.", "where_to_verify": "Passport; Travel Document; Bio Call"},
                {"id": "p3_passport_country", "code": "15", "label": "Country That Issued Passport / Travel Document", "section": "Part 3", "responsible_party": "client", "type": "text", "optional": True, "instruction": "Issuing country name.", "where_to_verify": "Passport; Travel Document; Bio Call"},
                {"id": "p3_passport_issue_date", "code": "16", "label": "Passport Issue Date", "section": "Part 3", "responsible_party": "client", "type": "date", "format": "Mmm DD YYYY", "optional": True, "instruction": "Do NOT confuse with expiration date.", "where_to_verify": "Passport; Bio Call"},
                {"id": "p3_passport_expiration", "code": "17", "label": "Passport Expiration Date", "section": "Part 3", "responsible_party": "client", "type": "date", "format": "Mmm DD YYYY", "optional": True, "instruction": "Do NOT confuse with issue date.", "where_to_verify": "Passport; Bio Call"},
                {"id": "p3_current_status", "code": "18", "label": "Current Immigration Status", "section": "Part 3", "responsible_party": "client", "type": "text", "instruction": "Status, not citizenship or country. E.g. 'B-2 overstay', 'No Status', 'Parole'.", "where_to_verify": "Form I-94; FOIA; Bio Call"},
                {"id": "p3_currently_in_us", "code": "19", "label": "Currently Living in the United States?", "section": "Part 3", "responsible_party": "client", "type": "yes_no", "options": [{"label": "Yes", "value": "yes"}, {"label": "No", "value": "no"}], "instruction": "Answer based on physical presence at the date of filing.", "where_to_verify": "Bio Call; Intake; Proof of Address; Travel Records"},
            ],
        },
        {
            "page": 5,
            "items": [
                {
                    "id": "p5_client_signature",
                    "code": "1",
                    "label": "Applicant Signature",
                    "form_text": "Signature of the derivative applicant on Part 5.",
                    "section": "Part 5. Statement, Contact Information, Declaration, Certification, and Signature of the Applicant Who Is Filing This Supplement A",
                    "responsible_party": "client",
                    "type": "signature",
                    "instruction": "The derivative signs in ink at the time of submission; leave the value blank.",
                    "where_to_verify": "Declaration; Signed Form",
                },
                {
                    "id": "p5_client_signature_date",
                    "code": "2",
                    "label": "Date of Signature",
                    "section": "Part 5. Statement, Contact Information, Declaration, Certification, and Signature of the Applicant Who Is Filing This Supplement A",
                    "responsible_party": "client",
                    "type": "date",
                    "format": "Mmm DD YYYY",
                    "instruction": "Date the form is signed (typically the day of filing).",
                    "where_to_verify": "Declaration; Signed Form",
                },
            ],
        },
        {
            "page": 8,
            "items": [
                {
                    "id": "p8_additional_information",
                    "code": "1-7",
                    "label": "Additional Information",
                    "form_text": "Use Part 8 to provide any additional information that did not fit elsewhere on this Supplement A.",
                    "section": "Part 8. Additional Information",
                    "responsible_party": "client",
                    "type": "repeatable_group",
                    "repeatable": True,
                    "optional": True,
                    "fields": [
                        {"id": "page_number", "label": "Page Number", "type": "text"},
                        {"id": "part_number", "label": "Part Number", "type": "text"},
                        {"id": "item_number", "label": "Item Number", "type": "text"},
                        {"id": "additional_text", "label": "Additional Information", "type": "textarea"},
                    ],
                    "instruction": "Include Page/Part/Item for every entry. Use factual paragraphs; never copy generic boilerplate.",
                    "where_to_verify": "Declaration; Affidavit; LEA Report; Intake",
                },
            ],
        },
    ]


def _attorney_pages() -> list[dict[str, Any]]:
    return [
        {
            "page": 4,
            "items": [
                {
                    "id": "p4_processing_yes_no_block",
                    "code": "1.A-1.S",
                    "label": "Part 4 Processing Yes/No",
                    "form_text": "Yes/No answers about criminal history, prostitution, terrorism, presence near harm, and immigration proceedings.",
                    "section": "Part 4. Processing Information",
                    "responsible_party": "attorney",
                    "type": "group",
                    "fields": [
                        {"id": "committed_crime_no_arrest", "label": "Committed a crime/offense without being arrested", "type": "yes_no"},
                        {"id": "arrested_or_detained", "label": "Arrested, cited, or detained by law enforcement", "type": "yes_no"},
                        {"id": "charged_with_crime", "label": "Charged with a crime or offense", "type": "yes_no"},
                        {"id": "convicted", "label": "Convicted of a crime or offense", "type": "yes_no"},
                        {"id": "diversion_program", "label": "Placed in alternative sentencing or diversion", "type": "yes_no"},
                        {"id": "probation_or_parole", "label": "Probation, parole, or suspended sentence", "type": "yes_no"},
                        {"id": "jail_or_prison", "label": "Time in jail or prison", "type": "yes_no"},
                        {"id": "prostitution", "label": "Engaged in or procured prostitution", "type": "yes_no"},
                        {"id": "smuggling", "label": "Knowingly aided/abetted alien smuggling", "type": "yes_no"},
                        {"id": "drugs", "label": "Drug trafficking or controlled substance involvement", "type": "yes_no"},
                        {"id": "terrorist_activities", "label": "Engaged in terrorist activities", "type": "yes_no"},
                        {"id": "espionage_security", "label": "Espionage or threats to U.S. security", "type": "yes_no"},
                        {"id": "torture_genocide", "label": "Participation in torture or genocide", "type": "yes_no"},
                        {"id": "extrajudicial_killings", "label": "Extrajudicial killings or political killings", "type": "yes_no"},
                        {"id": "child_soldiers", "label": "Recruitment or use of child soldiers", "type": "yes_no"},
                        {"id": "civil_penalties", "label": "Civil penalties (e.g., for immigration fraud)", "type": "yes_no"},
                        {"id": "fraud_misrepresentation", "label": "Fraud or material misrepresentation", "type": "yes_no"},
                        {"id": "removal_proceedings", "label": "Ever in removal/exclusion/deportation proceedings", "type": "yes_no"},
                    ],
                    "instruction": "Each Yes triggers a Part 8 addendum with factual detail (date, place, agency, outcome). Do NOT mark Yes without explicit evidence.",
                    "where_to_verify": "FBI Records; Court Disposition; LEA Report; Declaration; EOIR Portal",
                },
            ],
        },
        {
            "page": 6,
            "items": [
                {
                    "id": "p6_interpreter_used",
                    "code": "1",
                    "label": "Interpreter Used?",
                    "section": "Part 6. Interpreter's Contact Information, Certification, and Signature",
                    "responsible_party": "attorney",
                    "type": "yes_no",
                    "options": [{"label": "Yes", "value": "yes"}, {"label": "No", "value": "no"}],
                    "instruction": "Answer Yes only when an interpreter actually assisted the derivative.",
                    "where_to_verify": "Interpreter Certification; Intake",
                },
                {
                    "id": "p6_interpreter_full_name",
                    "code": "2",
                    "label": "Interpreter Full Name",
                    "section": "Part 6. Interpreter's Contact Information, Certification, and Signature",
                    "responsible_party": "attorney",
                    "type": "group",
                    "optional": True,
                    "condition": "If an interpreter was used",
                    "fields": [
                        {"id": "family_name", "label": "Family Name (Last Name)", "type": "text"},
                        {"id": "given_name", "label": "Given Name (First Name)", "type": "text"},
                    ],
                    "instruction": "Use the firm interpreter's name when applicable.",
                    "where_to_verify": "Interpreter Certification; Firm Records",
                },
                {
                    "id": "p6_interpreter_business",
                    "code": "3",
                    "label": "Interpreter Business or Organization",
                    "section": "Part 6. Interpreter's Contact Information, Certification, and Signature",
                    "responsible_party": "attorney",
                    "type": "text",
                    "optional": True,
                    "condition": "If an interpreter was used",
                    "default_value": "Law Offices of Manuel E. Solis, PLLC",
                    "instruction": "Use firm name when the interpreter is firm staff.",
                    "where_to_verify": "Firm Records",
                },
            ],
        },
        {
            "page": 7,
            "items": [
                {
                    "id": "p7_preparer_full_name",
                    "code": "1",
                    "label": "Preparer Full Name",
                    "section": "Part 7. Contact Information, Declaration, and Signature of the Person Preparing this Supplement A, if Other Than the Applicant",
                    "responsible_party": "attorney",
                    "type": "group",
                    "optional": True,
                    "fields": [
                        {"id": "family_name", "label": "Family Name (Last Name)", "type": "text"},
                        {"id": "given_name", "label": "Given Name (First Name)", "type": "text"},
                    ],
                    "instruction": "Name of the firm attorney or staff who prepared the form.",
                    "where_to_verify": "G-28; Firm Records",
                },
                {
                    "id": "p7_preparer_business",
                    "code": "2",
                    "label": "Preparer Business or Organization",
                    "section": "Part 7. Contact Information, Declaration, and Signature of the Person Preparing this Supplement A, if Other Than the Applicant",
                    "responsible_party": "attorney",
                    "type": "text",
                    "optional": True,
                    "default_value": "Law Offices of Manuel E. Solis, PLLC",
                    "instruction": "Use the firm name.",
                    "where_to_verify": "Firm Records; Letterhead",
                },
                {
                    "id": "p7_preparer_daytime_phone",
                    "code": "3",
                    "label": "Preparer Daytime Phone",
                    "section": "Part 7. Contact Information, Declaration, and Signature of the Person Preparing this Supplement A, if Other Than the Applicant",
                    "responsible_party": "attorney",
                    "type": "text",
                    "default_value": "7138442700",
                    "instruction": "Firm phone unless an alternate office line applies.",
                    "where_to_verify": "Firm Phone Directory",
                },
                {
                    "id": "p7_preparer_email",
                    "code": "4",
                    "label": "Preparer Email",
                    "section": "Part 7. Contact Information, Declaration, and Signature of the Person Preparing this Supplement A, if Other Than the Applicant",
                    "responsible_party": "attorney",
                    "type": "text",
                    "default_value": "uscism@manuelsolis.com",
                    "instruction": "Firm email; do not use a personal address.",
                    "where_to_verify": "Firm Records",
                },
            ],
        },
    ]


def write_jsons(apply: bool) -> int:
    client = _client_pages()
    attorney = _attorney_pages()
    client_path = _QUESTIONS_DIR / "i914a_form_client.json"
    attorney_path = _QUESTIONS_DIR / "i914a_form_attorney.json"

    if apply:
        client_path.write_text(json.dumps(client, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        attorney_path.write_text(json.dumps(attorney, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"[apply] wrote {client_path.name} ({len(client)} pages)")
        print(f"[apply] wrote {attorney_path.name} ({len(attorney)} pages)")
    else:
        print(f"[check] would write {client_path.name} ({len(client)} pages)")
        print(f"[check] would write {attorney_path.name} ({len(attorney)} pages)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not args.apply and not args.check:
        args.check = True
    return write_jsons(apply=args.apply)


if __name__ == "__main__":
    sys.exit(main())
