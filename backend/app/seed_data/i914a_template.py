"""
I-914A QC Checklist template data.

Current scope: pages 1-12, based on the checklist images provided by the user.
Structure: list of parts, each with optional subparts and questions.
Each question has: code, description, where_to_verify.
"""

I914A_TEMPLATE = {
    "name": "QC Checklist - I-914A",
    "description": "Quality Control checklist for I-914 Supplement A (I-914A) - Application for Derivative T Nonimmigrant Status",
    "parts": [
        {
            "code": "Part 1",
            "name": "Family Member For Whom You Are Filing",
            "questions": [
                {
                    "code": "1",
                    "description": "Did you verify the family member relationship selected in Part 1, Item Number 1 (select only one box): Spouse / Child / Parent / Unmarried Sibling Under 18 Years of Age?",
                    "where_to_verify": "Intake / Bio Call / Birth Certificate(s) / Marriage Certificate (if spouse)",
                },
                {
                    "code": "2",
                    "description": "Did you verify Part 1, Item Number 2 (adult or minor child of one of the family members listed in Item Number 1 who faces a present danger of retaliation) and the selected box (select only one): Child of my spouse / Child of my child (my grandchild) / Child of my parent (my sibling over 18 years of age) / Child of my unmarried sibling under 18 years of age (my niece or nephew)?",
                    "where_to_verify": "Intake / Bio Call / Declaration / Birth Certificate(s)",
                },
            ],
        },
        {
            "code": "Part 2",
            "name": "General Information About You (the principal)",
            "questions": [
                {
                    "code": "1",
                    "description": "Did you verify Part 2, Item Number 1. Full Legal Name?",
                    "where_to_verify": "Birth Certificate / Passport / Form I-914 / Bio Call",
                },
                {
                    "code": "2",
                    "description": "Did you verify Part 2, Item Number 2. Date of Birth (Mmm DD YYYY)?",
                    "where_to_verify": "Birth Certificate / Passport / Form I-914 / Bio Call",
                },
                {
                    "code": "3",
                    "description": "Did you verify Part 2, Item Number 3. Alien Registration Number (A-Number)?",
                    "where_to_verify": "USCIS Notice (I-797) / Form I-914 / Previous Immigration Docs / Intake / Bio Call",
                },
                {
                    "code": "4",
                    "description": "Did you verify Part 2, Item Number 4. Status of your Form I-914, Application for T Nonimmigrant Status (select one): Filing this Form I-914, Supplement A together / Pending / Approved?",
                    "where_to_verify": "USCIS Notice (I-797) / USCIS Online Account / Case File / Intake",
                },
            ],
        },
        {
            "code": "Part 3",
            "name": "Information About Your Family Member (the derivative)",
            "questions": [
                {
                    "code": "1",
                    "description": "Did you verify Part 3, Item Number 1. Your Full Legal Name (the derivative)?",
                    "where_to_verify": "Birth Certificate / Passport / Bio Call / Other ID / Previous Docs",
                },
                {
                    "code": "2",
                    "description": "Did you verify Part 3, Item Number 2. Other Names Used (aliases, maiden names, nicknames, etc.)?",
                    "where_to_verify": "Bio Call / Passport/ID / Previous Docs / FBI Records (if any)",
                },
                {
                    "code": "3",
                    "description": "Did you verify Part 3, Item Number 3. U.S. Physical Address or Intended Physical Address?",
                    "where_to_verify": "Bio Call / Proof of Address / Google Maps / Intake",
                },
                {
                    "code": "4",
                    "description": "Did you verify Part 3, Item Number 4. Safe U.S. Mailing Address (if different from physical address)?",
                    "where_to_verify": "Bio Call / Intake / Proof of Address / Office Address (if used)",
                },
                {
                    "code": "5",
                    "description": "Did you verify Part 3, Item Number 5. Alien Registration Number (A-Number) (if any)?",
                    "where_to_verify": "USCIS Notice (I-797) / Previous Immigration Docs / Intake / Bio Call",
                },
                {
                    "code": "6",
                    "description": "Did you verify Part 3, Item Number 6. USCIS Online Account Number?",
                    "where_to_verify": "USCIS Online Account / Intake / Bio Call",
                },
                {
                    "code": "7",
                    "description": "Did you verify Part 3, Item Number 7. U.S. Social Security Number (SSN) (if any)?",
                    "where_to_verify": "Copy of SS Card / Bio Call / Intake",
                },
                {
                    "code": "8",
                    "description": "Did you verify Part 3, Item Number 8. Sex (Male/Female)?",
                    "where_to_verify": "Birth Certificate / Passport / Bio Call",
                },
                {
                    "code": "9",
                    "description": "Did you verify Part 3, Item Number 9. Marital Status (Single/Never Married / Married / Divorced / Widowed / Annulled)?",
                    "where_to_verify": "Bio Call / Marriage Certificate / Divorce Decree/Death Certificate / Intake",
                },
                {
                    "code": "10",
                    "description": "If applicable, did you verify Part 3, Item Number 10. Prior marriages (names of prior spouses and dates of termination) and that supporting documents (divorce decrees/death certificates) are attached?",
                    "where_to_verify": "Bio Call / Divorce Decree / Death Certificate / Marriage Certificate",
                },
                {
                    "code": "10.A",
                    "description": "Did you verify Part 3, Item Number 10.A. Name of Former Spouse?",
                    "where_to_verify": "Divorce Decree / Marriage Certificate / Bio Call / Other Documents",
                },
                {
                    "code": "10.B",
                    "description": "Did you verify Part 3, Item Number 10.B. Date Marriage Ended (Mmm DD YYYY)?",
                    "where_to_verify": "Divorce Decree / Death Certificate / Bio Call",
                },
                {
                    "code": "10.C",
                    "description": "Did you verify Part 3, Item Number 10.C. Where Marriage Ended (City or Town / State or Province / Country)?",
                    "where_to_verify": "Divorce Decree / Death Certificate / Bio Call",
                },
                {
                    "code": "10.D",
                    "description": "Did you verify Part 3, Item Number 10.D. How Marriage Ended (Annulled / Divorced / Separated / Widowed)?",
                    "where_to_verify": "Divorce Decree / Death Certificate / Bio Call",
                },
                {
                    "code": "11",
                    "description": "Did you verify Part 3, Item Number 11. Date of Birth (Mmm DD YYYY)?",
                    "where_to_verify": "Birth Certificate / Passport / Bio Call",
                },
                {
                    "code": "12",
                    "description": "Did you verify Part 3, Item Number 12. Place of Birth (City or Town / State or Province / Country)?",
                    "where_to_verify": "Birth Certificate / Passport / Bio Call",
                },
                {
                    "code": "13",
                    "description": "Did you verify Part 3, Item Number 13. Country of Citizenship or Nationality?",
                    "where_to_verify": "Passport / Birth Certificate / Bio Call",
                },
                {
                    "code": "14",
                    "description": "Did you verify Part 3, Item Number 14. Passport or Travel Document Number?",
                    "where_to_verify": "Passport/Travel Document / Bio Call",
                },
                {
                    "code": "15",
                    "description": "Did you verify Part 3, Item Number 15. Country That Issued Passport or Travel Document?",
                    "where_to_verify": "Passport/Travel Document / Bio Call",
                },
                {
                    "code": "16",
                    "description": "Did you verify Part 3, Item Number 16. Issued Date for Passport or Travel Document (Mmm DD YYYY)?",
                    "where_to_verify": "Passport/Travel Document / Bio Call",
                },
                {
                    "code": "17",
                    "description": "Did you verify Part 3, Item Number 17. Expiration Date for Passport or Travel Document (Mmm DD YYYY)?",
                    "where_to_verify": "Passport/Travel Document / Bio Call",
                },
                {
                    "code": "18",
                    "description": "Did you verify Part 3, Item Number 18. Current Immigration Status?",
                    "where_to_verify": "Form I-94 / Immigration Docs / FOIA (if any) / Bio Call",
                },
                {
                    "code": "19",
                    "description": "Did you verify Part 3, Item Number 19. Is your family member currently living in the United States? (Yes/No)",
                    "where_to_verify": "Bio Call / Intake / Proof of Address / Travel Records",
                },
                {
                    "code": "20.A",
                    "description": "If applicable, did you verify Part 3, Item Number 20.A. Place of Last Entry (City or Town / State)?",
                    "where_to_verify": "Form I-94 / Passport Stamps / FOIA/CBP (if any) / Bio Call",
                },
                {
                    "code": "20.B",
                    "description": "If applicable, did you verify Part 3, Item Number 20.B. Date of Last Entry (Mmm DD YYYY)?",
                    "where_to_verify": "Form I-94 / Passport Stamps / FOIA/CBP (if any) / Bio Call",
                },
                {
                    "code": "20.C",
                    "description": "If applicable, did you verify Part 3, Item Number 20.C. Form I-94 Arrival-Departure Record Number?",
                    "where_to_verify": "Form I-94 / FOIA/CBP (if any) / Bio Call",
                },
                {
                    "code": "21.A",
                    "description": "If applicable (family member outside the U.S.), did you verify Part 3, Item Number 21.A. Type of Office (Select one): Consulate / Pre-flight Inspection Facility / Port of Entry?",
                    "where_to_verify": "Bio Call / Intake / Consular Preference",
                },
                {
                    "code": "21.B",
                    "description": "If applicable, did you verify Part 3, Item Number 21.B. City or Town?",
                    "where_to_verify": "Bio Call / Intake",
                },
                {
                    "code": "21.C",
                    "description": "If applicable, did you verify Part 3, Item Number 21.C. U.S. State or Foreign Country?",
                    "where_to_verify": "Bio Call / Intake",
                },
                {
                    "code": "21.D",
                    "description": "If applicable, did you verify Part 3, Item Number 21.D. Foreign Address Where You Want Notification Sent?",
                    "where_to_verify": "Bio Call / Intake / Proof of Address (if available)",
                },
                {
                    "code": "22.A",
                    "description": "If applicable (previous travel to the U.S.), did you verify Part 3, Item Number 22.A. Place of Entry (City or Town / State)?",
                    "where_to_verify": "Form I-94 / Passport Stamps / FOIA/CBP (if any) / Bio Call",
                },
                {
                    "code": "22.B",
                    "description": "If applicable, did you verify Part 3, Item Number 22.B. Date of Entry (Mmm DD YYYY)?",
                    "where_to_verify": "Form I-94 / Passport Stamps / FOIA/CBP (if any) / Bio Call",
                },
                {
                    "code": "22.C",
                    "description": "If applicable, did you verify Part 3, Item Number 22.C. Date Authorized Stay Expired (Mmm DD YYYY)?",
                    "where_to_verify": "Form I-94 / USCIS/CBP Records / FOIA (if any) / Bio Call",
                },
                {
                    "code": "22.D",
                    "description": "If applicable, did you verify Part 3, Item Number 22.D. Immigration Status?",
                    "where_to_verify": "Form I-94 / Visa/Entry Docs / FOIA (if any) / Bio Call",
                },
                {
                    "code": "23",
                    "description": "Did you verify Part 3, Item Number 23. Has your family member ever been in immigration court proceedings? (Yes/No)",
                    "where_to_verify": "EOIR Portal/ICE / FOIA (if any) / Intake / Bio Call",
                },
                {
                    "code": "24.A",
                    "description": "If applicable, did you verify Part 3, Item Number 24.A. Removal Date (Mmm DD YYYY)?",
                    "where_to_verify": "EOIR/ICE Records / FOIA (if any) / Court Documents / Bio Call",
                },
                {
                    "code": "24.B",
                    "description": "If applicable, did you verify Part 3, Item Number 24.B. Exclusion Date (Mmm DD YYYY)?",
                    "where_to_verify": "EOIR/ICE Records / FOIA (if any) / Court Documents / Bio Call",
                },
                {
                    "code": "24.C",
                    "description": "If applicable, did you verify Part 3, Item Number 24.C. Deportation Date (Mmm DD YYYY)?",
                    "where_to_verify": "EOIR/ICE Records / FOIA (if any) / Court Documents / Bio Call",
                },
                {
                    "code": "24.D",
                    "description": "If applicable, did you verify Part 3, Item Number 24.D. Recission Date (Mmm DD YYYY)?",
                    "where_to_verify": "EOIR/ICE Records / FOIA (if any) / Court Documents / Bio Call",
                },
                {
                    "code": "24.E",
                    "description": "If applicable, did you verify Part 3, Item Number 24.E. Next Hearing Date (Mmm DD YYYY)?",
                    "where_to_verify": "EOIR Portal/ICE / Court Notice / FOIA (if any) / Bio Call",
                },
                {
                    "code": "25",
                    "description": "Did you verify Part 3, Item Number 25. Is your family member requesting an Employment Authorization Document? (Yes/No)",
                    "where_to_verify": "Bio Call / Intake / Form I-765 (if filing) / Case Strategy",
                },
            ],
        },
        {
            "code": "Part 4",
            "name": "Processing Information",
            "questions": [
                {
                    "code": "1.A",
                    "description": "Did you verify whether the family member for whom you are filing has committed a crime or offense for which they have not been arrested?",
                    "where_to_verify": "Intake / Bio Call / Declaration / Affidavit / Criminal Record / FBI",
                },
                {
                    "code": "1.B",
                    "description": "Did you verify whether the family member for whom you are filing has been arrested, cited, or detained by any law enforcement officer (including DHS/INS/military) for any reason?",
                    "where_to_verify": "Intake / Bio Call / Declaration / Criminal Record / FBI / FOIA (as needed)",
                },
                {
                    "code": "1.C",
                    "description": "Did you verify whether the family member for whom you are filing has been charged with committing any crime or offense?",
                    "where_to_verify": "Court Disposition / Criminal Record / FOIA / FBI",
                },
                {
                    "code": "1.D",
                    "description": "Did you verify whether the family member for whom you are filing has been convicted of a crime or offense (even if subsequently expunged or pardoned)?",
                    "where_to_verify": "Outcome / Court Disposition / Criminal Record / FBI",
                },
                {
                    "code": "1.E",
                    "description": "Did you verify whether the family member for whom you are filing has been placed in an alternative sentencing or rehabilitative program (diversion, deferred prosecution, withheld adjudication, deferred adjudication)?",
                    "where_to_verify": "Court Disposition / FOIA / FBI",
                },
                {
                    "code": "1.F",
                    "description": "Did you verify whether the family member for whom you are filing has received a suspended sentence, been placed on probation, or been paroled?",
                    "where_to_verify": "Court Disposition / FOIA / Declaration / FBI",
                },
                {
                    "code": "1.G",
                    "description": "Did you verify whether the family member for whom you are filing has been in jail or prison?",
                    "where_to_verify": "Bio Call / Affidavit / Court Disposition / Intake / FBI / Declaration",
                },
                {
                    "code": "1.H",
                    "description": "Did you verify whether the family member for whom you are filing has been the beneficiary of a pardon, amnesty, rehabilitation, or other act of clemency or similar action?",
                    "where_to_verify": "Official Documents / Court Record / FBI / Bio Call",
                },
                {
                    "code": "1.I",
                    "description": "Did you verify whether the family member for whom you are filing has exercised diplomatic immunity to avoid prosecution for a criminal offense in the United States?",
                    "where_to_verify": "Intake / Declaration / Bio Call / Any Documentation / FBI",
                },
                {
                    "code": "1.Table",
                    "description": "If you answered \"Yes\" to any part of Item Number 1, did you verify the incident table is completed (why / date / where / outcome) and any required explanation is included in Part 8?",
                    "where_to_verify": "Court Disposition / Criminal Record / FOIA (as needed) / FBI / Part 8 Explanation",
                },
                {
                    "code": "2.A",
                    "description": "Did you verify whether the family member for whom you are filing has engaged in prostitution or procurement of prostitution or intends to engage in prostitution or procurement of prostitution?",
                    "where_to_verify": "Intake / Bio Call / FBI / Criminal Record / Declaration",
                },
                {
                    "code": "2.B",
                    "description": "Did you verify whether the family member for whom you are filing has EVER engaged in any unlawful commercialized vice, including but not limited to illegal gambling?",
                    "where_to_verify": "Intake / Declaration / Criminal Record / FBI",
                },
                {
                    "code": "2.C",
                    "description": "Did you verify whether the family member for whom you are filing has EVER knowingly encouraged, induced, assisted, abetted, or aided any alien to try to enter the United States illegally?",
                    "where_to_verify": "Declaration / FOIA/CBP (if needed) / Bio Call / FBI",
                },
                {
                    "code": "2.D",
                    "description": "Did you verify whether the family member for whom you are filing has EVER illicitly trafficked in any controlled substance, or knowingly assisted, abetted, or colluded in the illicit trafficking of any controlled substance?",
                    "where_to_verify": "Bio Call / FBI / FOIA / Criminal Record / Court Disposition / Part 8 Explanation",
                },
                {
                    "code": "3.A",
                    "description": "Did you verify whether the family member for whom you are filing has EVER committed, planned or prepared, participated in, threatened to, attempted to, or conspired to commit, gathered information for, or solicited funds for hijacking or sabotage of any conveyance (aircraft, vessel, or vehicle)?",
                    "where_to_verify": "Intake / FOIA (if any) / Declaration / Bio Call",
                },
                {
                    "code": "3.B",
                    "description": "Did you verify whether the family member for whom you are filing has EVER committed, planned or prepared, participated in, threatened to, attempted to, or conspired to commit, gathered information for, or solicited funds for seizing or detaining (and threatening to kill/injure/continue to detain) an individual to compel a third person/governmental organization?",
                    "where_to_verify": "Intake / FOIA / Declaration / Bio Call",
                },
                {
                    "code": "3.C",
                    "description": "Did you verify whether the family member for whom you are filing has EVER committed, planned or prepared, participated in, threatened to, attempted to, or conspired to commit, gathered information for, or solicited funds for assassination?",
                    "where_to_verify": "Intake / FBI / Bio Call / Declaration / FOIA (if any)",
                },
                {
                    "code": "3.D",
                    "description": "Did you verify whether the family member for whom you are filing has EVER committed, planned or prepared, participated in, threatened to, attempted to, or conspired to commit, gathered information for, or solicited funds for the use of any firearm with intent to endanger safety or cause substantial property damage?",
                    "where_to_verify": "Intake / FOIA / Declaration / Criminal Record (if any) / Bio Call / FBI",
                },
                {
                    "code": "3.E",
                    "description": "Did you verify whether the family member for whom you are filing has EVER committed, planned or prepared, participated in, threatened to, attempted to, or conspired to commit, gathered information for, or solicited funds for the use of any biological/chemical agent; nuclear weapon/device; explosive; or other dangerous device with intent to endanger safety or cause substantial property damage?",
                    "where_to_verify": "Intake / FOIA / FBI / Bio Call",
                },
                {
                    "code": "4.A",
                    "description": "Did you verify whether the family member for whom you are filing has EVER been a member of, solicited money/members for, provided support for, attended military training by or on behalf of, or been associated with an organization designated as a terrorist organization under INA section 219?",
                    "where_to_verify": "Intake / FOIA / Declaration / FBI / Bio Call",
                },
                {
                    "code": "4.B(1)",
                    "description": "Did you verify whether the family member for whom you are filing has EVER been associated with any other group of two or more individuals that has engaged in hijacking or sabotage of any conveyance (aircraft, vessel, or vehicle)?",
                    "where_to_verify": "Intake / FOIA / FBI / Bio Call",
                },
                {
                    "code": "4.B(2)",
                    "description": "Did you verify whether the family member for whom you are filing has EVER been associated with any other group of two or more individuals that has engaged in seizing or detaining (and threatening to kill/injure/continue to detain) an individual to compel a third person/governmental organization?",
                    "where_to_verify": "Intake / FOIA / FBI / Bio Call",
                },
                {
                    "code": "4.B(3)",
                    "description": "Did you verify whether the family member for whom you are filing has EVER been associated with any other group of two or more individuals that has engaged in assassination?",
                    "where_to_verify": "Intake / FOIA / FBI / Bio Call",
                },
                {
                    "code": "4.B(4)",
                    "description": "Did you verify whether the family member for whom you are filing has EVER been associated with any other group of two or more individuals that has engaged in the use of any firearm with intent to endanger safety or cause substantial property damage?",
                    "where_to_verify": "Intake / FOIA / FBI / Bio Call",
                },
                {
                    "code": "4.B(5)",
                    "description": "Did you verify whether the family member for whom you are filing has EVER been associated with any other group of two or more individuals that has engaged in soliciting money/members or otherwise providing material support to a terrorist organization?",
                    "where_to_verify": "Intake / FOIA / FBI / Bio Call",
                },
                {
                    "code": "4.B(6)",
                    "description": "Did you verify whether the family member for whom you are filing has EVER been associated with any other group of two or more individuals that has engaged in the use of any biological/chemical agent; nuclear weapon/device; explosive; or other dangerous device with intent to endanger safety or cause substantial property damage?",
                    "where_to_verify": "Intake / FOIA / FBI / Bio Call",
                },
                {
                    "code": "5.A",
                    "description": "Did you verify whether the family member for whom you are filing intends to engage in the United States in espionage?",
                    "where_to_verify": "FBI / Bio Call",
                },
                {
                    "code": "5.B",
                    "description": "Did you verify whether the family member for whom you are filing intends to engage in the United States in any unlawful activity, or any activity the purpose of which is in opposition to control or overthrow of the Government of the United States?",
                    "where_to_verify": "Intake / FBI / Bio Call",
                },
                {
                    "code": "5.C",
                    "description": "Did you verify whether the family member for whom you are filing intends to engage in the United States solely, principally, or incidentally in any activity related to espionage or sabotage or to violate any law involving the export of goods, technology, or sensitive information?",
                    "where_to_verify": "Intake / FBI / Bio Call",
                },
                {
                    "code": "6",
                    "description": "Did you verify whether the family member for whom you are filing has EVER been or continues to be a member of the Communist or other totalitarian party (except when membership was involuntary)?",
                    "where_to_verify": "Intake / Country History / Personal History / Bio Call",
                },
                {
                    "code": "7",
                    "description": "Did you verify whether the family member for whom you are filing, during March 23, 1933 to May 8, 1945, in association with the Nazi Government of Germany (or associated/allied organization), ever ordered, incited, assisted, or otherwise participated in persecution because of race, religion, nationality, membership in a particular social group, or political opinion?",
                    "where_to_verify": "Country History / Personal History / Intake / Bio Call",
                },
                {
                    "code": "8.A",
                    "description": "Did you verify whether the family member for whom you are filing has EVER been present or nearby when any person was intentionally killed, tortured, beaten, or injured?",
                    "where_to_verify": "Intake / Personal History / Declaration / Bio Call",
                },
                {
                    "code": "8.B",
                    "description": "Did you verify whether the family member for whom you are filing has EVER been present or nearby when any person was displaced or moved from their residence by force, compulsion, or duress?",
                    "where_to_verify": "Intake / Country History / Declaration / Bio Call",
                },
                {
                    "code": "8.C",
                    "description": "Did you verify whether the family member for whom you are filing has EVER been present or nearby when any person was compelled or forced to engage in any kind of sexual contact or relations?",
                    "where_to_verify": "Intake / Personal History / Declaration / Bio Call",
                },
                {
                    "code": "9.A",
                    "description": "Did you verify whether removal, exclusion, rescission, or deportation proceedings are pending against the family member for whom you are filing?",
                    "where_to_verify": "FOIA / Intake / Bio Call / EOIR Portal/ICE",
                },
                {
                    "code": "9.B",
                    "description": "Did you verify whether removal, exclusion, rescission, or deportation proceedings have EVER been initiated against the family member for whom you are filing?",
                    "where_to_verify": "FOIA / Intake / Bio Call / EOIR Portal/ICE",
                },
                {
                    "code": "9.C",
                    "description": "Did you verify whether the family member for whom you are filing has EVER been removed, excluded, or deported from the United States?",
                    "where_to_verify": "FOIA/CBP / FBI / Intake / Bio Call",
                },
                {
                    "code": "9.D",
                    "description": "Did you verify whether the family member for whom you are filing has EVER been ordered to be removed, excluded, or deported from the United States?",
                    "where_to_verify": "EOIR Portal/ICE / FBI / Intake / Bio Call",
                },
                {
                    "code": "9.E",
                    "description": "Did you verify whether the family member for whom you are filing has EVER been denied a visa or denied admission to the United States?",
                    "where_to_verify": "Client Documents / Declaration / FOIA (as needed) / Bio Call",
                },
                {
                    "code": "9.F",
                    "description": "Did you verify whether the family member for whom you are filing has EVER been granted voluntary departure by an immigration officer or immigration judge and failed to depart within the allotted time?",
                    "where_to_verify": "FOIA/EOIR / EOIR Portal / Intake / Bio Call",
                },
                {
                    "code": "10.A",
                    "description": "Did you verify whether the family member for whom you are filing (or any member of their family) has EVER ordered, incited, called for, committed, assisted, helped with, or otherwise participated in acts involving torture or genocide?",
                    "where_to_verify": "Personal History / Country History / Bio Call / ICE/EOIR (if any)",
                },
                {
                    "code": "10.B",
                    "description": "Did you verify whether the family member for whom you are filing (or any member of their family) has EVER ordered, incited, called for, committed, assisted, helped with, or otherwise participated in killing any person?",
                    "where_to_verify": "Personal History / Intake / FBI / Bio Call",
                },
                {
                    "code": "10.C",
                    "description": "Did you verify whether the family member for whom you are filing (or any member of their family) has EVER ordered, incited, called for, committed, assisted, helped with, or otherwise participated in intentionally and severely injuring any person?",
                    "where_to_verify": "Personal History / Intake / FBI / Bio Call",
                },
                {
                    "code": "10.D",
                    "description": "Did you verify whether the family member for whom you are filing (or any member of their family) has EVER ordered, incited, called for, committed, assisted, helped with, or otherwise participated in engaging in sexual contact/relations with any person who was being forced or threatened?",
                    "where_to_verify": "Personal History / Intake / FBI / Bio Call",
                },
                {
                    "code": "10.E",
                    "description": "Did you verify whether the family member for whom you are filing (or any member of their family) has EVER ordered, incited, called for, committed, assisted, helped with, or otherwise participated in limiting or denying any person's ability to exercise religious beliefs?",
                    "where_to_verify": "Country History / Personal History / Bio Call / FBI",
                },
                {
                    "code": "11.A",
                    "description": "Did you verify whether the family member for whom you are filing has EVER served in, been a member of, assisted in, or participated in any military/paramilitary/police/self-defense/vigilante/rebel/guerrilla/militia/insurgent organization?",
                    "where_to_verify": "Intake / Personal/Country History / FBI / Bio Call",
                },
                {
                    "code": "11.B",
                    "description": "Did you verify whether the family member for whom you are filing has EVER served in any prison, jail/prison camp/detention facility/labor camp, or any situation involving detaining persons?",
                    "where_to_verify": "Intake / Personal History / FBI / Bio Call",
                },
                {
                    "code": "12",
                    "description": "Did you verify whether the family member for whom you are filing has EVER been a member of, assisted in, or participated in any group/unit/organization in which they or any other persons used any type of weapon against any person or threatened to do so?",
                    "where_to_verify": "Intake / Personal History / FBI / Bio Call",
                },
                {
                    "code": "13",
                    "description": "Did you verify whether the family member for whom you are filing has EVER assisted or participated in selling/providing weapons to any person who (to their knowledge) used them against another person, or in transporting weapons to any person who (to their knowledge) used them against another person?",
                    "where_to_verify": "Intake / Personal History / FBI / Bio Call",
                },
                {
                    "code": "14",
                    "description": "Did you verify whether the family member for whom you are filing has EVER received any type of military, paramilitary, or weapons training?",
                    "where_to_verify": "FBI / Bio Call / Intake / Personal History",
                },
                {
                    "code": "15",
                    "description": "Did you verify whether the family member for whom you are filing is under a final order or civil penalty for violating INA section 274C (producing and/or using false documentation to unlawfully satisfy a requirement of the INA)?",
                    "where_to_verify": "Client Documents / Prior Filings / FOIA / Declaration / Bio Call",
                },
                {
                    "code": "16",
                    "description": "Did you verify whether the family member for whom you are filing has EVER, by fraud or willful misrepresentation of a material fact, sought to procure or procured a visa/other documentation for entry or any immigration benefit?",
                    "where_to_verify": "FOIA / FBI / Bio Call / Prior Filings / Declaration",
                },
                {
                    "code": "17",
                    "description": "Did you verify whether the family member for whom you are filing has EVER left the United States to avoid being drafted into the U.S. Armed Forces?",
                    "where_to_verify": "Intake / Personal History / FBI / Bio Call",
                },
                {
                    "code": "18",
                    "description": "Did you verify whether the family member for whom you are filing has EVER detained, retained, or withheld custody of a child (with a lawful claim to U.S. citizenship) outside the United States from a U.S. citizen granted custody?",
                    "where_to_verify": "FBI / Bio Call / Intake / Court Records / Declaration",
                },
                {
                    "code": "19",
                    "description": "Did you verify whether the family member for whom you are filing plans to practice polygamy in the United States?",
                    "where_to_verify": "Intake / Declaration / Bio Call",
                },
                {
                    "code": "20",
                    "description": "Did you verify whether the family member for whom you are filing entered the United States as a stowaway?",
                    "where_to_verify": "Declaration / FOIA/CBP / Intake / Bio Call",
                },
                {
                    "code": "21.A",
                    "description": "Did you verify whether the family member for whom you are filing has a communicable disease of public health significance?",
                    "where_to_verify": "Medical Records / Declaration / Bio Call",
                },
                {
                    "code": "21.B",
                    "description": "Did you verify whether the family member for whom you are filing has (or had) a physical or mental disorder and behavior (or history of behavior likely to recur) associated with the disorder that has posed or may pose a threat to property, safety, or welfare of themselves or others?",
                    "where_to_verify": "Medical Evaluation / Bio Call / Declaration",
                },
                {
                    "code": "21.C",
                    "description": "Did you verify whether the family member for whom you are filing is now or has been a drug abuser or drug addict?",
                    "where_to_verify": "Medical Evaluation / Medical Records / Bio Call / Declaration",
                },
            ],
        },
        {
            "code": "Part 5",
            "name": "Applicant's Statement, Contact Information, Declaration, Certification, and Signature",
            "questions": [
                {
                    "code": "1.A",
                    "description": "Did you verify Part 5, Item Number 1.A. Applicant's Statement Regarding the Interpreter: \"I can read and understand English, and I have read and understand every question and instruction on this application and my answer to every question.\"",
                    "where_to_verify": "Bio Call / Intake / Client Confirmation",
                },
                {
                    "code": "1.B",
                    "description": "If applicable, did you verify Part 5, Item Number 1.B. Applicant's Statement Regarding the Interpreter: \"The interpreter named in Part 6 read to me every question and instruction...\" and the language line is completed?",
                    "where_to_verify": "Bio Call / Interpreter Info (Part 6) / Client Confirmation / BOS",
                },
                {
                    "code": "2",
                    "description": "If applicable, did you verify Part 5, Item Number 2. Applicant's Statement Regarding the Preparer and the preparer name line is completed (preparer named in Part 7)?",
                    "where_to_verify": "Bio Call / Preparer Info (Part 7) / Client Confirmation / BOS",
                },
                {
                    "code": "3",
                    "description": "Did you verify Part 5, Item Number 3. Applicant's Daytime Telephone Number?",
                    "where_to_verify": "Intake / Bio Call / BOS",
                },
                {
                    "code": "4",
                    "description": "Did you verify Part 5, Item Number 4. Applicant's Mobile Telephone Number (if any)?",
                    "where_to_verify": "Intake / Bio Call / BOS",
                },
                {
                    "code": "5",
                    "description": "Did you verify Part 5, Item Number 5. Applicant's Email Address (if any)?",
                    "where_to_verify": "Intake / Bio Call / BOS",
                },
                {
                    "code": "6",
                    "description": "Did you verify Part 5, Item Number 6. Applicant's Signature and Date of Signature (Mmm DD YYYY), and that it is signed in ink?",
                    "where_to_verify": "Original Signed Form I-914A / Client Confirmation / Case File",
                },
                {
                    "code": "6.Phone",
                    "description": "Did you verify Part 5 (Applicant's Signature section). Applicant's Phone Number (if any) and Applicant's Safe Phone Number (if any)?",
                    "where_to_verify": "Intake / Bio Call / BOS",
                },
                {
                    "code": "7",
                    "description": "If applicable, did you verify Part 5, Item Number 7. Signature of Family Member (the family member for whom you are filing if he or she is physically present in the United States) and Date of Signature (Mmm DD YYYY)?",
                    "where_to_verify": "Original Signed Form I-914A / Bio Call / Client Confirmation",
                },
            ],
        },
        {
            "code": "Part 6",
            "name": "Interpreter's Contact Information, Certification, and Signature",
            "questions": [
                {
                    "code": "1",
                    "description": "Did you verify Part 6, Item Number 1. Interpreter's Full Name (Family Name and Given Name)?",
                    "where_to_verify": "BOS / Interpreter ID (if available) / Case File",
                },
                {
                    "code": "2",
                    "description": "Did you verify Part 6, Item Number 2. Interpreter's Business or Organization Name (if any)?",
                    "where_to_verify": "BOS / Case File",
                },
                {
                    "code": "3",
                    "description": "Did you verify Part 6, Item Number 3. Interpreter's Mailing Address?",
                    "where_to_verify": "BOS / Case File / Interpreter Confirmation",
                },
                {
                    "code": "4",
                    "description": "Did you verify Part 6, Item Number 4. Interpreter's Daytime Telephone Number?",
                    "where_to_verify": "BOS / Interpreter Confirmation",
                },
                {
                    "code": "5",
                    "description": "Did you verify Part 6, Item Number 5. Interpreter's Mobile Telephone Number (if any)?",
                    "where_to_verify": "BOS / Interpreter Confirmation",
                },
                {
                    "code": "6",
                    "description": "Did you verify Part 6, Item Number 6. Interpreter's Email Address (if any)?",
                    "where_to_verify": "BOS / Interpreter Confirmation",
                },
                {
                    "code": "7",
                    "description": "Did you verify Part 6, Item Number 7. Interpreter's Signature and Date of Signature (Mmm DD YYYY), and that it is signed in ink?",
                    "where_to_verify": "Original Signed Form I-914A / Case File",
                },
            ],
        },
        {
            "code": "Part 7",
            "name": "Contact Information, Declaration, and Signature of the Person Preparing this Application, if Other Than the Applicant",
            "questions": [
                {
                    "code": "1",
                    "description": "Did you verify Part 7, Item Number 1. Preparer's Full Name (Family Name and Given Name)?",
                    "where_to_verify": "BOS / Case File / Form G-28 (if applicable)",
                },
                {
                    "code": "2",
                    "description": "Did you verify Part 7, Item Number 2. Preparer's Business or Organization Name (if any)?",
                    "where_to_verify": "BOS / Case File",
                },
                {
                    "code": "3",
                    "description": "Did you verify Part 7, Item Number 3. Preparer's Mailing Address?",
                    "where_to_verify": "BOS / Case File",
                },
                {
                    "code": "4",
                    "description": "Did you verify Part 7, Item Number 4. Preparer's Daytime Telephone Number?",
                    "where_to_verify": "BOS / Case File",
                },
                {
                    "code": "5",
                    "description": "Did you verify Part 7, Item Number 5. Preparer's Mobile Telephone Number (if any)?",
                    "where_to_verify": "BOS / Case File",
                },
                {
                    "code": "6",
                    "description": "Did you verify Part 7, Item Number 6. Preparer's Email Address (if any)?",
                    "where_to_verify": "BOS / Case File",
                },
                {
                    "code": "7.A",
                    "description": "Did you verify Part 7, Item Number 7.A. Preparer's Statement: \"I am not an attorney or accredited representative but have prepared this application...\" (if applicable)?",
                    "where_to_verify": "Case File / BOS",
                },
                {
                    "code": "7.B",
                    "description": "If applicable, did you verify Part 7, Item Number 7.B. Preparer's Statement: \"I am an attorney or accredited representative...\" and the representation box (extends / does not extend) is selected correctly? (Form G-28 may be required.)",
                    "where_to_verify": "Form G-28 / Attorney/Rep Info / BOS / Case File",
                },
                {
                    "code": "8",
                    "description": "Did you verify Part 7, Item Number 8. Preparer's Signature and Date of Signature (Mmm DD YYYY), and that it is signed in ink?",
                    "where_to_verify": "Original Signed Form I-914A / Case File",
                },
            ],
        },
        {
            "code": "Part 8",
            "name": "Additional Information",
            "questions": [
                {
                    "code": "1",
                    "description": "Did you verify Part 8, Item Number 1. Family Name (Last Name), Given Name (First Name), and Middle Name?",
                    "where_to_verify": "Form I-914A / Case File",
                },
                {
                    "code": "2",
                    "description": "Did you verify Part 8, Item Number 2. A-Number?",
                    "where_to_verify": "Form I-914A / USCIS Notice (I-797) / Case File",
                },
                {
                    "code": "3",
                    "description": "Did you verify Part 8, Item Number 3. Page Number / Part Number / Item Number are provided, and the additional information is written clearly?",
                    "where_to_verify": "Part 8 Entry / Draft Form I-914A / Case File",
                },
                {
                    "code": "4",
                    "description": "Did you verify Part 8, Item Number 4. Page Number / Part Number / Item Number are provided, and the additional information is written clearly?",
                    "where_to_verify": "Part 8 Entry / Draft Form I-914A / Case File",
                },
                {
                    "code": "5",
                    "description": "Did you verify Part 8, Item Number 5. Page Number / Part Number / Item Number are provided, and the additional information is written clearly?",
                    "where_to_verify": "Part 8 Entry / Draft Form I-914A / Case File",
                },
                {
                    "code": "6",
                    "description": "Did you verify Part 8, Item Number 6. Page Number / Part Number / Item Number are provided, and the additional information is written clearly?",
                    "where_to_verify": "Part 8 Entry / Draft Form I-914A / Case File",
                },
            ],
        },
    ],
}
