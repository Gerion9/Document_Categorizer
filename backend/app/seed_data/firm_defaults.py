"""Canonical firm-default values reused across questionnaire JSONs and QC templates.

These are the supervisor-approved values for the Law Offices of Manuel E. Solis
mirrored from the I-914 QC template (the firm's most thoroughly reviewed
checklist). Every questionnaire JSON `default_value` that mentions firm data
and every QC template `where_to_verify` string that cites contact info should
sourcer here so the data stays consistent.

NOT a runtime config; this module is a single source of truth for static seed
data. Migration scripts and seed loaders import these constants.
"""

from __future__ import annotations

FIRM_DEFAULTS: dict[str, str] = {
    # People
    "attorney_full_name": "Manuel E. Solis",
    # Firm identity
    "firm_name": "Law Offices of Manuel E. Solis",
    "firm_name_pllc": "Law Offices of Manuel E. Solis, PLLC",
    # Identifiers
    "attorney_bar_number": "18826790",
    "uscis_online_account": "087361245002",
    # Address (mailing)
    "address_street": "P.O. Box 231704",
    "address_city": "Houston",
    "address_state": "TX",
    "address_zip": "77223",
    "address_one_line": "P.O. Box 231704, Houston, TX 77223",
    # Contact
    "phone": "7138442700",
    "phone_pretty": "713-844-2700",
    "email": "uscism@manuelsolis.com",
}


__all__ = ["FIRM_DEFAULTS"]
