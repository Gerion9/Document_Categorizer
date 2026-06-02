import type { QuestionnaireField, QuestionnaireItem } from "../../types";

function cleanQuestionText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function mentionsAny(combined: string, ...terms: string[]): boolean {
  return terms.some((term) => combined.includes(term));
}

const INTERPRETER_IDENTITY_FIELDS = new Set([
  "interpreter_family_name",
  "interpreter_given_name",
  "interpreter_business_or_organization_name",
]);
const INTERPRETER_MAILING_FIELDS = new Set([
  "interpreter_street_number_name",
  "interpreter_unit_type",
  "interpreter_unit_number",
  "interpreter_city",
  "interpreter_state",
  "interpreter_zip_code",
  "interpreter_province",
  "interpreter_postal_code",
  "interpreter_country",
]);
const INTERPRETER_CONTACT_FIELDS = new Set([
  "interpreter_daytime_telephone_number",
  "interpreter_mobile_telephone_number",
  "interpreter_email_address",
]);
const INTERPRETER_SIGNATURE_FIELDS = new Set([
  "interpreter_fluent_language",
  "interpreter_signature",
  "interpreter_signature_date",
]);
const PREPARER_IDENTITY_FIELDS = new Set([
  "preparer_family_name",
  "preparer_given_name",
  "preparer_business_or_organization_name",
]);
const PREPARER_MAILING_FIELDS = new Set([
  "preparer_street_number_name",
  "preparer_unit_type",
  "preparer_unit_number",
  "preparer_city",
  "preparer_state",
  "preparer_zip_code",
  "preparer_province",
  "preparer_postal_code",
  "preparer_country",
]);
const PREPARER_CONTACT_FIELDS = new Set([
  "preparer_daytime_telephone_number",
  "preparer_mobile_telephone_number",
  "preparer_email_address",
]);
const PREPARER_SIGNATURE_FIELDS = new Set([
  "preparer_signature",
  "preparer_signature_date",
]);
const ADDITIONAL_INFO_ENTRY_FIELDS = new Set([
  "page_number",
  "part_number",
  "item_number",
  "additional_information",
  "additional_info",
]);

function interpreterGroupForField(fieldId: string): string {
  if (INTERPRETER_IDENTITY_FIELDS.has(fieldId)) return "interpreter_identity";
  if (INTERPRETER_MAILING_FIELDS.has(fieldId)) return "interpreter_mailing";
  if (INTERPRETER_CONTACT_FIELDS.has(fieldId)) return "interpreter_contact";
  if (INTERPRETER_SIGNATURE_FIELDS.has(fieldId)) return "interpreter_signature";
  return "interpreter_identity";
}

function preparerGroupForField(fieldId: string): string {
  if (PREPARER_IDENTITY_FIELDS.has(fieldId)) return "preparer_identity";
  if (PREPARER_MAILING_FIELDS.has(fieldId)) return "preparer_mailing";
  if (PREPARER_CONTACT_FIELDS.has(fieldId)) return "preparer_contact";
  if (PREPARER_SIGNATURE_FIELDS.has(fieldId)) return "preparer_signature";
  return "preparer_identity";
}

function normalizeAdditionalInfoField(fieldId: string): string {
  if (fieldId === "additional_info") return "additional_information";
  if (fieldId.startsWith("part9_")) return `part6_${fieldId.slice(6)}`;
  return fieldId;
}

