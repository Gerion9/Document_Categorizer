"""
I-360 QC Checklist template data (SIJS-focused).

Structure: list of parts, each with optional subparts and questions.
Each question has: code, description, where_to_verify.

Scope:
- Special Immigrant Juvenile (SIJ) self-petitions only.
- Other I-360 classifications (Amerasian, Widow(er), Religious Worker,
  Iraqi/Afghan Translator, Broadcaster, VAWA self-petitioners) are out
  of scope for this checklist.

Key reminders:
- Bar No. for Law Offices of Manuel E. Solis: 18826790.
- USCIS Online Account No. (firm): 087361245002.
- Firm mailing address: P.O. Box 231704, Houston, TX 77223.
- Firm contact: 713-844-2700; uscism@manuelsolis.com.
- Use 'Mmm DD YYYY' (e.g., Mar 21 2008) for every date.
- SIJS eligibility: under 21 and unmarried at time of filing AND
  through adjudication; a qualifying state court order must exist.
"""

I360_TEMPLATE = {
    "name": "QC Checklist - I-360 (SIJS)",
    "description": "Quality Control checklist for I-360 Petition for Amerasian, Widow(er), or Special Immigrant - scoped to Special Immigrant Juvenile (SIJ) self-petitions filed by the Law Offices of Manuel E. Solis",
    "parts": [
        {
            "code": "Page 1 Header",
            "name": "Attorney / Accredited Representative Header (top of Page 1)",
            "questions": [
                {"code": "H.1", "description": "Did you verify the 'To be completed by an attorney or accredited representative (if any)' checkbox (CheckBox1) is marked because a G-28 is always filed with the I-360?", "where_to_verify": "Filed G-28; cover letter; filing checklist"},
                {"code": "H.2", "description": "Did you verify the Attorney State Bar Number is 18826790 (Manuel E. Solis), or the bar number of the appearing attorney named on the G-28?", "where_to_verify": "G-28; bar card; firm records"},
                {"code": "H.3", "description": "Did you verify the Attorney USCIS Online Account Number is 087361245002 (firm) or the appearing attorney's individual USCIS account?", "where_to_verify": "G-28; firm USCIS account records"},
            ],
        },
        {
            "code": "Part 1",
            "name": "Information About the Person Filing this Petition (Petitioner = juvenile)",
            "questions": [
                {"code": "1.1", "description": "Did you verify the Petitioner's Full Legal Name (Items 1.a - 1.c) matches the birth certificate, passport, and state court order, and is consistent with the G-28 client name?", "where_to_verify": "Birth Certificate; Passport; state court order; G-28; BioCall"},
                {"code": "1.2", "description": "Did you verify the USCIS Online Account Number (Item 2) is provided if the juvenile has an online account, or left blank if not?", "where_to_verify": "Prior USCIS filings; client account records"},
                {"code": "1.3", "description": "Did you verify the SSN (Item 3) is provided only when the juvenile has been issued an SSN, and is left blank otherwise?", "where_to_verify": "Social Security card; SSA records"},
                {"code": "1.4", "description": "Did you verify the A-Number (Item 4) is provided (without the 'A-' prefix) when the juvenile has one, or left blank if none has been assigned?", "where_to_verify": "Prior I-797 receipts; FBI rap sheet; EOIR portal"},
                {"code": "1.5", "description": "Did you verify Item 5 (IRS Employer ID) is left blank because SIJS petitioners are individuals, not organizations?", "where_to_verify": "Form footer; case strategy memo"},
                {"code": "1.6", "description": "Did you verify the Mailing Address (Items 6.a - 6.i) is correct, uses the firm address only when notices are directed to the firm, and is consistent with the G-28 Item 6 client address?", "where_to_verify": "Engagement letter; intake; BioCall; G-28"},
                {"code": "1.7", "description": "Did you verify the Physical Address (Items 7.a - 7.i) is provided when it differs from the mailing address, and left blank when it matches?", "where_to_verify": "Intake; BioCall; school records"},
            ],
        },
        {
            "code": "Part 2",
            "name": "Classification Requested",
            "questions": [
                {"code": "2.1", "description": "Did you verify only 'Special Immigrant Juvenile' (Item 1.c, Pt2Line1[2]) is checked, and that every other classification box (Amerasian, Widow(er), Religious Worker, Iraqi/Afghan Translator, VAWA self-petitioners, etc.) is left unchecked?", "where_to_verify": "Form footer; case strategy memo"},
                {"code": "2.2", "description": "Did you verify the 'Other / Describe' fields (Pt2Line1d1_yes/no, Pt2Line1p_Describe) are left blank because SIJS does not require an explanation in Part 2?", "where_to_verify": "Form footer"},
            ],
        },
        {
            "code": "Part 3",
            "name": "Information About the Person this Petition is For (Beneficiary = juvenile)",
            "questions": [
                {"code": "3.1", "description": "Did you verify the Beneficiary's Full Legal Name (Items 1.a - 1.c) is identical to Part 1, Items 1.a - 1.c because SIJS is a self-petition?", "where_to_verify": "Form internal consistency; birth certificate; G-28"},
                {"code": "3.2", "description": "Did you verify the Beneficiary's Address (Items 2.a - 2.i) is the juvenile's residence and is consistent with Part 1 (mailing or physical address)?", "where_to_verify": "Intake; BioCall"},
                {"code": "3.3", "description": "Did you verify the Date of Birth (Item 3) is in 'Mmm DD YYYY' format, matches the birth certificate, and confirms the juvenile is under 21 as of the planned filing date?", "where_to_verify": "Birth Certificate; passport; case strategy memo"},
                {"code": "3.4", "description": "Did you verify the Country of Birth (Item 4) matches the birth certificate and passport?", "where_to_verify": "Birth Certificate; Passport"},
                {"code": "3.5", "description": "Did you verify the SSN (Item 5) and A-Number (Item 6) match the values in Part 1?", "where_to_verify": "Form internal consistency"},
                {"code": "3.6", "description": "Did you verify the Marital Status (Item 7) is 'Single, Never Married' for typical SIJS cases, and that any 'Divorced/Annulled' selection is supported by an annulment/divorce decree showing the marriage is fully terminated before filing?", "where_to_verify": "Birth Certificate; civil registry; annulment/divorce decree; case strategy memo"},
                {"code": "3.7", "description": "Did you verify the Date of Last Arrival (Item 8) and I-94 (Item 9) are sourced from i94.cbp.dhs.gov, entry stamps, or the juvenile's recollection (with a note in Part 14 when no record exists)?", "where_to_verify": "I-94 print-out; CBP I-94 portal; passport stamps; intake"},
                {"code": "3.8", "description": "Did you verify the Passport/Travel Document fields (Items 10 - 13) match the passport biographic page, including expiration date in 'Mmm DD YYYY' format?", "where_to_verify": "Passport biographic page"},
                {"code": "3.9", "description": "Did you verify the Current USCIS Status (Item 14) and Status Expiration Date (Item 15) reflect the juvenile's current status (e.g., 'No status / EWI', 'Parole', 'TPS', 'Pending asylum')?", "where_to_verify": "Prior I-797 receipts; ICE/DHS records; EOIR portal"},
            ],
        },
        {
            "code": "Part 4",
            "name": "Processing Information",
            "questions": [
                {"code": "4.1", "description": "Did you verify the Consulate City/Country (Items 1.a - 1.b) is left blank when the juvenile will adjust status in the U.S. (typical SIJS) and completed only for consular processing?", "where_to_verify": "Case strategy memo"},
                {"code": "4.2", "description": "Did you verify the Sex (Item 3) is marked Male or Female to match the birth certificate / government ID?", "where_to_verify": "Birth Certificate; Passport"},
                {"code": "4.3", "description": "Did you verify the Prior Immigration Proceedings answer (Item 5) accurately reflects FBI rap sheet, EOIR portal, and FOIA findings?", "where_to_verify": "FBI rap sheet; EOIR portal; FOIA; case strategy memo"},
                {"code": "4.4", "description": "Did you verify the 'currently in U.S. and will adjust status' answer (Item 6) is 'Yes' for typical SIJS cases?", "where_to_verify": "Case strategy memo; intake"},
            ],
        },
        {
            "code": "Parts 5-7",
            "name": "Spouse/Children, Amerasian, Widow(er) (must be blank)",
            "questions": [
                {"code": "57.1", "description": "Did you verify Part 5 (Spouse and Children) is left blank in standard SIJS cases (juvenile must be unmarried and rarely has biological children)? Complete only if the juvenile has biological children, and confirm the entries match the case file.", "where_to_verify": "Intake; BioCall; case strategy memo"},
                {"code": "57.2", "description": "Did you verify Parts 6 (Amerasian) and 7 (Widow(er)) are completely blank because they apply to other classifications, not SIJS?", "where_to_verify": "Form footer"},
            ],
        },
        {
            "code": "Part 8",
            "name": "Special Immigrant Juvenile (SIJ) findings",
            "questions": [
                {"code": "8.1", "description": "Did you verify the SIJ Current Legal Name (Items 1.a - 1.c) matches Part 1 exactly?", "where_to_verify": "Form internal consistency"},
                {"code": "8.2", "description": "Did you verify the SIJ 'Other Names Used' (Items 1.d - 1.f) include the name on the state court order if it differs from the current legal name?", "where_to_verify": "State court order; identity documents"},
                {"code": "8.3", "description": "Did you verify the unmarried eligibility checkbox (Item 2.a, Pt8Line2a) is marked 'Yes' and is supported by a sworn statement and absence of any prior marriage records?", "where_to_verify": "Sworn statement; civil registry; intake"},
                {"code": "8.4", "description": "Did you verify the state court name and case number (Item 2.b, Pt8Line2b_Name) are entered in the format 'Court Name - Case No. XXX' and match the certified court order?", "where_to_verify": "Certified state court order"},
                {"code": "8.5", "description": "Did you verify the under-21 eligibility checkbox (Item 2.c, Pt8Line2c) is marked 'Yes' based on date of birth vs. filing date?", "where_to_verify": "Birth Certificate; planned filing date"},
                {"code": "8.6", "description": "Did you verify the court order findings checkboxes (Items 3.a, 3.b, 3.A, 3.b sub-checkboxes) accurately reflect the findings in the certified state court order (parental reunification not viable due to abuse, neglect, abandonment, or similar basis under State law)?", "where_to_verify": "Certified state court order; SIJS predicate order best practice memo"},
                {"code": "8.7", "description": "Did you verify the custody / placement checkboxes (Items 4.a - 4.b, Pt8Line4a, Pt8Line4b_NameOfParent) reflect the state court order's placement determination (juvenile court, agency, individual)?", "where_to_verify": "Certified state court order"},
                {"code": "8.8", "description": "Did you verify the best-interest checkbox (Item 5, Pt8Line5) confirms the court found that returning to the country of nationality / last habitual residence is not in the juvenile's best interest?", "where_to_verify": "Certified state court order"},
                {"code": "8.9", "description": "Did you verify the country and date information related to the court findings (Items 6.a - 6.b) is consistent with the order and with Part 3 country of birth?", "where_to_verify": "Certified state court order; Part 3 internal consistency"},
            ],
        },
        {
            "code": "Parts 9-10",
            "name": "Religious Worker, VAWA self-petition (must be blank)",
            "questions": [
                {"code": "910.1", "description": "Did you verify Part 9 (Religious Worker) is entirely blank because it applies only to religious worker classifications?", "where_to_verify": "Form footer"},
                {"code": "910.2", "description": "Did you verify Part 10 (VAWA-self petitioning spouse/child) is entirely blank because SIJS is a separate classification?", "where_to_verify": "Form footer"},
            ],
        },
        {
            "code": "Part 11",
            "name": "Petitioner's Statement, Contact Information, Declaration, Certification, and Signature",
            "questions": [
                {"code": "11.1", "description": "Did you verify the petitioner's-statement checkbox (Item 1, Pt11Line1_Checkbox) reflects whether the petition was read directly or read through an interpreter, consistent with the interpreter section in Part 12?", "where_to_verify": "Interpreter notes; case file"},
                {"code": "11.2", "description": "Did you verify the language field (Item 1.b, Pt11Line1b_Language) is completed when an interpreter was used and is blank otherwise?", "where_to_verify": "Interpreter notes"},
                {"code": "11.3", "description": "Did you verify the preparer checkbox (Item 2, Pt11Line2_Checkbox) is marked and that Item 2's representative name (Pt11Line2_RepresentativeName) matches the attorney appearing on the G-28?", "where_to_verify": "G-28; firm records"},
                {"code": "11.4", "description": "Did you verify the petitioner's daytime/mobile phone and email (Items 3 - 5) match the client contact information on file?", "where_to_verify": "Intake; BioCall; client contact records"},
                {"code": "11.5", "description": "Did you verify the petitioner's signature (Item 6.a) is wet ink, and the date of signature (Item 6.b, Pt11Line6_DateofSignature) uses 'Mmm DD YYYY' format and is consistent with the G-28 client signature date?", "where_to_verify": "Original signature page; G-28"},
            ],
        },
        {
            "code": "Part 12",
            "name": "Interpreter's Contact Information, Certification, and Signature",
            "questions": [
                {"code": "12.1", "description": "If an interpreter was used (Part 11 Item 1 marked 'with interpreter'), did you verify Item 1 (interpreter's full name) and Item 2 (business / organization) are completed?", "where_to_verify": "Interpreter notes; case file"},
                {"code": "12.2", "description": "Did you verify the language of interpretation (Pt12_NameofLanguage) matches Part 11 Item 1.b?", "where_to_verify": "Form internal consistency"},
                {"code": "12.3", "description": "Did you verify the interpreter's signature and date use the 'Mmm DD YYYY' format and were obtained from the actual interpreter (wet ink)?", "where_to_verify": "Original signature page"},
                {"code": "12.4", "description": "If no interpreter was used, did you verify Part 12 is left entirely blank?", "where_to_verify": "Form footer; interpreter notes"},
            ],
        },
        {
            "code": "Part 13",
            "name": "Contact Information, Declaration, and Signature of Person Preparing this Petition",
            "questions": [
                {"code": "13.1", "description": "Did you verify the preparer's name (Item 1, Pt13Line1_PreparerFamilyName / Pt13Line1_PreparerGivenName) is the appearing attorney named on the G-28?", "where_to_verify": "G-28; firm records"},
                {"code": "13.2", "description": "Did you verify the preparer's business name (Item 2, Pt13Line2_BusinessName) is 'Law Offices of Manuel E. Solis, PLLC'?", "where_to_verify": "Firm records; letterhead"},
                {"code": "13.3", "description": "Did you verify the preparer's mailing address (Item 3, Pt14Line3 group on page 18) is the firm address P.O. Box 231704, Houston, TX 77223 (or the assigned office address)?", "where_to_verify": "Firm records"},
                {"code": "13.4", "description": "Did you verify the preparer's daytime phone (Item 4, Pt13Line4_DaytimePhoneNumber1) is 713-844-2700 or the assigned office line?", "where_to_verify": "Firm phone directory"},
                {"code": "13.5", "description": "Did you verify the preparer's email (Item 6, Pt13Line6_Email) is uscism@manuelsolis.com or the appearing attorney's firm email?", "where_to_verify": "Firm email directory"},
                {"code": "13.6", "description": "Did you verify the preparer relationship checkbox (Item 7, Pt13Line7_Checkbox) is marked 'Attorney or Accredited Representative whose representation extends beyond preparation'?", "where_to_verify": "G-28; case strategy memo"},
                {"code": "13.7", "description": "Did you verify the preparer's signature (wet ink) and date of signature (Item 8, Pt13Line8_DateofSignature) use 'Mmm DD YYYY' format and align with the G-28 attorney signature date?", "where_to_verify": "Original signature page; G-28"},
            ],
        },
        {
            "code": "Part 14",
            "name": "Additional Information",
            "questions": [
                {"code": "14.1", "description": "If Part 14 is used, did you verify the juvenile's family name, given name, middle name, and A-Number anchors at the top of the page are completed?", "where_to_verify": "Part 14 entries"},
                {"code": "14.2", "description": "Did you verify each Part 14 entry includes the correct Page Number, Part Number, and Item Number references?", "where_to_verify": "Part 14 entries"},
                {"code": "14.3", "description": "Did you verify each explanation is clear, specific, and consistent with the answers it expands (e.g., name on court order, prior immigration history, missing I-94)?", "where_to_verify": "Part 14 entries; main form"},
            ],
        },
        {
            "code": "Filing",
            "name": "Filing Logistics",
            "questions": [
                {"code": "F.1", "description": "Did you verify a G-28 is filed concurrently with the I-360 and that Page 1 'G-28 is attached' (CheckBox1) is marked?", "where_to_verify": "Filed G-28; cover letter; filing checklist"},
                {"code": "F.2", "description": "Did you verify the I-360 edition date in the lower-right footer matches the most recent edition published at uscis.gov/i-360?", "where_to_verify": "USCIS website; form footer"},
                {"code": "F.3", "description": "Did you verify the filing packet includes the certified state court order (with required SIJS findings) and the juvenile's birth certificate?", "where_to_verify": "Filing packet; filing checklist"},
                {"code": "F.4", "description": "Did you verify the correct fee or fee-exempt status is documented (SIJS petitions filed before the juvenile turns 21 are fee-exempt per current USCIS policy)?", "where_to_verify": "USCIS fee schedule; filing checklist"},
                {"code": "F.5", "description": "Did you verify the juvenile is still under 21 and unmarried on the actual mailing/filing date (not just on the date the petition was drafted)?", "where_to_verify": "Filing log; case calendar"},
            ],
        },
    ],
    "reference_sources": {
        "Firm records": "Bar No. 18826790; USCIS Online Account No. 087361245002; firm address P.O. Box 231704, Houston, TX 77223; firm phone 713-844-2700; firm email uscism@manuelsolis.com",
        "Identity & civil": "Birth Certificate; Passport; national ID; Social Security card; sworn statement",
        "Internal case sources": "Engagement letter; BioCall (BOS); Intake (BOS); BOS notes; case assignment notes; strategy memo; client contact records; interpreter notes",
        "Immigration / status": "Prior USCIS filings; Form I-797; FBI rap sheet; EOIR portal; FOIA; CBP I-94 portal",
        "SIJS-specific": "Certified state court order (predicate order); SIJS predicate order best practice memo; school records; ORR/UAC records when applicable",
        "Filing / packet components": "G-28; cover letter; filing checklist; certified state court order; original signature page",
    },
}
