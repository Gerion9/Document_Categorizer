"""
I-914 QC Checklist template data.

Structure: list of parts, each with optional subparts and questions.
Each question has: code, description, where_to_verify.
"""

I914_TEMPLATE = {
    "name": "QC Checklist – I-914 (T-1)",
    "description": "Quality Control checklist for I-914 Application for T Nonimmigrant Status",
    "parts": [
        {
            "code": "Part 1",
            "name": "I-914 Part 1",
            "questions": [
                {"code": "1", "description": "Did you verify that the A or B square are proper check according to the case?", "where_to_verify": "BIO CALL / INTAKE / PREVIOUS DOCS"},
            ],
        },
        {
            "code": "Part 2",
            "name": "I-914 Part 2",
            "questions": [
                {"code": "2", "description": "Did you verify the applicant's full legal name?", "where_to_verify": "Birth Cert / Passport / I-94"},
                {"code": "3", "description": "Did you verify other names used?", "where_to_verify": "Intake / Bio Call / Passport"},
                {"code": "4", "description": "Did you verify the USCIS Online Account Number?", "where_to_verify": "Bio Call"},
                {"code": "5", "description": "Did you verify the A-Number?", "where_to_verify": "FOIA / Previous docs / I-94"},
                {"code": "6", "description": "Did you verify the U.S. Social Security Number?", "where_to_verify": "Intake / Bio Call"},
                {"code": "7", "description": "Did you verify the I-94 Arrival-Departure Record Number?", "where_to_verify": "I-94 / CBP"},
                {"code": "8", "description": "Did you verify Sex?", "where_to_verify": "Birth Cert / Passport"},
                {"code": "9", "description": "Did you verify Marital Status?", "where_to_verify": "Intake/Bio Call / Marriage Cert"},
                {"code": "10", "description": "Did you verify Date of Birth? *Remember to use the proper format (mm/dd/yyyy)", "where_to_verify": "Birth Cert / Passport"},
            ],
        },
        {
            "code": "Part 3",
            "name": "I-914 Part 3",
            "questions": [
                {"code": "3.1", "description": "Did you verify whether the applicant has been a victim of a severe form of trafficking in persons?", "where_to_verify": "Intake; Bio Call; Declaration"},
                {"code": "3.2.A", "description": "Did you verify whether the applicant cooperated with reasonable requests for assistance from law enforcement?", "where_to_verify": "LEA Report"},
                {"code": "3.2.B", "description": "Did you verify whether the applicant due to their age or the trauma has suffered, and is exempt from the requirement to cooperate with reasonable requests for assistance from law enforcement?", "where_to_verify": "Intake; Bio Call; Declaration; Birth Certificate"},
                {"code": "3.3", "description": "Did you verify whether the applicant is physically present in the United States, American Samoa, or the Commonwealth of the Northern Mariana Islands, or at a port of entry, on account of trafficking?", "where_to_verify": "Intake; Bio Call"},
                {"code": "3.4", "description": "Did you verify whether the applicant fears that they will suffer extreme hardship involving unusual and severe harm upon removal?", "where_to_verify": "Intake; Declaration"},
                {"code": "3.5", "description": "Did you verify whether the applicant has reported the trafficking crime of which they are claiming to be a victim?", "where_to_verify": "LEA Report; Police Report"},
                {"code": "3.6", "description": "Did you verify whether they were under 18 years of age at the time at least one of the acts of trafficking occurred?", "where_to_verify": "Intake; Declaration"},
                {"code": "3.7", "description": "Did you verify whether the applicant has complied with reasonable requests from Federal, State, Tribal, or local law enforcement authorities for assistance in the investigation or prosecution of acts of trafficking?", "where_to_verify": "LEA Report"},
                {"code": "3.8", "description": "Did you verify whether this is the applicant's first time they have entered the United States?", "where_to_verify": "Intake; Bio Call; Declaration; FBI; FOIA"},
                {"code": "3.9", "description": "Did you verify whether the applicant's most recent entry was on account of the trafficking that forms the basis for the claim?", "where_to_verify": "Intake; Bio Call; Declaration"},
                {"code": "3.10", "description": "Did you verify whether the applicant is requesting an Employment Authorization Document (EAD) when granted T nonimmigrant status?", "where_to_verify": "Verify to answer YES Form I-765"},
                {"code": "3.11", "description": "Did you verify whether the applicant is now applying for one or more eligible family members?", "where_to_verify": "Contract"},
            ],
        },
        {
            "code": "Part 4",
            "name": "I-914 Part 4 – Processing Information",
            "subparts": [
                {
                    "code": "4.1",
                    "name": "Criminal / Law Enforcement (including DHS/INS/military)",
                    "questions": [
                        {"code": "4.1.A", "description": "Did you verify whether the applicant has committed a crime or offense for which they have not been arrested?", "where_to_verify": "Intake; Bio Call; Declaration/Affidavit; Criminal Record; FBI"},
                        {"code": "4.1.B", "description": "Did you verify whether the applicant has been arrested, cited, or detained by any law enforcement officer for any reason?", "where_to_verify": "Intake; Bio Call; Declaration; Criminal record; FBI; FOIA"},
                        {"code": "4.1.C", "description": "Did you verify whether the applicant has been charged with committing any crime or offense?", "where_to_verify": "Court disposition; Criminal record; FOIA"},
                        {"code": "4.1.D", "description": "Did you verify whether the applicant has been convicted of a crime or offense (even if later expunged or pardoned)?", "where_to_verify": "Outcome; Court disposition; Criminal record; FBI"},
                        {"code": "4.1.E", "description": "Did you verify whether the applicant has been placed in alternative sentencing / rehabilitative programs?", "where_to_verify": "Court disposition; FOIA"},
                        {"code": "4.2.A", "description": "Did you verify whether the applicant has received a suspended sentence, been placed on probation, or been paroled?", "where_to_verify": "Court disposition; FOIA; Declaration"},
                        {"code": "4.2.B", "description": "Did you verify whether the applicant has been in jail or prison?", "where_to_verify": "Declaration/Affidavit; Intake; Bio Call; FBI; Court dispositions"},
                        {"code": "4.2.C", "description": "Did you verify whether the applicant has been the beneficiary of a pardon, amnesty, rehabilitation, clemency, or similar action?", "where_to_verify": "Official documents; Court record"},
                        {"code": "4.2.D", "description": "Did you verify whether the applicant has exercised diplomatic immunity to avoid prosecution for a criminal offense in the U.S.?", "where_to_verify": "Intake; Declaration; any documentation"},
                        {"code": "4.2.E", "description": "If any of 4.1.A-4.1.I is Yes, did you verify the incident table is completed (date/place/why/outcome)?", "where_to_verify": "Part 9 incident table; dispositions/FOIA"},
                    ],
                },
                {
                    "code": "4.2",
                    "name": "Prostitution / Vice / Smuggling / Drug trafficking",
                    "questions": [
                        {"code": "4.2.A", "description": "Did you verify whether the applicant has engaged in prostitution or procurement of prostitution, or intends to engage?", "where_to_verify": "Intake; Bio Call; Declaration; Criminal record"},
                        {"code": "4.2.B", "description": "Did you verify whether the applicant has engaged in unlawful commercialized vice (including illegal gambling)?", "where_to_verify": "Intake; Declaration; Criminal record"},
                        {"code": "4.2.C", "description": "Did you verify whether the applicant has knowingly encouraged/induced/assisted/abetted/aided any alien to try to enter the U.S. illegally?", "where_to_verify": "Declaration; FOIA CBP; Intake"},
                        {"code": "4.2.D", "description": "Did you verify whether the applicant has illicitly trafficked in any controlled substance?", "where_to_verify": "Criminal record; Court disposition; FOIA; Intake"},
                    ],
                },
                {
                    "code": "4.3",
                    "name": "Security / Terrorism / Espionage / Political / Communist / Nazi persecution",
                    "subparts": [
                        {
                            "code": "4.3.1",
                            "name": "Acts (hijacking/hostage/assassination/firearms/WMD)",
                            "questions": [
                                {"code": "4.3.A", "description": "Did you verify whether the applicant has committed/planned/prepared/participated/threatened/attempted/conspired in hijacking or sabotage of any conveyance?", "where_to_verify": "Intake; FOIA; Declarations; BioCall"},
                                {"code": "4.3.B", "description": "Did you verify whether the applicant has committed/planned/etc. seizing or detaining and threatening to kill/injure/continue to detain to compel a third person/government?", "where_to_verify": "Intake; FOIA; Declarations; BioCall"},
                                {"code": "4.3.C", "description": "Did you verify whether the applicant has committed/planned/etc. assassination?", "where_to_verify": "Intake; FOIA; Declarations; BioCall; FBI"},
                                {"code": "4.3.D", "description": "Did you verify whether the applicant has committed/planned/etc. the use of any firearm with intent to endanger safety or cause substantial property damage?", "where_to_verify": "Intake; FOIA; Declarations; Criminal record; BioCall; FBI"},
                                {"code": "4.3.E", "description": "Did you verify whether the applicant has committed/planned/etc. the use of biological/chemical/nuclear/explosive/other dangerous device?", "where_to_verify": "Intake; FOIA; Declarations; FBI"},
                            ],
                        },
                        {
                            "code": "4.3.2",
                            "name": "Terrorist organization association (INA 219 + other groups)",
                            "questions": [
                                {"code": "4.3.F", "description": "Did you verify whether the applicant has been a member of / solicited money or members for / provided support for a terrorist organization under INA 219?", "where_to_verify": "Intake; FOIA; Declaration; FBI"},
                                {"code": "4.3.G", "description": "Did you verify whether the applicant has been associated with any other group that engaged in hijacking/sabotage?", "where_to_verify": "Intake; FOIA; FBI"},
                                {"code": "4.3.H", "description": "Did you verify whether the applicant has been associated with a group that engaged in seizing/detaining hostage-type conduct?", "where_to_verify": "Intake; FOIA; FBI"},
                                {"code": "4.3.I", "description": "Did you verify whether the applicant has been associated with a group that engaged in assassination?", "where_to_verify": "Intake; FOIA; FBI"},
                                {"code": "4.3.J", "description": "Did you verify whether the applicant has been associated with a group that engaged in use of firearms to endanger safety?", "where_to_verify": "Intake; FOIA; FBI"},
                                {"code": "4.3.K", "description": "Did you verify whether the applicant has been associated with a group involved in soliciting money/members or providing material support to a terrorist organization?", "where_to_verify": "Intake; FOIA; FBI"},
                                {"code": "4.3.L", "description": "Did you verify whether the applicant has been associated with a group that engaged in WMD/explosive/other dangerous device conduct?", "where_to_verify": "Intake; FOIA; FBI"},
                            ],
                        },
                        {
                            "code": "4.3.3",
                            "name": "Intent in the U.S. (espionage/overthrow/export violations)",
                            "questions": [
                                {"code": "4.3.M", "description": "Did you verify whether the applicant intends to engage in the U.S. in espionage?", "where_to_verify": "Intake; FBI"},
                                {"code": "4.3.N", "description": "Did you verify whether the applicant intends to engage in unlawful activity or activity to oppose/control/overthrow the U.S. government?", "where_to_verify": "Intake; FBI"},
                            ],
                        },
                        {
                            "code": "4.3.4",
                            "name": "Communist/totalitarian party + Nazi-era persecution",
                            "questions": [
                                {"code": "4.3.P", "description": "Did you verify whether the applicant has ever been or continues to be a member of the Communist or other totalitarian party (except involuntary membership)?", "where_to_verify": "Country history; Personal history"},
                                {"code": "4.3.Q", "description": "Did you verify whether, during 3/23/1933-5/8/1945, the applicant ordered/incited/assisted/participated in persecution in association with Nazi Germany?", "where_to_verify": "Country history; Personal history; Intake; Birth Certificate"},
                            ],
                        },
                    ],
                },
                {
                    "code": "4.4",
                    "name": "Presence near harm + Immigration proceedings/removal/visa denial",
                    "questions": [
                        {"code": "4.4.A", "description": "Did you verify whether the applicant has been present or nearby when someone was intentionally killed, tortured, beaten, or injured?", "where_to_verify": "Intake; Personal history; Declaration"},
                        {"code": "4.4.B", "description": "Did you verify whether the applicant has been present or nearby when someone was displaced/moved by force/compulsion/duress?", "where_to_verify": "Intake; Country history; Declaration"},
                        {"code": "4.5.C", "description": "Did you verify whether the applicant has been present or nearby when someone was forced to engage in sexual contact/relations?", "where_to_verify": "Intake; Personal history; Declaration"},
                        {"code": "4.5.D", "description": "Did you verify whether removal/exclusion/rescission/deportation proceedings are pending?", "where_to_verify": "EOIR portal; FOIA EOIR/ICE"},
                        {"code": "4.5.E", "description": "Did you verify whether removal/exclusion/rescission/deportation proceedings have been initiated?", "where_to_verify": "EOIR portal; FOIA EOIR/ICE"},
                        {"code": "4.5.F", "description": "Did you verify whether the applicant has been removed/excluded/deported from the U.S.?", "where_to_verify": "FOIA CBP/ICE/EOIR/FBI"},
                        {"code": "4.5.G", "description": "Did you verify whether the applicant has been ordered removed/excluded/deported?", "where_to_verify": "FOIA EOIR/ICE/FBI; EOIR portal"},
                        {"code": "4.5.H", "description": "Did you verify whether the applicant has been denied a visa or denied admission to the U.S.?", "where_to_verify": "Client docs; Declaration; FOIA"},
                        {"code": "4.5.I", "description": "Did you verify whether the applicant was granted voluntary departure and failed to depart within the allotted time?", "where_to_verify": "FOIA EOIR; EOIR portal"},
                    ],
                },
                {
                    "code": "4.5",
                    "name": "Torture/Genocide/Killing/Injury/Forced sex/Religious limits",
                    "questions": [
                        {"code": "4.5.A", "description": "Did you verify whether the applicant has ordered/incited/called for/committed/assisted/participated in torture or genocide?", "where_to_verify": "Personal history; Country history; Intake"},
                        {"code": "4.5.B", "description": "Did you verify whether the applicant has participated in killing any person?", "where_to_verify": "Personal history; Intake; FBI"},
                        {"code": "4.5.C", "description": "Did you verify whether the applicant has participated in intentionally and severely injuring any person?", "where_to_verify": "Personal history; Intake; FBI"},
                        {"code": "4.5.D", "description": "Did you verify whether the applicant has engaged in sexual contact/relations with someone being forced or threatened?", "where_to_verify": "Personal history; Intake; FBI"},
                        {"code": "4.5.E", "description": "Did you verify whether the applicant has participated in limiting/denying religious beliefs?", "where_to_verify": "Country history; Personal history; FBI"},
                    ],
                },
                {
                    "code": "4.7",
                    "name": "Civil penalty / fraud-misrep / draft / child custody / polygamy / stowaway",
                    "questions": [
                        {"code": "4.7.A", "description": "Did you verify whether the applicant is under a final order or civil penalty for violating INA 274C (false documentation)?", "where_to_verify": "FOIA; Prior filings; Client docs; Declaration"},
                        {"code": "4.7.B", "description": "Did you verify whether the applicant, by fraud or willful misrepresentation, sought to procure a visa/documentation/entry/immigration benefit?", "where_to_verify": "FOIA; Prior filings; Declaration; Work history"},
                        {"code": "4.7.C", "description": "Did you verify whether the applicant left the U.S. to avoid being drafted into the U.S. Armed Forces?", "where_to_verify": "Intake; Personal history; FBI"},
                        {"code": "4.7.D", "description": "Did you verify whether the applicant has withheld custody of a child with lawful claim to U.S. citizenship?", "where_to_verify": "Court records (custody); Intake; FBI; Declaration"},
                        {"code": "4.7.E", "description": "Did you verify whether the applicant plans to practice polygamy in the U.S.?", "where_to_verify": "Intake; Declaration"},
                        {"code": "4.7.F", "description": "Did you verify whether the applicant entered the U.S. as a stowaway?", "where_to_verify": "Declaration; FOIA CBP; Intake"},
                    ],
                },
                {
                    "code": "4.8",
                    "name": "Health",
                    "questions": [
                        {"code": "4.8.A", "description": "Did you verify whether the applicant has a communicable disease of public health significance?", "where_to_verify": "Medical records; Declaration; BioCall"},
                        {"code": "4.8.B", "description": "Did you verify whether the applicant has/had a physical or mental disorder with behavior posing a threat to property/safety/welfare?", "where_to_verify": "Medical Evaluation; BioCall; Declaration"},
                        {"code": "4.8.C", "description": "Did you verify whether the applicant is now or has been a drug abuser or drug addict?", "where_to_verify": "Medical Evaluation; Medical record; BioCall; Declaration"},
                    ],
                },
            ],
        },
        {
            "code": "Part 5",
            "name": "Information About Your Family Members",
            "questions": [
                {"code": "5.1", "description": "Did you verify that current spouse information (full name, DOB, country of birth) is complete and accurate? Did you verify prior spouse(s) information?", "where_to_verify": "Marriage certificates; Declaration"},
                {"code": "5.2", "description": "Did you verify that current spouse information (full name, DOB, country of birth) is complete and accurate?", "where_to_verify": "Birth Certificate; Passport"},
                {"code": "5.3", "description": "Did you verify that each child is listed with full name, DOB, country of birth, and current location?", "where_to_verify": "BioCall; Birth Certificates"},
                {"code": "5.4", "description": "Did you verify children from prior relationships are included (even if no contact)?", "where_to_verify": "Declaration/Affidavit; Court Records (Custody)"},
                {"code": "5.5", "description": "Did you verify stepchildren eligibility and relationship dates (marriage date to parent)?", "where_to_verify": "Marriage certificate; Birth Certificates"},
                {"code": "5.6", "description": "Did you verify adopted children details and final adoption status?", "where_to_verify": "Adoption decrees; Court orders"},
                {"code": "5.7", "description": "Did you verify child's marital status (must be unmarried for derivatives where applicable)?", "where_to_verify": "Declaration/Affidavit; Civil records"},
                {"code": "5.8", "description": "Did you verify child's age at filing to assess derivative eligibility/age-out protection?", "where_to_verify": "Birth certificates; Filing date"},
                {"code": "5.9", "description": "Did you verify current address/location for each listed family member?", "where_to_verify": "Declaration/Affidavit; Contact Records; Google maps"},
                {"code": "5.10", "description": "Did you verify whether any family member is deceased (and properly noted)?", "where_to_verify": "Death certificates; Declaration/Affidavit"},
                {"code": "5.11", "description": "Did you verify whether the applicant is requesting derivatives now?", "where_to_verify": "I-914; Strategy Memo"},
                {"code": "5.12", "description": "If derivatives are requested, did you verify I-914A prepared for each eligible family member?", "where_to_verify": "I-914A drafts; Filing checklist"},
                {"code": "5.13", "description": "Did you verify consistency between Part 5, Declaration, I-914A (if any), and prior filings?", "where_to_verify": "Prior filings; FOIA USCIS; Case file"},
            ],
        },
        {
            "code": "Part 6",
            "name": "Applicant's Statement, Contact Information, Certification, and Signature",
            "questions": [
                {"code": "6.1", "description": "Did you verify whether the applicant can read and understand English? Select Box A only if Yes.", "where_to_verify": "Bio Call"},
                {"code": "6.2", "description": "Did you verify whether an interpreter was used, and that this matches? If client speaks a different language than English or Spanish, they can freely look for an interpreter.", "where_to_verify": "Bio Call"},
                {"code": "6.3", "description": "Did you verify whether a preparer was used, and that this matches Part 8?", "where_to_verify": "Part 6; Part 8"},
                {"code": "6.4", "description": "Did you verify all applicant contact information (phone, safe phone, email) is complete and consistent?", "where_to_verify": "Intake; Bio Call; BOS"},
                {"code": "6.5", "description": "Did you verify the applicant signed and dated the form in ink?", "where_to_verify": "Original I-914"},
            ],
        },
        {
            "code": "Part 7",
            "name": "Interpreter's Contact Information, Certification, and Signature",
            "questions": [
                {"code": "7.1", "description": "Did you verify the interpreter's full legal name is listed First Name and Last Name?", "where_to_verify": "BOS"},
                {"code": "7.2", "description": "Did you verify the interpreter's organization?", "where_to_verify": "The Law Offices of Manuel E. Solis (if Eng/Spa); client doc for other languages"},
                {"code": "7.3", "description": "Did you verify the Interpreter's Mailing Address?", "where_to_verify": "P.O. Box 231704 Houston, TX 77223 (if firm); otherwise client provides"},
                {"code": "7.4", "description": "Did you verify the interpreter's contact information are complete (daytime phone, safe number, email)?", "where_to_verify": "713-8442700; uscism@manuelsolis.com"},
                {"code": "7.5", "description": "Did you verify the interpreter certification? Did you verify the interpreter signed and dated the form in ink?", "where_to_verify": "BOSS (case manager assigned)"},
            ],
        },
        {
            "code": "Part 8",
            "name": "Preparer's Contact Information, Declaration, and Signature",
            "questions": [
                {"code": "8.1", "description": "Did you verify the preparer's full name and organization are listed?", "where_to_verify": "BOSS"},
                {"code": "8.2", "description": "Did you verify the preparer's mailing address and contact information (phone numbers and email)?", "where_to_verify": "P.O. Box 231704 Houston, TX 77223; 713-8442700; uscism@manuelsolis.com"},
                {"code": "8.3", "description": "Did you verify whether the preparer is an attorney or accredited representative, and bar/DOJ info is correct?", "where_to_verify": "CHECK BOX B 'IM NOT AN ATTORNEY'"},
                {"code": "8.4", "description": "Did you verify the preparer signed and dated the form in ink?", "where_to_verify": "Original I-914"},
            ],
        },
        {
            "code": "Part 9",
            "name": "Additional Information",
            "questions": [
                {"code": "9.1", "description": "Did you verify Part 9 is used for all YES answers from Parts 1-8?", "where_to_verify": "Part 3, 1-8; 914"},
                {"code": "9.2", "description": "Did you verify each explanation includes the correct Page / Part / Item Number?", "where_to_verify": "Part 9 entries"},
                {"code": "9.3", "description": "Did you verify explanations are clear, specific, and complete, with no grammatical mistakes?", "where_to_verify": "Part 9; Declaration"},
                {"code": "9.4", "description": "Did you verify additional sheets include applicant name and A-number (if any)?", "where_to_verify": "Attachments"},
                {"code": "9.5", "description": "Did you verify each additional page is signed and dated by the applicant?", "where_to_verify": "Attachments"},
                {"code": "9.6", "description": "Did you verify that you answered page 3, part 3 item 9 with the last entry correct information?", "where_to_verify": "Declaration; Bio Call; Part 9"},
            ],
        },
    ],
}