export function getSharedAttorneyAnswerAliases(
  item: QuestionnaireItem,
  field?: QuestionnaireField
): string[] {
  const itemId = cleanQuestionText(item.id).toLowerCase();
  const fieldId = cleanQuestionText(field?.id).toLowerCase();
  const formText = cleanQuestionText(item.form_text).toLowerCase();
  const section = cleanQuestionText(item.section).toLowerCase();
  const itemType = cleanQuestionText(item.type).toLowerCase();
  const combined = [itemId, fieldId, formText, section].filter(Boolean).join(" | ");
  const aliases: string[] = [];

  const add = (alias: string) => {
    if (!aliases.includes(alias)) {
      aliases.push(alias);
    }
  };

  if (itemId.startsWith("shared_attorney.")) {
    return aliases;
  }

  if (
    itemId === "p_attorney_info" ||
    itemId === "p_global_attorney_info" ||
    mentionsAny(combined, "attorney or accredited representative information")
  ) {
    if (fieldId === "g28_attached") {
      add("shared_attorney.info.g28_attached");
    } else if (
      fieldId === "attorney_state_bar_number" ||
      fieldId === "attorney_state_license_bar_number"
    ) {
      add("shared_attorney.info.state_bar_number");
    } else if (fieldId === "attorney_uscis_online_account_number") {
      add("shared_attorney.info.uscis_online_account_number");
    } else if (!fieldId) {
      add("shared_attorney.info");
    }
    return aliases;
  }

  if (itemId === "p1_g28_attached") {
    add("shared_attorney.info.g28_attached");
    return aliases;
  }
  if (itemId === "p1_attorney_state_bar") {
    add("shared_attorney.info.state_bar_number");
    return aliases;
  }
  if (itemId === "p1_attorney_uscis_account") {
    add("shared_attorney.info.uscis_online_account_number");
    return aliases;
  }

  if (fieldId.startsWith("part6_") || fieldId.startsWith("part9_")) {
    add(`shared_attorney.additional_info_header.${normalizeAdditionalInfoField(fieldId)}`);
    return aliases;
  }

  if (
    itemId === "p6_header" ||
    itemId === "p9_header" ||
    mentionsAny(combined, "applicant identity for additional information")
  ) {
    if (fieldId) {
      add(`shared_attorney.additional_info_header.${normalizeAdditionalInfoField(fieldId)}`);
    } else {
      add("shared_attorney.additional_info_header");
    }
    return aliases;
  }

  if (
    itemId === "p6_entries" ||
    itemId === "p9_entries" ||
    itemId === "p14_additional_info" ||
    itemId === "p9_additional" ||
    mentionsAny(combined, "additional information entries", "additional information overflow")
  ) {
    if (ADDITIONAL_INFO_ENTRY_FIELDS.has(fieldId)) {
      add(
        `shared_attorney.additional_info_entries.${normalizeAdditionalInfoField(fieldId)}`
      );
    } else if (!fieldId) {
      add("shared_attorney.additional_info_entries");
    }
    return aliases;
  }

  if (
    itemId === "p5_7" ||
    itemId === "p8_7" ||
    (itemType === "single_choice" && combined.includes("preparer") && combined.includes("statement"))
  ) {
    if (fieldId === "preparer_representation_scope") {
      add("shared_attorney.preparer_statement.preparer_representation_scope");
    } else {
      add("shared_attorney.preparer_statement");
    }
    return aliases;
  }

  if (itemId === "p12_interpreter_family_name") {
    add("shared_attorney.interpreter_identity.interpreter_family_name");
    return aliases;
  }
  if (itemId === "p12_interpreter_given_name") {
    add("shared_attorney.interpreter_identity.interpreter_given_name");
    return aliases;
  }
  if (itemId === "p12_interpreter_business") {
    add("shared_attorney.interpreter_identity.interpreter_business_or_organization_name");
    return aliases;
  }
  if (itemId === "p12_interpreter_language") {
    add("shared_attorney.interpreter_signature.interpreter_fluent_language");
    return aliases;
  }

  if (itemId === "p13_preparer_family_name") {
    add("shared_attorney.preparer_identity.preparer_family_name");
    return aliases;
  }
  if (itemId === "p13_preparer_given_name") {
    add("shared_attorney.preparer_identity.preparer_given_name");
    return aliases;
  }
  if (itemId === "p13_preparer_business") {
    add("shared_attorney.preparer_identity.preparer_business_or_organization_name");
    return aliases;
  }
  if (itemId === "p13_preparer_phone") {
    add("shared_attorney.preparer_contact.preparer_daytime_telephone_number");
    return aliases;
  }
  if (itemId === "p13_preparer_mobile") {
    add("shared_attorney.preparer_contact.preparer_mobile_telephone_number");
    return aliases;
  }
  if (itemId === "p13_preparer_email") {
    add("shared_attorney.preparer_contact.preparer_email_address");
    return aliases;
  }
  if (itemId === "p13_preparer_signature_date") {
    add("shared_attorney.preparer_signature.preparer_signature_date");
    return aliases;
  }
  if (itemId === "p13_preparer_address" && fieldId) {
    const mapped = fieldId.startsWith("preparer_") ? fieldId : `preparer_${fieldId}`;
    add(`shared_attorney.preparer_mailing.${mapped}`);
    return aliases;
  }

  if (fieldId.startsWith("interpreter_")) {
    add(`shared_attorney.${interpreterGroupForField(fieldId)}.${fieldId}`);
    return aliases;
  }

  if (fieldId.startsWith("preparer_")) {
    add(`shared_attorney.${preparerGroupForField(fieldId)}.${fieldId}`);
    return aliases;
  }

  if (itemId.includes("interpreter")) {
    if (fieldId === "family_name" || fieldId === "given_name") {
      add(`shared_attorney.interpreter_identity.interpreter_${fieldId}`);
    } else if (itemId === "p6_interpreter_business") {
      add("shared_attorney.interpreter_identity.interpreter_business_or_organization_name");
    }
    return aliases;
  }

  if (itemId.includes("preparer")) {
    if (fieldId === "family_name" || fieldId === "given_name") {
      add(`shared_attorney.preparer_identity.preparer_${fieldId}`);
    } else if (itemId === "p7_preparer_business") {
      add("shared_attorney.preparer_identity.preparer_business_or_organization_name");
    } else if (itemId === "p7_preparer_daytime_phone") {
      add("shared_attorney.preparer_contact.preparer_daytime_telephone_number");
    } else if (itemId === "p7_preparer_email") {
      add("shared_attorney.preparer_contact.preparer_email_address");
    }
    return aliases;
  }

  return aliases;
}
