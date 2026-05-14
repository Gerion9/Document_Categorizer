export type MissingRequiredField = {
  inputId: string;
  label: string;
  rowLabel?: string;
  sectionCode?: string;
  kind: "required" | "review";
};

function getMissingFieldCounts(fields: MissingRequiredField[]): {
  required: number;
  review: number;
} {
  return fields.reduce(
    (counts, field) => {
      if (field.kind === "review") {
        counts.review += 1;
      } else {
        counts.required += 1;
      }
      return counts;
    },
    { required: 0, review: 0 }
  );
}

export function formatPendingFieldLabel(field: MissingRequiredField | null): string {
  if (!field) {
    return "";
  }
  return `Section ${field.sectionCode || "pending"}: "${field.label}"${field.rowLabel ? ` (${field.rowLabel})` : ""}.`;
}

export function getClientPendingFieldsLead(fields: MissingRequiredField[]): string {
  const counts = getMissingFieldCounts(fields);
  if (counts.required > 0 && counts.review > 0) {
    return `Complete ${counts.required} required field${counts.required === 1 ? "" : "s"} and review ${counts.review} pending field${counts.review === 1 ? "" : "s"} in optional client sections before continuing.`;
  }
  if (counts.required > 0) {
    return `Complete ${counts.required} required field${counts.required === 1 ? "" : "s"} in the client details before continuing.`;
  }
  return `Review ${counts.review} pending field${counts.review === 1 ? "" : "s"} in optional client sections before continuing.`;
}

export function getClientConfirmationBlockMessage(fields: MissingRequiredField[]): string {
  if (fields.length === 0) {
    return "Confirm the current client answers before generating the PDF preview.";
  }
  const counts = getMissingFieldCounts(fields);
  if (counts.required > 0) {
    return "Confirm the required client answers before generating the PDF preview.";
  }
  return "Review and confirm the pending client details in optional sections before generating the PDF preview.";
}

export function getClientRegenerationBlockMessage(fields: MissingRequiredField[]): string {
  if (fields.length === 0) {
    return "Confirm the current client answers before generating another PDF.";
  }
  const counts = getMissingFieldCounts(fields);
  if (counts.required > 0) {
    return "Confirm the required client answers before generating another PDF.";
  }
  return "Review and confirm the pending client details in optional sections before generating another PDF.";
}

export function getPreviewStepBlockedMessage(fields: MissingRequiredField[]): string {
  if (fields.length === 0) {
    return "Confirm client answers to continue";
  }
  const counts = getMissingFieldCounts(fields);
  if (counts.required > 0) {
    return "Confirm required client answers to continue";
  }
  return "Review pending optional-section answers to continue";
}
