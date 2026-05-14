"""
G-1145 QC Checklist template data.

Structure: list of parts, each with optional subparts and questions.
Each question has: code, description, where_to_verify.

Key reminders: G-1145 is a one-page eNotification request submitted with the
primary USCIS application or petition. It captures the applicant's name plus
the email address and U.S. mobile phone number USCIS may use to send an
acceptance notification. The form must be stapled to the first page of the
related application or petition (NOT mailed separately).
"""

G1145_TEMPLATE = {
    "name": "QC Checklist - G-1145",
    "description": "Quality Control checklist for G-1145 E-Notification of Application/Petition Acceptance",
    "parts": [
        {
            "code": "Filing",
            "name": "Filing Logistics",
            "questions": [
                {"code": "F.1", "description": "Did you verify the completed G-1145 is stapled to the FIRST page of the primary application or petition being filed and is not mailed under a separate cover?", "where_to_verify": "Filing packet; cover letter; mailing checklist"},
                {"code": "F.2", "description": "Did you verify the edition date in the lower-right footer matches the most recent edition published at uscis.gov/g-1145?", "where_to_verify": "USCIS website; form footer"},
            ],
        },
        {
            "code": "Applicant",
            "name": "Applicant's Full Name",
            "questions": [
                {"code": "A.1", "description": "Did you verify the applicant's Family Name (Last Name) matches the primary application/petition and supporting identity documents?", "where_to_verify": "Birth Certificate; Passport; primary form (I-914, I-765, I-192, etc.); BioCall"},
                {"code": "A.2", "description": "Did you verify the applicant's Given Name (First Name) matches the primary application/petition and supporting identity documents?", "where_to_verify": "Birth Certificate; Passport; primary form; BioCall"},
                {"code": "A.3", "description": "Did you verify the applicant's Middle Name (if any) matches the primary application/petition and supporting identity documents, and is left blank if the applicant has no middle name?", "where_to_verify": "Birth Certificate; Passport; primary form; BioCall"},
            ],
        },
        {
            "code": "Contact",
            "name": "Notification Channels",
            "questions": [
                {"code": "C.1", "description": "Did you verify the applicant's Email Address is current, monitored by the applicant, and consistent with contact information on the primary form?", "where_to_verify": "Intake; BOS; client contact records; primary form contact section"},
                {"code": "C.2", "description": "Did you verify the applicant's Mobile Phone Number is a U.S. mobile number capable of receiving SMS text messages?", "where_to_verify": "Intake; BOS; client contact records"},
                {"code": "C.3", "description": "Did you verify at least one notification channel (email OR mobile phone) is provided, because USCIS will not send a notification if both fields are blank?", "where_to_verify": "Completed G-1145"},
                {"code": "C.4", "description": "Did you verify the applicant has been informed that only ONE notification per recipient will be sent and that traditional paper receipts will still be issued by USCIS?", "where_to_verify": "BioCall notes; client communication log"},
            ],
        },
        {
            "code": "Consistency",
            "name": "Consistency With Primary Form",
            "questions": [
                {"code": "X.1", "description": "Did you verify the applicant name on G-1145 exactly matches the primary application/petition (no aliases, no nicknames)?", "where_to_verify": "Primary form; G-1145"},
                {"code": "X.2", "description": "Did you verify the email and mobile phone, if also provided on the primary application/petition, match between forms?", "where_to_verify": "Primary form; G-1145"},
            ],
        },
    ],
    "reference_sources": {
        "Identity & civil": "Birth Certificate; Passport; national ID",
        "Internal case sources": "BioCall (BOS); Intake (BOS); client contact records; assigned case manager",
        "Filing / packet components": "Primary application or petition (e.g., I-914, I-765, I-192); cover letter; filing checklist",
    },
}
