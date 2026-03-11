"""
I-765 QC Checklist template data.
Edition 08/21/25

Structure: list of parts, each with optional subparts and questions.
Each question has: code, description, where_to_verify.

Key reminders: use mm/dd/yyyy for all dates; complete only the category-specific
fields that apply; if Item 1.c is selected, attach a copy of the prior EAD;
if Item 30 or 31.b is answered Yes, verify court dispositions; if replacement
is due to USCIS error, review the form note before refiling.
"""

I765_TEMPLATE = {
    "name": "QC Checklist - I-765",
    "description": "Quality Control checklist for I-765 Application for Employment Authorization",
    "parts": [
        {
            "code": "Header",
            "name": "I-765 Header / Top of Page 1",
            "questions": [
                {"code": "H.1", "description": "Did you verify the Page 1 attorney/accredited representative box is checked only if Form G-28 is attached?", "where_to_verify": "G-28; filing packet; case file"},
                {"code": "H.2", "description": "Did you verify the Attorney State Bar Number and USCIS Online Account Number are completed correctly when representation applies?", "where_to_verify": "G-28; attorney records. For Law Offices of Manuel E. Solis: Bar No. 18826790; USCIS Online Account No. 087361245002"},
                {"code": "H.3", "description": "Did you verify this section is left blank if no attorney or accredited representative is appearing on the case?", "where_to_verify": "Case file; G-28 status"},
            ],
        },
        {
            "code": "Part 1",
            "name": "I-765 Part 1",
            "questions": [
                {"code": "1", "description": "Did you verify the correct reason for applying is selected (1.a initial permission, 1.b replacement/correction not due to USCIS error, or 1.c renewal)?", "where_to_verify": "Intake; Bio Call; case strategy memo; prior EAD or prior filings"},
                {"code": "2", "description": "If Item 1.b is selected, did you verify the replacement/correction is NOT due to USCIS error and that the case is appropriate for a new I-765?", "where_to_verify": "Client documents; USCIS notices; prior EAD; case file"},
                {"code": "3", "description": "If Item 1.c is selected, did you verify a copy of the previous employment authorization document is attached?", "where_to_verify": "Prior EAD card; prior filings; client documents"},
                {"code": "4", "description": "Did you verify Your Full Legal Name (Items 1.a - 1.c)?", "where_to_verify": "Birth Certificate; Passport; prior immigration filings"},
            ],
        },
        {
            "code": "Part 2",
            "name": "Identity / Address / Other Information",
            "questions": [
                {"code": "2.1", "description": "Did you verify Other Names Used (Items 2.a - 4.e), including aliases, maiden names, and nicknames, and use Part 6 if more space is needed?", "where_to_verify": "FBI records; Bio Call; prior filings; civil documents"},
                {"code": "2.2", "description": "Did you verify the U.S. Mailing Address (Items 5.a - 5.f), including In Care Of information and any safe mailing address used in the case?", "where_to_verify": "Bio Call; BOS; proof of address; safe mailing instructions. If office mailing is used, confirm the correct office address"},
                {"code": "2.3", "description": "Did you verify Item 6 is answered correctly (whether the current mailing address is the same as the physical address)?", "where_to_verify": "Bio Call; compare mailing and physical address entries"},
                {"code": "2.4", "description": "If Item 6 = No, did you verify the U.S. Physical Address (Items 7.a - 7.e)?", "where_to_verify": "Bio Call; Google Maps; proof of address"},
                {"code": "2.5", "description": "Did you verify the Alien Registration Number (A-Number), if any? (Item 8)", "where_to_verify": "Intake; Bio Call; prior immigration documents; FBI rap sheet"},
                {"code": "2.6", "description": "Did you verify the USCIS Online Account Number, if any? (Item 9)", "where_to_verify": "Bio Call; USCIS account information; prior filings"},
                {"code": "2.7", "description": "Did you verify Sex? (Item 10)", "where_to_verify": "Birth Certificate; Passport"},
                {"code": "2.8", "description": "Did you verify Marital Status? (Item 11)", "where_to_verify": "Intake; Bio Call; marriage certificate; divorce decree; death certificate, as applicable"},
                {"code": "2.9", "description": "Did you verify whether the applicant previously filed Form I-765? (Item 12)", "where_to_verify": "Prior filings; USCIS receipts/notices; Bio Call"},
                {"code": "2.10", "description": "Did you verify the Social Security Number (government-issued SSN only), if known? (Item 13)", "where_to_verify": "Bio Call; Social Security card"},
                {"code": "2.11", "description": "Did you verify all Countries of Citizenship or Nationality (Items 14.a - 14.b)?", "where_to_verify": "Birth Certificate; Passport; national ID, if applicable"},
                {"code": "2.12", "description": "Did you verify Place of Birth (Items 15.a - 15.c)?", "where_to_verify": "Birth Certificate; Passport"},
                {"code": "2.13", "description": "Did you verify Date of Birth (Item 16) using the proper format (mm/dd/yyyy)?", "where_to_verify": "Birth Certificate; Passport"},
                {"code": "2.14", "description": "Did you verify the Form I-94 Arrival-Departure Record Number, if any? (Item 17)", "where_to_verify": "I-94; CBP records; FOIA, if needed"},
                {"code": "2.15", "description": "Did you verify the Passport Number of the most recently issued passport? (Item 18)", "where_to_verify": "Passport; prior filings"},
                {"code": "2.16", "description": "Did you verify the Travel Document Number, if any? (Item 19)", "where_to_verify": "Travel document; visa; I-94; other immigration documents"},
                {"code": "2.17", "description": "Did you verify the Country that issued the passport or travel document? (Item 20)", "where_to_verify": "Passport; travel document"},
                {"code": "2.18", "description": "Did you verify the Expiration Date for passport or travel document (Item 21) using the proper format (mm/dd/yyyy)?", "where_to_verify": "Passport; travel document"},
                {"code": "2.19", "description": "Did you verify the Date of the applicant's last arrival into the United States (Item 22) using the proper format (mm/dd/yyyy)?", "where_to_verify": "I-94; passport stamp; declaration; Intake; FOIA, if needed"},
                {"code": "2.20", "description": "Did you verify the Place of the applicant's last arrival into the United States (Item 23)?", "where_to_verify": "I-94; passport stamp; declaration; Intake; FOIA, if needed"},
                {"code": "2.21", "description": "Did you verify Immigration Status at Last Arrival (Item 24)?", "where_to_verify": "I-94; visa; admission documents; declaration; Intake"},
                {"code": "2.22", "description": "Did you verify Current Immigration Status or Category (Item 25)?", "where_to_verify": "Current immigration documents; prior filings; Intake; Bio Call"},
                {"code": "2.23", "description": "Did you verify the SEVIS Number, if any? (Item 26)", "where_to_verify": "Form I-20; SEVIS records; school documents"},
                {"code": "2.24", "description": "Did you verify the Eligibility Category entered in Item 27 matches the case strategy and supporting eligibility documents?", "where_to_verify": "Cover letter; strategy memo; I-94/I-20/I-797/prior EAD; case file"},
                {"code": "2.25", "description": "If (c)(3)(C) STEM OPT is selected, did you verify Degree, Employer's Name as Listed in E-Verify, and Employer's E-Verify Company or Client Company ID (Items 28.a - 28.c)?", "where_to_verify": "Form I-20; SEVIS records; employer letter; E-Verify records"},
                {"code": "2.26", "description": "If (c)(26) is selected, did you verify the H-1B spouse's most recent Form I-797 receipt number for Form I-129 is entered correctly? (Item 29)", "where_to_verify": "Spouse's Form I-797 Notice; Form I-129 receipt/approval; prior filings"},
                {"code": "2.27", "description": "If (c)(8) is selected, did you verify whether the applicant has EVER been arrested for and/or convicted of any crime and, if Yes, that court dispositions are available? (Item 30)", "where_to_verify": "FBI records; court dispositions; criminal record; declaration; Bio Call"},
                {"code": "2.28", "description": "If (c)(35) or (c)(36) is selected, did you verify the Form I-140 receipt number is entered correctly? (Item 31.a)", "where_to_verify": "Form I-797 Notice for Form I-140; spouse's or parent's Form I-140 notice, if applicable"},
                {"code": "2.29", "description": "If (c)(35) or (c)(36) is selected, did you verify whether the applicant has EVER been arrested for and/or convicted of any crime and, if Yes, that court dispositions are available? (Item 31.b)", "where_to_verify": "FBI records; court dispositions; criminal record; declaration; Bio Call"},
            ],
        },
        {
            "code": "Part 3",
            "name": "Applicant's Statement, Contact Information, Declaration, Certification, and Signature",
            "note": "Form I-765 must be filed while the applicant is in the United States.",
            "questions": [
                {"code": "3.1", "description": "Did you verify Item 1.a or 1.b is checked correctly, but not both?", "where_to_verify": "Bio Call; applicant language ability; completed form"},
                {"code": "3.2", "description": "If Item 1.b is checked, did you verify the interpreter language is entered and matches Part 4?", "where_to_verify": "Bio Call; interpreter information; Part 4"},
                {"code": "3.3", "description": "Did you verify whether Item 2 is checked correctly when a preparer is used, and that it matches Part 5?", "where_to_verify": "Part 5; BOS; assigned case manager; case file"},
                {"code": "3.4", "description": "Did you verify all applicant contact information (Items 3 - 5) is complete and consistent across the form?", "where_to_verify": "Intake; Bio Call; BOS; client contact records"},
                {"code": "3.5", "description": "Did you verify whether the ABC settlement agreement box (Item 6) applies and is checked only when appropriate?", "where_to_verify": "Intake; declaration; nationality documents; legal strategy memo"},
                {"code": "3.6", "description": "Did you verify the applicant signed Item 7.a in ink?", "where_to_verify": "Original I-765 signature page"},
                {"code": "3.7", "description": "Did you verify the date of signature in Item 7.b is complete and in mm/dd/yyyy?", "where_to_verify": "Original I-765 signature page"},
            ],
        },
        {
            "code": "Part 4",
            "name": "Interpreter's Contact Information, Certification, and Signature",
            "questions": [
                {"code": "4.1", "description": "Did you verify the interpreter's full legal name (Items 1.a - 1.b) and that it matches the correct interpreter or assigned case manager, if applicable?", "where_to_verify": "BOS; interpreter record; case assignment notes"},
                {"code": "4.2", "description": "Did you verify the interpreter's business or organization name, if any? (Item 2)", "where_to_verify": "If English/Spanish: Law Offices of Manuel E. Solis. If other language: client's interpreter information"},
                {"code": "4.3", "description": "Did you verify the interpreter's mailing address (Items 3.a - 3.h)?", "where_to_verify": "If Law Offices of Manuel E. Solis: P.O. Box 231704, Houston, TX 77223. Otherwise, use the interpreter's own address information"},
                {"code": "4.4", "description": "Did you verify the interpreter's contact information (Items 4 - 6) is complete?", "where_to_verify": "If Law Offices of Manuel E. Solis: 713-844-2700; uscism@manuelsolis.com. Otherwise, use the interpreter's own contact information"},
                {"code": "4.5", "description": "Did you verify the language in the interpreter certification matches Part 3, Item 1.b?", "where_to_verify": "Part 3; Bio Call; interpreter certification"},
                {"code": "4.6", "description": "Did you verify the interpreter signed Item 7.a in ink?", "where_to_verify": "Original I-765; interpreter signature page"},
                {"code": "4.7", "description": "Did you verify the date of signature in Item 7.b is complete and in mm/dd/yyyy?", "where_to_verify": "Original I-765; interpreter signature page"},
            ],
        },
        {
            "code": "Part 5",
            "name": "Contact Information, Declaration, and Signature of the Person Preparing this Application, if Other Than the Applicant",
            "questions": [
                {"code": "5.1", "description": "Did you verify the preparer's full legal name (Items 1.a - 1.b) and that it matches the correct preparer or assigned case manager, if applicable?", "where_to_verify": "BOS; preparer record; case assignment notes"},
                {"code": "5.2", "description": "Did you verify the preparer's business or organization name, if any? (Item 2)", "where_to_verify": "If prepared by office staff: Law Offices of Manuel E. Solis. Otherwise, use the preparer's own organization information"},
                {"code": "5.3", "description": "Did you verify the preparer's mailing address (Items 3.a - 3.h)?", "where_to_verify": "If Law Offices of Manuel E. Solis: P.O. Box 231704, Houston, TX 77223. Otherwise, use the preparer's own address information"},
                {"code": "5.4", "description": "Did you verify the preparer's contact information (Items 4 - 6) is complete?", "where_to_verify": "If Law Offices of Manuel E. Solis: 713-844-2700; uscism@manuelsolis.com. Otherwise, use the preparer's own contact information"},
                {"code": "5.5", "description": "Did you verify whether Item 7.a or 7.b is checked correctly?", "where_to_verify": "BOS; case file. If the preparer is not an attorney/accredited representative, check 7.a. If attorney/accredited representative, check 7.b"},
                {"code": "5.6", "description": "If Item 7.b is checked, did you verify whether 'extends' or 'does not extend beyond the preparation of this application' is marked correctly?", "where_to_verify": "G-28; attorney/accredited representative instructions; case file"},
                {"code": "5.7", "description": "Did you verify the preparer signed Item 8.a in ink?", "where_to_verify": "Original I-765 preparer signature page"},
                {"code": "5.8", "description": "Did you verify the date of signature in Item 8.b is complete and in mm/dd/yyyy?", "where_to_verify": "Original I-765 preparer signature page"},
            ],
        },
        {
            "code": "Part 6",
            "name": "Additional Information",
            "questions": [
                {"code": "6.1", "description": "If Part 6 is used, did you verify the applicant's name and A-Number (if any) appear at the top of the page?", "where_to_verify": "Part 6 entries; additional sheets"},
                {"code": "6.2", "description": "Did you verify each Part 6 entry includes the correct Page Number, Part Number, and Item Number?", "where_to_verify": "Part 6 entries"},
                {"code": "6.3", "description": "Did you verify each explanation is clear, specific, and consistent with the main form?", "where_to_verify": "Part 6; draft packet; declaration; case file"},
                {"code": "6.4", "description": "Did you verify any additional sheets include the applicant's name, A-Number (if any), signature, and date?", "where_to_verify": "Attachments; additional sheets"},
                {"code": "6.5", "description": "Did you verify Part 6 is used only when extra space is actually needed (for example, extra names, countries, or continued responses)?", "where_to_verify": "Main form; Part 6 entries; attachments"},
            ],
        },
    ],
    "reference_sources": {
        "Internal case sources": "Bio Call (BOS); Intake (BOS); BOS notes; case assignment notes; strategy memo; previous docs / prior immigration filings; case file",
        "Identity & civil": "Birth Certificate; Passport; Travel Document; national ID; Social Security card; proof of address; marriage certificate; divorce decree; death certificate, as applicable",
        "Immigration / status": "Form I-94; visa; passport admission stamp; prior EAD card; USCIS Online Account Number; USCIS receipts/notices; Form I-797; FOIA records, as needed",
        "Student / employment / category-specific": "Form I-20; SEVIS records; school documents; employer letter; E-Verify company information; H-1B spouse's I-797/I-129 records; Form I-140 notice; spouse/parent supporting documents, when applicable",
        "Criminal / court (conditional)": "FBI Records; criminal record; court dispositions; police / arrest documents; declaration; Bio Call",
        "Filing / packet components": "Form I-765 draft; Form G-28 (if applicable); Part 6 entries; attachments / additional sheets; cover letter; filing checklist",
    },
}
