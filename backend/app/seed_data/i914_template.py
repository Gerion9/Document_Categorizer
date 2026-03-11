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
                {"code": "1", "description": "Did you verify Full Legal Name?", "where_to_verify": "Birth Certificate or Passport"},
                {"code": "2", "description": "Did you verify Other Names Used?", "where_to_verify": "FBI RECORDs and/or the BIO CALL, Otros Documentos"},
                {"code": "3", "description": "Did you verify the Physical Address?", "where_to_verify": "Bio Call, Google Maps and Proof of Address"},
                {"code": "4", "description": "Did you verify the Safe Mailing Address? Law Offices Of Manuel E. Solis P.O. Box 231704 Houston, TX 77223", "where_to_verify": "Is this address in the section the Houston office address"},
                {"code": "4.A", "description": "Accredited representative information: Did you CHECK the Additional square in the bottom right corner for the G28 and write Attorney Bar Number Manuel E. Solis", "where_to_verify": "MUST BE: Attorney State License Bar Number 18826790. USCIS Online Account Number - 087361245002"},
                {"code": "5", "description": "Did you verify the Alien Registration Number (A-Number)?", "where_to_verify": "Intake, BIO call or Previous Immigration Process Docs, FBI RAPSHEET"},
                {"code": "6", "description": "Did you verify USCIS Online Account Number?", "where_to_verify": "Bio Call"},
                {"code": "7", "description": "Did you verify U.S. Social Security Number (SSN)? *Just SSN Issued by the Government", "where_to_verify": "Bio Call / Copy of SS Card"},
                {"code": "8", "description": "Did you verify applicants gender?", "where_to_verify": "Birth Certificate / Passport"},
                {"code": "9", "description": "Did you verify Marital Status?", "where_to_verify": "Intake / Bio Call / Marriage Cert"},
                {"code": "10", "description": "Did you verify Date of Birth? *Remember to use the proper format (mm/dd/yyyy)", "where_to_verify": "Birth Cert / Passport"},
                {"code": "11", "description": "Did you verify Place of Birth?", "where_to_verify": "Birth Cert"},
                {"code": "12", "description": "Did you verify the Country of Citizenship or Nationality?", "where_to_verify": "Birth Cert / Passport"},
                {"code": "13", "description": "Did you verify Passport or Travel Document Number (if any)?", "where_to_verify": "Passport / I-94 / Visa / Other Doc"},
                {"code": "14", "description": "Did you verify the Country That Issued Your Passport or Travel Document (if any)?", "where_to_verify": "Passport / I-94 / Visa / Other Doc"},
                {"code": "15", "description": "Did you verify Issue Date for Passport or Travel Document (if any)? *Remember to use the proper format (mm/dd/yyyy)", "where_to_verify": "Passport / I-94 / Visa"},
                {"code": "16", "description": "Did you verify Expiration Date for Passport or Travel Document (if any)? *Remember to use the proper format (mm/dd/yyyy)", "where_to_verify": "Passport / I-94 / Visa"},
                {"code": "17", "description": "Did you verify Place of Your Last Entry Into the United States? *City or Town *State", "where_to_verify": "Intake / Bio Call / Declaration / FBI / FOIA"},
                {"code": "18", "description": "Did you verify Date of Your Last Entry Into the United States, On or About? *Remember to use the proper format (mm/dd/yyyy)", "where_to_verify": "Intake / Bio Call / Declaration / FBI / FOIA"},
                {"code": "19", "description": "Did you verify Form I-94 Arrival-Departure Record Number (if any)?", "where_to_verify": "I-94 / FOIA"},
                {"code": "20", "description": "Did you verify Your Current Nonimmigrant Status? *IF NO STATUS - No Legal Status*", "where_to_verify": "Intake / Bio Call / Immigration Doc"},
            ],
        },
        {
            "code": "Part 3",
            "name": "I-914 Part 3",
            "questions": [
                {"code": "3.1", "description": "Did you verify whether the applicant has been a victim of a severe form of trafficking in persons?", "where_to_verify": "Intake; Bio Call; Declaration: must be checked (true/yes)"},
                {"code": "3.2.A", "description": "Did you verify whether the applicant cooperated with reasonable requests for assistance from law enforcement?", "where_to_verify": "LEA Report email; cover letter; Declaration; police reports"},
                {"code": "3.2.B", "description": "Did you verify whether the applicant due to their age or the trauma has suffered, and is exempt from the requirement to cooperate with reasonable requests for assistance from law enforcement?", "where_to_verify": "Intake; Bio Call; Declaration; Birth Certificate"},
                {"code": "3.3", "description": "Did you verify whether the applicant is physically present in the United States, American Samoa, or the Commonwealth of the Northern Mariana Islands, or at a port of entry, on account of trafficking, or has been allowed entry into the United States to participate in investigative or judicial processes associated with an act or perpetrator of trafficking?", "where_to_verify": "Intake; Bio Call; must be checked yes, unless is a derivative outside the states"},
                {"code": "3.4", "description": "Did you verify whether the applicant fears that they will suffer extreme hardship involving unusual and severe harm upon removal?", "where_to_verify": "Intake; Declaration part. \"Extreme Hardship if removal from the US\""},
                {"code": "3.5", "description": "Did you verify whether the applicant has reported the trafficking crime of which they are claiming to be a victim. (If you selected \"Yes,\" indicate to which law enforcement agency and office you have made the report, the address and phone number of that office, and the case number assigned, if any. If you selected \"No,\" explain the circumstances below.) Law Enforcement Agency and Office City or Town State ZIP Code Street Number and Name Apt. Flr. Number Ste. Daytime Telephone Number Case Number Circumstances", "where_to_verify": "LEA Report; HTPU (Human Trafficking Prosecution unit, US department of Justice); Police Report"},
                {"code": "3.6", "description": "Did you verify whether they were under 18 years of age at the time at least one of the acts of trafficking occurred.", "where_to_verify": "Intake; Declaration; Birth Certificate"},
                {"code": "3.7", "description": "Did you verify whether the applicant has complied with reasonable requests from Federal, State, Tribal, or local law enforcement authorities for assistance in the investigation or prosecution of acts of trafficking, or is unable to cooperate with such requests due to physical or psychological trauma. (If you selected \"No,\" and were over 18 years of age at the time one of the acts of trafficking occurred, explain the circumstances.)", "where_to_verify": "LEA Report"},
                {"code": "3.8", "description": "Did you verify whether this is the applicant's first time they have entered the United States. (If you selected \"No,\" list each date, place of entry, and under which status you entered the United States for the past five years, and explain the circumstances of your most recent arrival.) 1. Date of Entry (mm/dd/yyyy) 2. Place of Entry City or Town and State 3. Status", "where_to_verify": "Intake; Bio Call; Declaration; FBI; FOIA"},
                {"code": "3.9", "description": "Did you verify whether the applicant's most recent entry was on account of the trafficking that forms the basis for my claim. (Explain the circumstances of your most recent arrival.)", "where_to_verify": "Intake; Declaration"},
                {"code": "3.10", "description": "Did you verify whether the applicant is requesting an Employment Authorization Document (EAD) when I am granted T nonimmigrant status?", "where_to_verify": "Verify to answer YES Form I-765"},
                {"code": "3.11", "description": "Did you verify whether the applicant is now applying for one or more eligible family members. (If you selected \"Yes,\" complete and include a Form I-914, Supplement A, Application for Derivative T Nonimmigrant Status, for each family member for whom you are now applying. You may also apply to bring eligible family members to the United States at a later date.)", "where_to_verify": "Contract; cover letter header regarding T-2, T-3, etc; Form I-914 Supplement A attached"},
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
                        {"code": "4.1.A", "description": "Did you verify whether the applicant has committed a crime or offense for which they have not been arrested?", "where_to_verify": "Intake; Bio Call; Declaration/Affidavit; Criminal Record; FBI (most accurate, but some detentions only in statement)"},
                        {"code": "4.1.B", "description": "Did you verify whether the applicant has been arrested, cited, or detained by any law enforcement officer (including DHS/INS/military) for any reason?", "where_to_verify": "Intake; Bio Call; Declaration; Criminal record; FBI; FOIA (as needed)"},
                        {"code": "4.1.C", "description": "Did you verify whether the applicant has been charged with committing any crime or offense?", "where_to_verify": "Court disposition; Criminal record; FOIA; FBI"},
                        {"code": "4.1.D", "description": "Did you verify whether the applicant has been convicted of a crime or offense (even if later expunged or pardoned)?", "where_to_verify": "Outcome; Court disposition; Criminal record; FBI"},
                        {"code": "4.1.E", "description": "Did you verify whether the applicant has been placed in alternative sentencing / rehabilitative programs (diversion, deferred prosecution, withheld adjudication, deferred adjudication)?", "where_to_verify": "Court disposition; FOIA; FBI"},
                        {"code": "4.1.F", "description": "Did you verify whether the applicant has received a suspended sentence, been placed on probation, or been paroled?", "where_to_verify": "Court disposition; FOIA; FBI; Declaration"},
                        {"code": "4.1.G", "description": "Did you verify whether the applicant has been in jail or prison?", "where_to_verify": "Declaration/Affidavit; Intake; Bio Call; FBI; Court dispositions"},
                        {"code": "4.1.H", "description": "Did you verify whether the applicant has been the beneficiary of a pardon, amnesty, rehabilitation, clemency, or similar action?", "where_to_verify": "Official documents (client docs); Court record; FBI; Bio Call"},
                        {"code": "4.1.I", "description": "Did you verify whether the applicant has exercised diplomatic immunity to avoid prosecution for a criminal offense in the U.S.?", "where_to_verify": "Intake; Declaration; Bio Call; any documentation; FBI"},
                        {"code": "4.1. (Trigger)", "description": "If any of 4.1.A-4.1.I is Yes, did you verify the incident table is completed (date (*Remember to use the proper format (mm/dd/yyyy)) /place/why/outcome)?", "where_to_verify": "Part 9 incident table; dispositions/FOIA as needed"},
                    ],
                },
                {
                    "code": "4.2",
                    "name": "Prostitution / Vice / Smuggling / Drug trafficking",
                    "questions": [
                        {"code": "4.2.A", "description": "Did you verify whether the applicant has engaged in prostitution or procurement of prostitution, or intends to engage?", "where_to_verify": "Intake; Bio Call; Declaration (flag trafficking nexus); Criminal record; FBI"},
                        {"code": "4.2.B", "description": "Did you verify whether the applicant has engaged in unlawful commercialized vice (including illegal gambling)?", "where_to_verify": "Intake; Declaration; Criminal record; FBI"},
                        {"code": "4.2.C", "description": "Did you verify whether the applicant has knowingly encouraged/induced/assisted/abetted/aided any alien to try to enter the U.S. illegally?", "where_to_verify": "Declaration; FOIA CBP; Bio Call (if needed); FBI"},
                        {"code": "4.2.D", "description": "Did you verify whether the applicant has illicitly trafficked in any controlled substance, or knowingly assisted/abetted/colluded in illicit trafficking?", "where_to_verify": "Criminal record; Court disposition; FOIA; Bio Call; FBI"},
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
                                {"code": "4.3.A", "description": "Did you verify whether the applicant has committed/planned/prepared/participated/threatened/attempted/conspired (or gathered info/solicited funds for) hijacking or sabotage of any conveyance?", "where_to_verify": "Intake; FOIA (if any); Declaration; Bio Call"},
                                {"code": "4.3.B", "description": "Did you verify whether the applicant has committed/planned/etc. seizing or detaining and threatening to kill/injure/continue to detain to compel a third person/government?", "where_to_verify": "Intake; FOIA (if any); Declaration; Bio Call"},
                                {"code": "4.3.C", "description": "Did you verify whether the applicant has committed/planned/etc. assassination?", "where_to_verify": "Intake; FOIA (if any); Declaration; Bio Call; FBI"},
                                {"code": "4.3.D", "description": "Did you verify whether the applicant has committed/planned/etc. the use of any firearm with intent to endanger safety or cause substantial property damage?", "where_to_verify": "Intake; FOIA; Declaration; Criminal record (if any); Bio Call; FBI"},
                                {"code": "4.3.E", "description": "Did you verify whether the applicant has committed/planned/etc. the use of biological/chemical/nuclear/explosive/other dangerous device with intent to endanger safety or cause substantial damage?", "where_to_verify": "Intake; FOIA; Declaration; FBI; Bio Call"},
                            ],
                        },
                        {
                            "code": "4.3.2",
                            "name": "Terrorist organization association (INA 219 + other groups)",
                            "questions": [
                                {"code": "4.4.A", "description": "Did you verify whether the applicant has been a member of / solicited money or members for / provided support for / attended military training by or on behalf of / been associated with an organization designated as terrorist under INA 219?", "where_to_verify": "Intake; FOIA; Declaration; FBI; Bio Call"},
                                {"code": "4.4.B", "description": "Did you verify whether the applicant has been associated with any other group (2+ individuals) that engaged in hijacking/sabotage?", "where_to_verify": "Intake; FOIA; FBI; Bio Call"},
                                {"code": "4.3.B.1", "description": "Did you verify whether the applicant has been associated with a group that engaged in seizing/detaining hostage-type conduct to compel a third party/government?", "where_to_verify": "Intake; FOIA; FBI; Bio Call"},
                                {"code": "4.3.B.2", "description": "Did you verify whether the applicant has been associated with a group that engaged in assassination?", "where_to_verify": "Intake; FOIA; FBI; Bio Call"},
                                {"code": "4.3.B.4", "description": "Did you verify whether the applicant has been associated with a group that engaged in use of firearms to endanger safety/cause substantial damage?", "where_to_verify": "Intake; FOIA; FBI; Bio Call"},
                                {"code": "4.3.B.5", "description": "Did you verify whether the applicant has been associated with a group involved in soliciting money/members or providing material support to a terrorist organization?", "where_to_verify": "Intake; FOIA; FBI; Bio Call"},
                                {"code": "4.3.B.6", "description": "Did you verify whether the applicant has been associated with a group that engaged in WMD/explosive/other dangerous device conduct to endanger safety/cause substantial damage?", "where_to_verify": "Intake; FOIA; FBI; Bio Call"},
                            ],
                        },
                        {
                            "code": "4.5",
                            "name": "Intent in the U.S. (espionage/overthrow/export violations)",
                            "questions": [
                                {"code": "4.5.A", "description": "Did you verify whether the applicant intends to engage in the U.S. in espionage?", "where_to_verify": "FBI; Bio Call"},
                                {"code": "4.5.B", "description": "Did you verify whether the applicant intends to engage in unlawful activity or activity to oppose/control/overthrow the U.S. government?", "where_to_verify": "Intake; FBI; Bio Call"},
                                {"code": "4.5.C", "description": "Did you verify whether the applicant intends to engage in activity related to espionage/sabotage or to violate export laws involving goods/technology/sensitive info?", "where_to_verify": "Intake; FBI; Bio Call"},
                            ],
                        },
                        {
                            "code": "4.6-4.7",
                            "name": "Communist/totalitarian party + Nazi-era persecution",
                            "questions": [
                                {"code": "4.6", "description": "Did you verify whether the applicant has ever been or continues to be a member of the Communist or other totalitarian party (except involuntary membership)?", "where_to_verify": "Intake; Country history; Personal history; Bio Call"},
                                {"code": "4.7", "description": "Did you verify whether, during 3/23/1933-5/8/1945, the applicant ordered/incited/assisted/participated in persecution in association with Nazi Germany (or allied org/government)?", "where_to_verify": "Country history; Personal history; Intake; Birth Certificate (Axis)"},
                            ],
                        },
                    ],
                },
                {
                    "code": "4.8-4.9",
                    "name": "Presence near harm + Immigration proceedings/removal/visa denial/voluntary departure",
                    "questions": [
                        {"code": "4.8.A", "description": "Did you verify whether the applicant has been present or nearby when someone was intentionally killed, tortured, beaten, or injured?", "where_to_verify": "Intake; Personal history; Declaration; Bio Call"},
                        {"code": "4.8.B", "description": "Did you verify whether the applicant has been present or nearby when someone was displaced/moved by force/compulsion/duress?", "where_to_verify": "Intake; Country history; Declaration; Bio Call"},
                        {"code": "4.8.C", "description": "Did you verify whether the applicant has been present or nearby when someone was forced to engage in sexual contact/relations?", "where_to_verify": "Intake; Personal history; Declaration; Bio Call"},
                        {"code": "4.9.A", "description": "Did you verify whether removal/exclusion/rescission/deportation proceedings are pending?", "where_to_verify": "EOIR portal; FOIA EOIR/ICE; Intake; Bio Call"},
                        {"code": "4.9.B", "description": "Did you verify whether removal/exclusion/rescission/deportation proceedings have been initiated?", "where_to_verify": "EOIR portal; FOIA EOIR/ICE; Intake; Bio Call"},
                        {"code": "4.9.C", "description": "Did you verify whether the applicant has been removed/excluded/deported from the U.S.?", "where_to_verify": "FOIA CBP/ICE/EOIR/FBI; Intake; Bio Call"},
                        {"code": "4.9.D", "description": "Did you verify whether the applicant has been ordered removed/excluded/deported?", "where_to_verify": "FOIA EOIR/ICE/FBI; EOIR portal; Intake; Bio Call"},
                        {"code": "4.9.E", "description": "Did you verify whether the applicant has been denied a visa or denied admission to the U.S.?", "where_to_verify": "Client docs; Declaration; FOIA (as needed); Bio Call"},
                        {"code": "4.9.F", "description": "Did you verify whether the applicant was granted voluntary departure and failed to depart within the allotted time?", "where_to_verify": "FOIA EOIR; EOIR portal; Intake; Bio Call"},
                    ],
                },
                {
                    "code": "4.10",
                    "name": "Torture/Genocide/Killing/Injury/Forced sex/Religious limits",
                    "questions": [
                        {"code": "4.10.A", "description": "Did you verify whether the applicant has ordered/incited/called for/committed/assisted/participated in torture or genocide?", "where_to_verify": "Personal history; Country history; Bio Call"},
                        {"code": "4.10.B", "description": "Did you verify whether the applicant has participated in killing any person?", "where_to_verify": "Personal history; Intake; FBI; Bio Call"},
                        {"code": "4.10.C", "description": "Did you verify whether the applicant has participated in intentionally and severely injuring any person?", "where_to_verify": "Personal history; Intake; FBI; Bio Call"},
                        {"code": "4.10.D", "description": "Did you verify whether the applicant has engaged in sexual contact/relations with someone being forced or threatened?", "where_to_verify": "Personal history; Intake; FBI; Bio Call"},
                        {"code": "4.10.E", "description": "Did you verify whether the applicant has participated in limiting/denying religious beliefs?", "where_to_verify": "Country history; Bio Call; Personal history; FBI"},
                    ],
                },
                {
                    "code": "4.11-4.14",
                    "name": "Military/Paramilitary/Detention/Weapons/Training",
                    "questions": [
                        {"code": "4.11.A", "description": "Did you verify whether the applicant has served in/been a member of/assisted/participated in any military/paramilitary/police/self-defense/vigilante/rebel/guerrilla/militia/insurgent organization?", "where_to_verify": "Intake; Personal/Country history; FBI; Bio Call"},
                        {"code": "4.11.B", "description": "Did you verify whether the applicant has served in any prison/jail/detention facility/labor camp or other situation involving detaining persons?", "where_to_verify": "Intake; Personal history; FBI; Bio Call"},
                        {"code": "4.12", "description": "Did you verify whether the applicant has participated in any group where any person used a weapon against someone or threatened to?", "where_to_verify": "Intake; Personal history; FBI; Bio Call"},
                        {"code": "4.13", "description": "Did you verify whether the applicant has assisted/participated in selling/providing/transporting weapons to someone they knew used them against others?", "where_to_verify": "Intake; Personal history; FBI; Bio Call"},
                        {"code": "4.14", "description": "Did you verify whether the applicant has received military/paramilitary/weapons training?", "where_to_verify": "Intake; Personal history (DECLARATION BACKGROUND); FBI; Bio Call"},
                    ],
                },
                {
                    "code": "4.15-4.20",
                    "name": "Civil penalty / fraud-misrep / draft / child custody / polygamy / stowaway",
                    "questions": [
                        {"code": "4.15", "description": "Did you verify whether the applicant is under a final order or civil penalty for violating INA 274C (false documentation)?", "where_to_verify": "FOIA; Prior filings; Client docs; Declaration; Bio Call"},
                        {"code": "4.16", "description": "Did you verify whether the applicant, by fraud or willful misrepresentation, sought to procure a visa/documentation/entry/immigration benefit?", "where_to_verify": "FOIA; Prior filings; Declaration; Work history; Intake; Bio Call"},
                        {"code": "4.17", "description": "Did you verify whether the applicant left the U.S. to avoid being drafted into U.S. Armed Forces?", "where_to_verify": "Intake; Personal history; FBI; Bio Call"},
                        {"code": "4.18", "description": "Did you verify whether the applicant has withheld custody of a child with lawful claim to U.S. citizenship outside the U.S. from a U.S. citizen granted custody?", "where_to_verify": "Court records (custody); Intake; FBI; Declaration; Bio Call"},
                        {"code": "4.19", "description": "Did you verify whether the applicant plans to practice polygamy in the U.S.?", "where_to_verify": "Intake; Declaration; Bio Call"},
                        {"code": "4.20", "description": "Did you verify whether the applicant entered the U.S. as a stowaway?", "where_to_verify": "Declaration; FOIA CBP; Intake; Bio Call"},
                    ],
                },
                {
                    "code": "4.21",
                    "name": "Health",
                    "questions": [
                        {"code": "4.21.A", "description": "Did you verify whether the applicant has a communicable disease of public health significance?", "where_to_verify": "Medical records; Declaration; Bio Call (disease: Active Tuberculosis (TB); Specifically infections TB; Infectious Syphilis; Gonorrhea; Infectious Hansen's Disease (Leprosy))"},
                        {"code": "4.21.B", "description": "Did you verify whether the applicant has/had a physical or mental disorder with behavior (or history likely to recur) posing a threat to property/safety/welfare of self/others?", "where_to_verify": "Medical Evaluation; Bio Call; Declaration"},
                        {"code": "4.21.C", "description": "Did you verify whether the applicant is now or has been a drug abuser or drug addict?", "where_to_verify": "Medical Evaluation; Medical record; Bio Call; Declaration"},
                    ],
                },
            ],
        },
        {
            "code": "Part 5",
            "name": "Information About Your Family Members",
            "questions": [
                {"code": "5.1", "description": "Did you verify that current spouse information (5.1.A: full name, 5.1.B: DOB, 5.1.C: country of birth, 5.1.D current location) is complete and accurate? If not married skip to part 5.3. Also verify whether the applicant has ever been married in or outside the United States and prior spouse(s) information (names, dates of marriage/divorce/annulment). A marriage is void if a prior marriage was never dissolved through divorce or annulment.", "where_to_verify": "Marriage certificates; declaration"},
                {"code": "5.2", "description": "Did you verify that each child is listed with 5.2.A: full name, 5.2.B: DOB, 5.2.C: country of birth, and 5.2.D: current location? If no children, skip to part 6. NOTE: Did you verify whether the applicant has children (biological, adopted, stepchildren)?", "where_to_verify": "BioCall; Birth Certificates"},
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
                {"code": "6.1", "description": "Did you verify whether the applicant can read and understand English? Select Box A only if Yes", "where_to_verify": "Bio Call"},
                {"code": "6.1.A-B", "description": "Did you verify whether an interpreter was used, and that this matches? Notes: If client speaks a different language than English or Spanish, they can freely look for an interpreter; if they speak Eng or Spa, interpreter will be the CASE MANAGER assigned on the case; if an old case manager is in the application, we must correct that and put the new one.", "where_to_verify": "Bio Call"},
                {"code": "6.2", "description": "Did you verify the preparer information is correct? and that this matches Part 8? Preparer will be the CASE MANAGER assigned on the case, if an old case manager is in the application, we must correct that and put the new one", "where_to_verify": "Part 6; Part 8"},
                {"code": "6.3/6.4/6.5", "description": "Did you verify all applicant contact information (phone, safe phone, email) is complete and consistent? MUST BE CONSISTENCE FROM ALL OF THE FORM", "where_to_verify": "Intake; Bio Call; BOS"},
                {"code": "6.6", "description": "Did you verify the applicant signed and dated the form in ink?", "where_to_verify": "Original I-914"},
            ],
        },
        {
            "code": "Part 7",
            "name": "Interpreter's Contact Information, Certification, and Signature",
            "questions": [
                {"code": "7.1", "description": "Did you verify the interpreter's full legal name is listed First Name and Last Name? Note: interpreter will be the CASE MANAGER assigned on the case; if an old case manager is in the application, we must correct that and put the new one.", "where_to_verify": "BOS"},
                {"code": "7.2", "description": "Did you verify the interpreter's organization? *this must be filled out if 6.1.B is checked*", "where_to_verify": "If Spanish or English: Law Offices of Manuel E. Solis; If other language: client doc. of interpretation services"},
                {"code": "7.3", "description": "Did you verify the Interpreter's Mailing Address? *If interpreter is from Law Offices of Manuel E. Solis* If not, we must filled out with the client's interpreter information", "where_to_verify": "English/Spanish P.O. Box 231704 Houston, TX 77223; Other languages: Client will provide this information"},
                {"code": "7.4/7.5/7.6", "description": "Did you verify the interpreter's contact information are complete? Daytime Phone Number; Safe daytime number; Email Address; If other interpreter is used, provide the information of them (client will provide this information)", "where_to_verify": "713-8442700; uscism@manuelsolis.com"},
                {"code": "7.7", "description": "Did you verify the interpreter certification? Did you verify the interpreter signed and dated the form in ink?", "where_to_verify": "BOS (case manager assigned)"},
            ],
        },
        {
            "code": "Part 8",
            "name": "Preparer's Contact Information, Declaration, and Signature",
            "questions": [
                {"code": "8.1/8.2", "description": "Did you verify the preparer's full name and organization are listed? Note: preparer will be the CASE MANAGER assigned on the case; if an old case manager is in the application, we must correct that and put the new one.", "where_to_verify": "BOS"},
                {"code": "8.3", "description": "Did you verify the preparer's mailing address?", "where_to_verify": "P.O. Box 231704 Houston, TX 77223"},
                {"code": "8.4/8.5/8.6", "description": "Did you verify the preparer's contact information is complete (phone numbers and email address)?", "where_to_verify": "713-8442700; uscism@manuelsolis.com"},
                {"code": "8.7", "description": "Did you verify whether the preparer is an attorney or accredited representative, and bar/DOJ info is correct?", "where_to_verify": "CHECK BOX B \"IM NOT AN ATTORNEY\" AND does not extend beyond the preparation of this application."},
                {"code": "8.8", "description": "Did you verify the preparer signed and dated the form in ink?", "where_to_verify": "Original I-914"},
            ],
        },
        {
            "code": "Part 9",
            "name": "Additional Information",
            "questions": [
                {"code": "9.1", "description": "Did you verify each explanation includes the correct Page / Part / Item Number?", "where_to_verify": "Part 9 entries"},
                {"code": "9.2", "description": "Did you verify explanations are clear, specific, and complete, with no grammatical mistakes?", "where_to_verify": "Part 9; Declaration"},
                {"code": "9.3", "description": "Did you verify additional sheets include applicant name and A-number (if any)? Did you verify each additional page is dated?", "where_to_verify": "Attachments"},
            ],
        },
    ],
}

