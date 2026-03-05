"""
Predefined document taxonomy for I-914 cases.
Maps the 'Where to verify' sources from the QC Checklist to a reusable
document structure (DocumentTypes with nested Sections).
"""

I914_DOC_TAXONOMY = {
    "name": "I-914 Document Taxonomy",
    "description": "Standard document structure for I-914 (T-1) immigration cases",
    "doc_types": [
        {
            "name": "Internal Case Sources",
            "code": "INT",
            "has_tables": False,
            "sections": [
                {"name": "Bio Call", "code": "1"},
                {"name": "Intake", "code": "2"},
                {"name": "BOS", "code": "3"},
                {"name": "Previous Docs / Prior Filings", "code": "4"},
                {"name": "Contract", "code": "5"},
                {"name": "Strategy Memo", "code": "6"},
            ],
        },
        {
            "name": "Identity & Civil Documents",
            "code": "ID",
            "has_tables": False,
            "sections": [
                {"name": "Birth Certificate", "code": "1"},
                {"name": "Passport", "code": "2"},
                {"name": "Travel Document", "code": "3"},
                {"name": "IDs (other)", "code": "4"},
                {"name": "Marriage Certificate", "code": "5"},
                {"name": "Divorce Decrees", "code": "6"},
                {"name": "Annulment Orders", "code": "7"},
                {"name": "Death Certificates", "code": "8"},
            ],
        },
        {
            "name": "Immigration / History",
            "code": "IMM",
            "has_tables": True,
            "sections": [
                {"name": "Form I-94 / Arrival-Departure", "code": "1"},
                {"name": "USCIS Online Account", "code": "2"},
                {"name": "EOIR Portal Records", "code": "3"},
                {"name": "Work History", "code": "4"},
                {"name": "Country History", "code": "5"},
                {"name": "Personal History", "code": "6"},
            ],
        },
        {
            "name": "Trafficking / Eligibility Narrative",
            "code": "NAR",
            "has_tables": False,
            "sections": [
                {"name": "Declaration / Affidavit", "code": "1"},
                {"name": "Supplemental Statement", "code": "2"},
            ],
        },
        {
            "name": "Law Enforcement",
            "code": "LEA",
            "has_tables": True,
            "sections": [
                {"name": "LEA Report", "code": "1"},
                {"name": "Police Report", "code": "2"},
                {"name": "FBI Records", "code": "3"},
            ],
        },
        {
            "name": "Criminal / Court Records",
            "code": "CRT",
            "has_tables": True,
            "sections": [
                {"name": "Criminal Record", "code": "1"},
                {"name": "Court Disposition", "code": "2"},
                {"name": "Outcome / Sentencing", "code": "3"},
                {"name": "Official Documents (pardon/amnesty/clemency)", "code": "4"},
            ],
        },
        {
            "name": "FOIA Records",
            "code": "FOIA",
            "has_tables": True,
            "sections": [
                {"name": "FOIA (generic)", "code": "1"},
                {"name": "FOIA CBP", "code": "2"},
                {"name": "FOIA EOIR", "code": "3"},
                {"name": "FOIA ICE", "code": "4"},
                {"name": "FOIA USCIS", "code": "5"},
                {"name": "FOIA EOIR/ICE", "code": "6"},
            ],
        },
        {
            "name": "Medical Records",
            "code": "MED",
            "has_tables": False,
            "sections": [
                {"name": "Medical Records", "code": "1"},
                {"name": "Medical Evaluation", "code": "2"},
            ],
        },
        {
            "name": "Family / Derivative Supporting Docs",
            "code": "FAM",
            "has_tables": False,
            "sections": [
                {"name": "Adoption Records / Decrees", "code": "1"},
                {"name": "Court Orders", "code": "2"},
                {"name": "Court Records (Custody)", "code": "3"},
                {"name": "Civil Records", "code": "4"},
                {"name": "Contact Records", "code": "5"},
            ],
        },
        {
            "name": "Filing / Packet Components",
            "code": "PKT",
            "has_tables": True,
            "sections": [
                {"name": "Original I-914", "code": "1"},
                {"name": "I-914A Drafts", "code": "2"},
                {"name": "Form I-765 (EAD)", "code": "3"},
                {"name": "G-28 (if applicable)", "code": "4"},
                {"name": "Filing Checklist", "code": "5"},
                {"name": "Case File", "code": "6"},
                {"name": "Part 9 Entries", "code": "7"},
                {"name": "Attachments / Additional Sheets", "code": "8"},
            ],
        },
    ],
}

