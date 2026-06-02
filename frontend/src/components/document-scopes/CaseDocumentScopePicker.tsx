import { useState } from "react";
import {
  FileText,
  FileSearch,
  CheckCircle2,
  Circle,
  Loader2,
  Inbox,
  ChevronDown,
  ChevronUp,
} from "lucide-react";

import { SolidCard } from "../ui/SolidCard";
import { formatLongDateTime } from "../../utils/dateFormat";
import type { CaseSourceDocumentSummary } from "../../utils/caseDocumentScopes";

type ScopePickerLocale = "en" | "es";

const LOCALE_COPY: Record<
  ScopePickerLocale,
  {
    saving: string;
    showDocuments: string;
    hideDocuments: string;
    selectAll: string;
    deselectAll: string;
    noDocuments: string;
    noDocumentsHint: string;
    page: string;
    pages: string;
    selectHint: string;
  }
> = {
  en: {
    saving: "Saving...",
    showDocuments: "Show documents",
    hideDocuments: "Hide documents",
    selectAll: "Select all",
    deselectAll: "Deselect all",
    noDocuments: "No documents",
    noDocumentsHint: "Upload documents to the case so they can be selected here.",
    page: "page",
    pages: "pages",
    selectHint: "Select at least one document to enable automatic analysis.",
  },
  es: {
    saving: "Guardando...",
    showDocuments: "Mostrar documentos",
    hideDocuments: "Ocultar documentos",
    selectAll: "Seleccionar todos",
    deselectAll: "Deseleccionar todos",
    noDocuments: "Sin documentos",
    noDocumentsHint: "Sube documentos al caso para poder seleccionarlos aquí.",
    page: "página",
    pages: "páginas",
    selectHint: "Selecciona al menos un documento para habilitar el análisis automático.",
  },
};

interface Props {
  title: string;
  description: string;
  documents: CaseSourceDocumentSummary[];
  selectedIds: string[];
  saving?: boolean;
  onChange: (nextSelectedIds: string[]) => void;
  collapsible?: boolean;
  defaultCollapsed?: boolean;
  listMaxHeightClassName?: string;
  locale?: ScopePickerLocale;
}

function formatUploadedAt(value: string): string {
  const formatted = formatLongDateTime(value);
  return formatted || "Unknown date";
}

