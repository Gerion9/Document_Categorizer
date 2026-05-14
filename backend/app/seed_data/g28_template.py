"""
G-28 QC Checklist template data.

Structure: list of parts, each with optional subparts and questions.
Each question has: code, description, where_to_verify.

Key reminders:
- Bar No. for Law Offices of Manuel E. Solis: 18826790.
- USCIS Online Account No. (firm): 087361245002.
- Firm mailing address: P.O. Box 231704, Houston, TX 77223.
- Firm contact: 713-844-2700; uscism@manuelsolis.com.
- Use 'Mmm DD YYYY' (e.g., Mar 21 1979) for every date.
- Each G-28 is signed in ink by both the attorney and the client.
"""

G28_TEMPLATE = {
    "name": "QC Checklist - G-28",
    "description": "Quality Control checklist for G-28 Notice of Entry of Appearance as Attorney or Accredited Representative",
    "parts": [
        {
            "code": "Part 1",
            "name": "Information About Attorney or Accredited Representative",
            "questions": [
                {"code": "1.1", "description": "Did you verify the attorney's Full Legal Name (Items 1.a - 1.c) matches the firm record (e.g., Manuel E. Solis) and is consistent across the case?", "where_to_verify": "Firm records; attorney's bar card; case file"},
                {"code": "1.2", "description": "Did you verify the attorney's mailing address (Items 2.a - 2.i) uses the firm address P.O. Box 231704, Houston, TX 77223 unless a different office address applies?", "where_to_verify": "Firm records; office address policy"},
                {"code": "1.3", "description": "Did you verify the attorney's Daytime Telephone Number (Item 3) is 713-844-2700 (or the assigned office line)?", "where_to_verify": "Firm phone directory; office assignment notes"},
                {"code": "1.4", "description": "Did you verify the attorney's Mobile Telephone Number (Item 4) is left blank or matches the firm-issued mobile, if applicable?", "where_to_verify": "Firm records; attorney mobile policy"},
                {"code": "1.5", "description": "Did you verify the attorney's Fax Number (Item 5) is provided if used by the office, or left blank otherwise?", "where_to_verify": "Firm records; office fax assignment"},
                {"code": "1.6", "description": "Did you verify the attorney's Email Address (Item 6) is uscism@manuelsolis.com or the attorney's official firm email?", "where_to_verify": "Firm email directory"},
                {"code": "1.7", "description": "Did you verify the attorney's USCIS Online Account Number (Item 7) is 087361245002 or matches the attorney's individual USCIS account?", "where_to_verify": "Firm USCIS account records"},
            ],
        },
        {
            "code": "Part 2",
            "name": "Eligibility Information for Attorney or Accredited Representative",
            "questions": [
                {"code": "2.1", "description": "Did you verify Item 1.a (attorney in good standing) is checked when filing as an attorney, and that the Licensing Authority and Bar Number (Items 1.b - 1.c) are completed (Bar No. 18826790 for Manuel E. Solis)?", "where_to_verify": "Bar card; state bar website"},
                {"code": "2.2", "description": "Did you verify Item 1.d (not subject to any restrictions) is checked and that Item 1.e is left blank unless an explanation is needed in Part 9?", "where_to_verify": "Bar status report; firm compliance records"},
                {"code": "2.3", "description": "Did you verify Item 2 (accredited representative) is left blank because the filer is an attorney (or completed correctly if the filer is an accredited representative)?", "where_to_verify": "Firm records; DOJ-EOIR recognition list, if applicable"},
                {"code": "2.4", "description": "Did you verify Item 3 (law student/recent graduate) is left blank unless the form is being filed by an authorized law student/graduate under supervision?", "where_to_verify": "Firm records; supervision documentation, if applicable"},
                {"code": "2.5", "description": "Did you verify the Name of Law Firm (Item 4) is 'Law Offices of Manuel E. Solis, PLLC' or the correct organization name?", "where_to_verify": "Firm records; letterhead"},
            ],
        },
        {
            "code": "Part 3",
            "name": "Notice of Appearance as Attorney or Accredited Representative",
            "questions": [
                {"code": "3.1", "description": "Did you verify the Date of Appearance (Item 1) is the date the G-28 is signed and uses the 'Mmm DD YYYY' format?", "where_to_verify": "Signature date; filing schedule"},
                {"code": "3.2", "description": "Did you verify Item 2 (appearing for an interview or other USCIS-scheduled event) is checked only when applicable?", "where_to_verify": "USCIS notice; case calendar"},
                {"code": "3.3", "description": "Did you verify the client-type selection (Item 3) matches the underlying filing (e.g., Applicant for I-914/I-765/I-192; Petitioner for I-360)?", "where_to_verify": "Primary form; case strategy memo"},
                {"code": "3.4", "description": "Did you verify the Entity Name and Title (Items 4 - 5) are left blank for an individual client, or completed if the client is a business entity (e.g., I-129/I-140 employer)?", "where_to_verify": "Primary form; entity documents, if applicable"},
                {"code": "3.5", "description": "Did you verify the Client's Full Legal Name (Items 6.a - 6.c) matches the primary form and identity documents?", "where_to_verify": "Birth Certificate; Passport; primary form; BioCall"},
                {"code": "3.6", "description": "Did you verify the Client's A-Number (Item 7) is entered (with the 'A-' prefix omitted from the AcroForm fill) or left blank if the client has no A-Number?", "where_to_verify": "BioCall; prior immigration filings; FBI rap sheet"},
                {"code": "3.7", "description": "Did you verify the Client's USCIS Online Account Number (Item 8) is provided if available, or left blank if not?", "where_to_verify": "Prior USCIS filings; BioCall"},
                {"code": "3.8", "description": "Did you verify the Client's Daytime Telephone Number (Item 9) matches the contact information on file?", "where_to_verify": "Intake; BioCall; client contact records"},
                {"code": "3.9", "description": "Did you verify the Client's Mobile Telephone Number (Item 10) is provided when available?", "where_to_verify": "Intake; BioCall; client contact records"},
                {"code": "3.10", "description": "Did you verify the Client's Email Address (Item 11) is provided when available?", "where_to_verify": "Intake; BioCall; client contact records"},
            ],
        },
        {
            "code": "Part 4",
            "name": "Client's Consent to Representation and Signature",
            "questions": [
                {"code": "4.1", "description": "Did you verify the consent scope (Item 1.a or 1.b) is selected, and that limited representation, if applicable, is detailed in Part 9?", "where_to_verify": "Engagement letter; case strategy memo; Part 9 entries"},
                {"code": "4.2", "description": "Did you verify the Receipt of Original Notices preference (Item 2) is selected to direct notices to the firm address unless the client requests otherwise?", "where_to_verify": "Engagement letter; client preferences on file"},
                {"code": "4.3", "description": "Did you verify the Receipt of Secure Identity Documents preference (Item 3) is selected to direct secure documents to the client's mailing address unless the firm address is appropriate?", "where_to_verify": "Engagement letter; client preferences on file"},
                {"code": "4.4", "description": "Did you verify the client signed Item 4 in ink (original wet signature)?", "where_to_verify": "Original G-28; signature page"},
                {"code": "4.5", "description": "Did you verify the client's Date of Signature (Item 5) uses 'Mmm DD YYYY' format and is consistent with the Part 5 attorney signature date?", "where_to_verify": "Signature page"},
            ],
        },
        {
            "code": "Part 5",
            "name": "Signature of Attorney or Accredited Representative",
            "questions": [
                {"code": "5.1", "description": "Did you verify the attorney signed Item 1 in ink (original wet signature)?", "where_to_verify": "Original G-28; signature page"},
                {"code": "5.2", "description": "Did you verify the attorney's Date of Signature (Item 2) uses 'Mmm DD YYYY' format?", "where_to_verify": "Signature page"},
            ],
        },
        {
            "code": "Part 9",
            "name": "Additional Information",
            "questions": [
                {"code": "9.1", "description": "If Part 9 is used, did you verify the applicant's name and A-Number (if any) appear at the top of the page?", "where_to_verify": "Part 9 entries; additional sheets"},
                {"code": "9.2", "description": "Did you verify each Part 9 entry includes the correct Page Number, Part Number, and Item Number?", "where_to_verify": "Part 9 entries"},
                {"code": "9.3", "description": "Did you verify each explanation is clear, specific, and consistent with the main G-28 entries (e.g., describing limited representation scope referenced in Part 4, Item 1.b)?", "where_to_verify": "Part 9 entries; main form"},
                {"code": "9.4", "description": "Did you verify any additional sheets include the applicant's name, A-Number (if any), signature, and date?", "where_to_verify": "Attachments; additional sheets"},
            ],
        },
        {
            "code": "Filing",
            "name": "Filing Logistics",
            "questions": [
                {"code": "F.1", "description": "Did you verify a copy of the G-28 is included with EVERY USCIS filing for this client (e.g., I-914, I-765, I-192, I-360, G-1145)?", "where_to_verify": "Filing packet; cover letter; filing checklist"},
                {"code": "F.2", "description": "Did you verify the G-28 edition date in the lower-right footer matches the most recent edition published at uscis.gov/g-28?", "where_to_verify": "USCIS website; form footer"},
                {"code": "F.3", "description": "Did you verify the corresponding 'Form G-28 is attached' checkbox is selected on the primary form(s) being filed (e.g., Page 1 of I-765, Part 1 of I-192)?", "where_to_verify": "Primary forms"},
            ],
        },
    ],
    "reference_sources": {
        "Firm records": "Bar No. 18826790; USCIS Online Account No. 087361245002; firm address P.O. Box 231704, Houston, TX 77223; firm phone 713-844-2700; firm email uscism@manuelsolis.com",
        "Identity & civil": "Birth Certificate; Passport; national ID; Social Security card",
        "Internal case sources": "Engagement letter; BioCall (BOS); Intake (BOS); BOS notes; case assignment notes; strategy memo; client contact records",
        "Immigration / status": "Prior USCIS filings; Form I-797; FBI rap sheet; FOIA, as needed",
        "Filing / packet components": "Primary application or petition; cover letter; filing checklist; original signature page",
    },
}
