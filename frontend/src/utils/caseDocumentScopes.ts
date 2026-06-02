import type { Case, Page } from "../types";

export type CaseDocumentScopeKey =
  | "form_filling_source_document_ids"
  | "qc_checklist_source_document_ids";

export interface CaseSourceDocumentSummary {
  source_document_id: string;
  original_filename: string;
  page_count: number;
  uploaded_at: string;
}

export function listSelectableCaseDocuments(pages: Page[]): CaseSourceDocumentSummary[] {
  const bySourceDocumentId = new Map<string, CaseSourceDocumentSummary>();

  for (const page of pages) {
    const sourceDocumentId = page.source_document_id?.trim();
    if (!sourceDocumentId) {
      continue;
    }

    const existing = bySourceDocumentId.get(sourceDocumentId);
    if (existing) {
      existing.page_count += 1;
      if (page.created_at < existing.uploaded_at) {
        existing.uploaded_at = page.created_at;
      }
      continue;
    }

    bySourceDocumentId.set(sourceDocumentId, {
      source_document_id: sourceDocumentId,
      original_filename: page.original_filename,
      page_count: 1,
      uploaded_at: page.created_at,
    });
  }

  return Array.from(bySourceDocumentId.values()).sort((left, right) => {
    if (left.uploaded_at !== right.uploaded_at) {
      return left.uploaded_at.localeCompare(right.uploaded_at);
    }
    return left.original_filename.localeCompare(right.original_filename, undefined, {
      numeric: true,
      sensitivity: "base",
    });
  });
}

export function resolveSelectedSourceDocumentIds(
  caseData: Case | null | undefined,
  scopeKey: CaseDocumentScopeKey,
  documents: CaseSourceDocumentSummary[]
): string[] {
  const allDocumentIds = documents.map((document) => document.source_document_id);
  const storedValue = caseData?.[scopeKey];
  if (storedValue == null) {
    return allDocumentIds;
  }

  const allowedIds = new Set(storedValue);
  return allDocumentIds.filter((documentId) => allowedIds.has(documentId));
}

export function buildScopeUpdatePayload(
  scopeKey: CaseDocumentScopeKey,
  selectedIds: string[],
  documents: CaseSourceDocumentSummary[]
): Partial<Case> {
  const orderedDocumentIds = documents.map((document) => document.source_document_id);
  const allowedIds = new Set(selectedIds);
  const normalizedSelection = orderedDocumentIds.filter((documentId) => allowedIds.has(documentId));
  const selectsAllDocuments =
    orderedDocumentIds.length > 0 &&
    normalizedSelection.length === orderedDocumentIds.length;

  return {
    [scopeKey]: selectsAllDocuments ? null : normalizedSelection,
  };
}