export default function CaseDocumentScopePicker({
  title,
  description,
  documents,
  selectedIds,
  saving = false,
  onChange,
  collapsible = false,
  defaultCollapsed = false,
  listMaxHeightClassName = "max-h-64",
  locale = "en",
}: Props) {
  const copy = LOCALE_COPY[locale];
  const filterId = title.toLowerCase().replace(/[^a-z0-9]+/g, "-");
  const selectedSet = new Set(selectedIds);
  const hasDocuments = documents.length > 0;
  const hasSelection = selectedIds.length > 0;
  const allSelected = hasDocuments && selectedIds.length === documents.length;
  const canCollapse = collapsible && hasDocuments;
  const [isCollapsed, setIsCollapsed] = useState(defaultCollapsed);
  const isContentCollapsed = canCollapse && isCollapsed;
  const detailsId = `${filterId}-scope-details`;

  const toggleDocument = (sourceDocumentId: string, checked: boolean) => {
    const next = new Set(selectedSet);
    if (checked) {
      next.add(sourceDocumentId);
    } else {
      next.delete(sourceDocumentId);
    }
    onChange(Array.from(next));
  };

  const handleToggleAll = () => {
    if (allSelected) {
      onChange([]);
    } else {
      onChange(documents.map((d) => d.source_document_id));
    }
  };

  return (
    <SolidCard className="section-panel-accent p-5">
      <fieldset className="flex flex-col gap-4">
        <legend className="sr-only">{title}</legend>
        
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex items-start gap-3">
            <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-brand-100 text-brand-600">
              <FileSearch className="h-4 w-4" />
            </div>
            <div>
              <p className="panel-section-title">{title}</p>
              <p className="mt-0.5 text-sm text-brand-600 max-w-xl">{description}</p>
            </div>
          </div>
          
          <div className="flex flex-wrap items-center gap-3 self-start sm:self-auto">
            {saving && (
              <div className="flex items-center gap-1.5 text-xs font-medium text-brand-500">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                <span>{copy.saving}</span>
              </div>
            )}
            <span
              className={`rounded-full px-3 py-1 text-xs font-semibold tracking-wide ${
                hasSelection
                  ? "bg-emerald-100 text-emerald-700"
                  : "bg-amber-100 text-amber-700"
              }`}
            >
              {selectedIds.length}/{documents.length || 0} docs
            </span>
            {canCollapse && (
              <button
                type="button"
                aria-expanded={!isContentCollapsed}
                aria-controls={detailsId}
                onClick={() => setIsCollapsed((current) => !current)}
                className="inline-flex items-center gap-1.5 rounded-xl border border-brand-100 bg-nova-snow px-3 py-1.5 text-xs font-semibold text-brand-700 shadow-sm transition hover:border-brand-200 hover:bg-brand-50 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-1"
              >
                {isContentCollapsed ? (
                  <>
                    <ChevronDown className="h-3.5 w-3.5" />
                    <span>{copy.showDocuments}</span>
                  </>
                ) : (
                  <>
                    <ChevronUp className="h-3.5 w-3.5" />
                    <span>{copy.hideDocuments}</span>
                  </>
                )}
              </button>
            )}
            <button
              type="button"
              onClick={handleToggleAll}
              disabled={!hasDocuments}
              className="rounded-xl border border-brand-100 bg-nova-snow px-3 py-1.5 text-xs font-semibold text-brand-700 shadow-sm transition hover:border-brand-200 hover:bg-brand-50 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {allSelected ? copy.deselectAll : copy.selectAll}
            </button>
          </div>
        </div>

        {isContentCollapsed ? (
          <div>
          </div>
        ) : (
          <div id={detailsId} className="flex flex-col gap-4">
            {!hasDocuments ? (
              <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-brand-100 bg-white/60 py-8 text-center">
                <Inbox className="h-8 w-8 text-brand-300" />
                <p className="mt-2 text-sm font-medium text-brand-900">{copy.noDocuments}</p>
                <p className="mt-1 text-xs text-brand-500">
                  {copy.noDocumentsHint}
                </p>
              </div>
            ) : (
              <div
                className={`${listMaxHeightClassName} overflow-y-auto rounded-2xl border border-brand-100/80 bg-white/60 p-1.5 shadow-inner custom-scroll`}
              >
                <div className="flex flex-col gap-1">
                  {documents.map((document) => {
                    const checked = selectedSet.has(document.source_document_id);
                    return (
                      <label
                        key={document.source_document_id}
                        className={`group relative flex cursor-pointer items-center gap-3 rounded-xl border p-3 transition-all ${
                          checked
                            ? "border-brand-200 bg-brand-50/50 shadow-sm"
                            : "border-transparent hover:bg-brand-50/70"
                        }`}
                      >
                        <input
                          type="checkbox"
                          className="peer sr-only"
                          checked={checked}
                          onChange={(event) =>
                            toggleDocument(document.source_document_id, event.target.checked)
                          }
                        />
                        <div
                          className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full transition-colors ${
                            checked
                              ? "text-brand-600"
                              : "text-brand-300 group-hover:text-brand-400"
                          }`}
                        >
                          {checked ? (
                            <CheckCircle2 className="h-5 w-5" />
                          ) : (
                            <Circle className="h-5 w-5" />
                          )}
                        </div>

                        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white shadow-sm ring-1 ring-brand-100">
                          <FileText
                            className={`h-4 w-4 ${checked ? "text-brand-500" : "text-brand-400"}`}
                          />
                        </div>

                        <div className="min-w-0 flex-1">
                          <p
                            className={`truncate text-sm font-medium transition-colors ${
                              checked ? "text-brand-900" : "text-brand-700"
                            }`}
                          >
                            {document.original_filename}
                          </p>
                          <p className="mt-0.5 flex items-center gap-1.5 text-xs text-brand-500">
                            <span className="font-medium">
                              {document.page_count}{" "}
                              {document.page_count === 1 ? copy.page : copy.pages}
                            </span>
                            <span>&bull;</span>
                            <span>{formatUploadedAt(document.uploaded_at)}</span>
                          </p>
                        </div>
                      </label>
                    );
                  })}
                </div>
              </div>
            )}

            {!hasSelection && hasDocuments && (
              <div className="flex items-center gap-2 rounded-xl border border-brand-100 bg-brand-50/70 px-4 py-3 text-xs text-brand-700">
                <div className="h-1.5 w-1.5 shrink-0 rounded-full bg-brand-500" />
                <p>{copy.selectHint}</p>
              </div>
            )}
          </div>
        )}
      </fieldset>
    </SolidCard>
  );
}
