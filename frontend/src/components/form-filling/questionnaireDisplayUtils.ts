import type { QuestionnaireItem, QuestionnairePage } from "../../types";

const PAGE_HEADER_CODE_RE = /^PAGE_(\d+)_HEADER$/i;
const PAGE_CODE_RE = /^Page\s+(\d+)$/i;
const PART_CODE_RE = /^Part\s+(\d+)$/i;
const SIMPLE_ITEM_CODE_RE = /^\d+(?:\.[a-z0-9]+)?$/i;
const MACHINE_NUMERIC_LABEL_RE = /^0+$/;

/** Internal USCIS reference codes -> readable labels for the form UI. */
export function humanizeQuestionnaireCode(code: string): string {
  const trimmed = code.trim();
  if (!trimmed) {
    return "";
  }

  const pageHeaderMatch = PAGE_HEADER_CODE_RE.exec(trimmed);
  if (pageHeaderMatch) {
    return `Page ${pageHeaderMatch[1]} header`;
  }

  const pageMatch = PAGE_CODE_RE.exec(trimmed);
  if (pageMatch) {
    return `Page ${pageMatch[1]}`;
  }

  const partMatch = PART_CODE_RE.exec(trimmed);
  if (partMatch) {
    return `Part ${partMatch[1]}`;
  }

  if (/^Part\s+\d+/i.test(trimmed)) {
    return trimmed.replace(/\s*\/\s*/g, " / ").replace(/-/g, "–");
  }

  if (/^ATTY\./i.test(trimmed)) {
    return trimmed
      .replace(/^ATTY\./i, "Attorney items ")
      .replace(/-ATTY\./gi, "–")
      .replace(/-/g, "–");
  }

  if (/^Global\./i.test(trimmed)) {
    return trimmed.replace(/^Global\./i, "Global items ").replace(/-/g, "–");
  }

  if (!trimmed.includes(" ") && trimmed.includes("-")) {
    const [start, end] = trimmed.split("-", 2);
    if (start && end) {
      return `Items ${start}–${end}`;
    }
  }

  if (SIMPLE_ITEM_CODE_RE.test(trimmed)) {
    return `Item ${trimmed}`;
  }

  if (trimmed.includes("_")) {
    return trimmed
      .replace(/_/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .replace(/^page\b/i, "Page")
      .replace(/^part\b/i, "Part")
      .replace(/\bheader\b/i, "header");
  }

  return trimmed;
}

export function shouldHideQuestionnaireFieldLabel(label: string): boolean {
  const trimmed = label.trim();
  if (!trimmed) {
    return true;
  }
  if (MACHINE_NUMERIC_LABEL_RE.test(trimmed)) {
    return true;
  }
  if (PAGE_HEADER_CODE_RE.test(trimmed)) {
    return true;
  }
  return false;
}

const LEAVE_EMPTY_DEFAULT_RE = /^leave\s+empty$/i;
const PAGE_HANDLING_SECTION_RE = /page\s+handling/i;

function hasLeaveEmptyDefaultValue(defaultValue: unknown): boolean {
  return typeof defaultValue === "string" && LEAVE_EMPTY_DEFAULT_RE.test(defaultValue.trim());
}

/** Items excluded from PDF mapping are internal filing instructions, not user questions. */
export function isInstructionOnlyQuestionnaireItem(
  item: Pick<
    QuestionnaireItem,
    "exclude_from_form_mapping" | "section" | "code" | "default_value" | "id" | "fields"
  >
): boolean {
  if (item.exclude_from_form_mapping) {
    return true;
  }

  if ((item.fields?.length ?? 0) > 0) {
    return false;
  }

  const section = item.section?.trim() ?? "";
  const code = item.code?.trim() ?? "";
  const id = item.id?.trim() ?? "";

  if (
    PAGE_HANDLING_SECTION_RE.test(section) &&
    PAGE_CODE_RE.test(code) &&
    hasLeaveEmptyDefaultValue(item.default_value)
  ) {
    return true;
  }

  if (/_leave_empty$/i.test(id) && hasLeaveEmptyDefaultValue(item.default_value)) {
    return true;
  }

  return false;
}

export function formatPageNumberList(pageNumbers: number[]): string {
  if (pageNumbers.length === 0) {
    return "";
  }
  if (pageNumbers.length === 1) {
    return String(pageNumbers[0]);
  }
  if (pageNumbers.length === 2) {
    return `${pageNumbers[0]} and ${pageNumbers[1]}`;
  }
  return `${pageNumbers.slice(0, -1).join(", ")}, and ${pageNumbers[pageNumbers.length - 1]}`;
}

export function buildPageHandlingInstructionSummary(
  pages: QuestionnairePage[]
): { section: string; instruction: string; pageNumbers: number[] } | null {
  const instructionPages: Array<{ page: number; item: QuestionnaireItem }> = [];

  for (const page of pages) {
    for (const item of page.items) {
      if (isInstructionOnlyQuestionnaireItem(item)) {
        instructionPages.push({ page: page.page, item });
      }
    }
  }

  if (instructionPages.length === 0) {
    return null;
  }

  const pageNumbers = [...new Set(instructionPages.map((entry) => entry.page))].sort(
    (left, right) => left - right
  );
  const firstItem = instructionPages[0].item;

  return {
    section: firstItem.section || "Form handling",
    instruction:
      firstItem.instruction ||
      "Leave every field on these pages empty for this filing type.",
    pageNumbers,
  };
}

export function getRenderableQuestionnairePages(pages: QuestionnairePage[]): QuestionnairePage[] {
  return pages
    .map((page) => ({
      ...page,
      items: page.items.filter((item) => !isInstructionOnlyQuestionnaireItem(item)),
    }))
    .filter((page) => page.items.length > 0);
}
