import type { QCChecklist } from "../types";

export type QcTemplateCategory = "visa-t" | "sijs";

export interface QcTemplateGroup {
  id: QcTemplateCategory;
  label: string;
  templates: QCChecklist[];
}

const CATEGORY_ORDER: QcTemplateCategory[] = ["visa-t", "sijs"];

const CATEGORY_LABELS: Record<QcTemplateCategory, string> = {
  "visa-t": "Visa T",
  sijs: "SIJS",
};

/** Maps a QC template display name to Visa T or SIJS (aligned with backend form_registry). */
export function resolveQcTemplateCategory(templateName: string): QcTemplateCategory {
  const normalized = templateName.toLowerCase();
  if (normalized.includes("sijs") || normalized.includes("i-360")) {
    return "sijs";
  }
  return "visa-t";
}

export function groupQcTemplates(templates: QCChecklist[]): QcTemplateGroup[] {
  const buckets: Record<QcTemplateCategory, QCChecklist[]> = {
    "visa-t": [],
    sijs: [],
  };

  for (const template of templates) {
    buckets[resolveQcTemplateCategory(template.name)].push(template);
  }

  return CATEGORY_ORDER.map((id) => ({
    id,
    label: CATEGORY_LABELS[id],
    templates: [...buckets[id]].sort((a, b) =>
      a.name.localeCompare(b.name, "en", { sensitivity: "base" })
    ),
  })).filter((group) => group.templates.length > 0);
}
