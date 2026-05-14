/**
 * Centralised API client using axios.
 * All calls go through the Vite proxy → FastAPI backend.
 */

import axios from "axios";
import toast from "react-hot-toast";
import type {
  AuditEntry,
  AutofillJobStatus,
  AutopilotJob,
  Case,
  FormTypeInfo,
  TeamDetail,
  TeamSummary,
  Checklist,
  ChecklistItem,
  DocumentType,
  EvidenceLink,
  ExtractionResult,
  ExtractionStatus,
  Page,
  PageSectionLink,
  QuestionnaireAnswerMap,
  QuestionnaireAutofillResponse,
  QuestionnairePage,
  RagQueryResponse,
  SaveQuestionnaireAnswerPayload,
  Section,
  SupervisorCase,
  Template,
  FormFillingJob,
  VerificationMap,
} from "../types";

const api = axios.create({ baseURL: import.meta.env.VITE_API_URL || "/api" });

const AUTOFILL_HTTP_TIMEOUT_MS = 30_000;
const AUTOFILL_POLL_INTERVAL_MS = 5_000;
const AUTOFILL_MAX_TOTAL_MS = 60 * 60 * 1000;
const AUTOFILL_POLL_MAX_TRANSIENT_FAILURES = 5;

function _isTransientNetworkError(error: unknown): boolean {
  if (!axios.isAxiosError(error)) return false;
  if (error.code === "ECONNABORTED") return true;
  if (error.code === "ERR_NETWORK") return true;
  if (/timeout/i.test(error.message || "")) return true;
  const status = error.response?.status ?? 0;
  return status === 502 || status === 503 || status === 504;
}

api.interceptors.request.use((config) => {
  const token = sessionStorage.getItem("auth_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

/* ── Cases ──────────────────────────────────────────────────────────── */

export const getCases = () => api.get<Case[]>("/cases").then((r) => r.data);

export const getSupervisorCases = () =>
  api.get<SupervisorCase[]>("/supervisor/cases").then((r) => r.data);

export const getSupervisorTeamCases = (teamUuid: string) =>
  api
    .get<SupervisorCase[]>(`/supervisor/teams/${teamUuid}/cases`)
    .then((r) => r.data);

export const getTeams = () =>
  api.get<TeamSummary[]>("/teams").then((r) => r.data);

export interface CreateTeamPayload {
  name: string;
  users?: { id: number; is_primary?: boolean }[];
}

export const createTeam = (payload: CreateTeamPayload) =>
  api
    .post<TeamDetail>("/teams", {
      name: payload.name,
      users: payload.users ?? [],
    })
    .then((r) => r.data);

export interface UpdateTeamPayload {
  name?: string;
  users: { id: number; uuid_team_user?: string; is_primary?: boolean }[];
}

export const updateTeam = (teamUuid: string, payload: UpdateTeamPayload) =>
  api
    .put<TeamDetail>(`/teams/${teamUuid}`, payload)
    .then((r) => r.data);

export const getTeamUsers = (teamUuid: string) =>
  api.get<TeamDetail>(`/teams/${teamUuid}/users`).then((r) => r.data);

export const getCase = (id: string) =>
  api.get<Case>(`/cases/${id}`).then((r) => r.data);

export const createCase = (name: string, description = "") =>
  api.post<Case>("/cases", { name, description }).then((r) => r.data);

export const updateCase = (id: string, data: Partial<Case>) =>
  api.put<Case>(`/cases/${id}`, data).then((r) => r.data);

export const deleteCase = (id: string) => api.delete(`/cases/${id}`);

/* ── Document Types ─────────────────────────────────────────────────── */

export const getDocumentTypes = (caseId: string) =>
  api
    .get<DocumentType[]>(`/cases/${caseId}/document-types`)
    .then((r) => r.data);

export const createDocumentType = (
  caseId: string,
  data: { name: string; code: string; order?: number; has_tables?: boolean }
) =>
  api
    .post<DocumentType>(`/cases/${caseId}/document-types`, data)
    .then((r) => r.data);

export const updateDocumentType = (
  id: string,
  data: Partial<{ name: string; code: string; order: number; has_tables: boolean }>
) => api.put<DocumentType>(`/document-types/${id}`, data).then((r) => r.data);

export const deleteDocumentType = (id: string) =>
  api.delete(`/document-types/${id}`);

export const reorderDocumentTypes = (
  items: { id: string; order: number }[]
) => api.put("/document-types/reorder", { items });

/* ── Sections ───────────────────────────────────────────────────────── */

export const createSection = (
  dtId: string,
  data: { name: string; code: string; order?: number; is_required?: boolean; parent_section_id?: string }
) =>
  api
    .post<Section>(`/document-types/${dtId}/sections`, data)
    .then((r) => r.data);

export const updateSection = (
  id: string,
  data: Partial<Section>
) => api.put<Section>(`/sections/${id}`, data).then((r) => r.data);

export const deleteSection = (id: string) => api.delete(`/sections/${id}`);

export const reorderSections = (items: { id: string; order: number }[]) =>
  api.put("/sections/reorder", { items });

export const getAllSectionsFlat = (caseId: string) =>
  api.get<Section[]>(`/cases/${caseId}/sections-flat`).then((r) => r.data);

/* ── Pages ──────────────────────────────────────────────────────────── */

export const uploadFiles = (caseId: string, files: File[]) => {
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  return api
    .post<Page[]>(`/cases/${caseId}/upload`, fd, {
      headers: { "Content-Type": "multipart/form-data" },
    })
    .then((r) => r.data);
};

export const getPages = (
  caseId: string,
  params?: { status?: string; section_id?: string; document_type_id?: string }
) => api.get<Page[]>(`/cases/${caseId}/pages`, { params }).then((r) => r.data);

export const classifyPage = (
  pageId: string,
  data: {
    document_type_id: string;
    section_id: string;
    order_in_section?: number;
  }
) => api.put<Page>(`/pages/${pageId}/classify`, data).then((r) => r.data);

export const unclassifyPage = (pageId: string) =>
  api.put<Page>(`/pages/${pageId}/unclassify`).then((r) => r.data);

export const markExtra = (pageId: string) =>
  api.put<Page>(`/pages/${pageId}/extra`).then((r) => r.data);

export const reorderPages = (
  sectionId: string,
  pages: { page_id: string; order_in_section: number }[]
) => api.put("/pages/reorder", { section_id: sectionId, pages });

export const deletePage = (pageId: string) => api.delete(`/pages/${pageId}`);

/* ── Page Section Links (multi-section) ────────────────────────────── */

export const getPageLinks = (pageId: string) =>
  api.get<PageSectionLink[]>(`/pages/${pageId}/section-links`).then((r) => r.data);

export const addPageSectionLink = (
  pageId: string,
  data: { section_id: string; is_primary?: boolean }
) =>
  api.post<Page>(`/pages/${pageId}/section-links`, data).then((r) => r.data);

export const removePageSectionLink = (pageId: string, sectionId: string) =>
  api.delete<Page>(`/pages/${pageId}/section-links/${sectionId}`).then((r) => r.data);

export const setPagePrimaryLink = (pageId: string, sectionId: string) =>
  api.put<Page>(`/pages/${pageId}/section-links/primary`, { section_id: sectionId }).then((r) => r.data);

/* ── Checklists ─────────────────────────────────────────────────────── */

export const createChecklist = (caseId: string, name: string) =>
  api
    .post<Checklist>(`/cases/${caseId}/checklists`, { name })
    .then((r) => r.data);

export const deleteChecklist = (id: string) =>
  api.delete(`/checklists/${id}`);

export const createChecklistItem = (
  clId: string,
  data: { description: string; order?: number; target_section_ids?: string[] }
) =>
  api
    .post<ChecklistItem>(`/checklists/${clId}/items`, data)
    .then((r) => r.data);

export const updateChecklistItem = (
  itemId: string,
  data: Partial<ChecklistItem> & { target_section_ids?: string[] }
) =>
  api
    .put<ChecklistItem>(`/checklist-items/${itemId}`, data)
    .then((r) => r.data);

export const deleteChecklistItem = (itemId: string) =>
  api.delete(`/checklist-items/${itemId}`);

export const upsertItemTargets = (
  itemId: string,
  sectionIds: string[]
) =>
  api
    .put<ChecklistItem>(`/checklist-items/${itemId}/targets`, {
      target_section_ids: sectionIds,
    })
    .then((r) => r.data);

export const addEvidence = (
  itemId: string,
  data: { page_id: string; notes?: string }
) =>
  api
    .post<EvidenceLink>(`/checklist-items/${itemId}/evidence`, data)
    .then((r) => r.data);

export const removeEvidence = (evId: string) =>
  api.delete(`/evidence-links/${evId}`);

/* ── Templates ─────────────────────────────────────────────────────── */

export const getTemplates = () =>
  api.get<Template[]>("/templates").then((r) => r.data);

export const createTemplate = (name: string, description = "") =>
  api.post<Template>("/templates", { name, description }).then((r) => r.data);

export const getTemplate = (id: string) =>
  api.get<Template>(`/templates/${id}`).then((r) => r.data);

export const deleteTemplate = (id: string) =>
  api.delete(`/templates/${id}`);

export const createTemplateNode = (
  tplId: string,
  data: {
    name: string;
    code: string;
    node_type?: string;
    has_tables?: boolean;
    is_required?: boolean;
    parent_node_id?: string;
    order?: number;
  }
) =>
  api.post(`/templates/${tplId}/nodes`, data).then((r) => r.data);

export const deleteTemplateNode = (nodeId: string) =>
  api.delete(`/template-nodes/${nodeId}`);

export const createTemplateChecklist = (
  tplId: string,
  data: { name: string; items?: { description: string; order?: number; target_node_ids?: string[] }[] }
) =>
  api.post(`/templates/${tplId}/checklists`, data).then((r) => r.data);

export const addTemplateChecklistItem = (
  clId: string,
  data: { description: string; order?: number; target_node_ids?: string[] }
) =>
  api.post(`/template-checklists/${clId}/items`, data).then((r) => r.data);

export const applyTemplate = (caseId: string, templateId: string) =>
  api
    .post(`/cases/${caseId}/apply-template`, { template_id: templateId })
    .then((r) => r.data);

/* ── QC Checklists (complex hierarchical) ──────────────────────────── */

import type { QCChecklist, QCPart, QCQuestion } from "../types";

export const getQCTemplates = () =>
  api.get<QCChecklist[]>("/qc-templates").then((r) => r.data);

export const getCaseQCChecklists = (caseId: string) =>
  api.get<QCChecklist[]>(`/cases/${caseId}/qc-checklists`).then((r) => r.data);

export const createQCChecklist = (data: { name: string; description?: string; is_template?: boolean }, caseId?: string) =>
  api.post<QCChecklist>("/qc-checklists", data, { params: caseId ? { case_id: caseId } : {} }).then((r) => r.data);

export const getQCChecklist = (id: string) =>
  api.get<QCChecklist>(`/qc-checklists/${id}`).then((r) => r.data);

export const deleteQCChecklist = (id: string) =>
  api.delete(`/qc-checklists/${id}`);

export const applyQCTemplate = (caseId: string, templateId: string) =>
  api.post<QCChecklist>(`/cases/${caseId}/qc-checklists/apply/${templateId}`).then((r) => r.data);

export const createQCPart = (clId: string, data: { name: string; code: string; order?: number; parent_part_id?: string }) =>
  api.post<QCPart>(`/qc-checklists/${clId}/parts`, data).then((r) => r.data);

export const updateQCPart = (partId: string, data: Partial<{ name: string; code: string; order: number }>) =>
  api.put<QCPart>(`/qc-parts/${partId}`, data).then((r) => r.data);

export const deleteQCPart = (partId: string) =>
  api.delete(`/qc-parts/${partId}`);

export const createQCQuestion = (partId: string, data: { code: string; description: string; where_to_verify?: string; order?: number }) =>
  api.post<QCQuestion>(`/qc-parts/${partId}/questions`, data).then((r) => r.data);

export const updateQCQuestion = (qId: string, data: Partial<{ code: string; description: string; where_to_verify: string; order: number; answer: string; correction: string; notes: string; target_section_ids: string[] }>) =>
  api.put<QCQuestion>(`/qc-questions/${qId}`, data).then((r) => r.data);

export const deleteQCQuestion = (qId: string) =>
  api.delete(`/qc-questions/${qId}`);

export const addQCEvidence = (qId: string, data: { page_id: string; notes?: string }) =>
  api.post(`/qc-questions/${qId}/evidence`, data).then((r) => r.data);

export const deleteQCEvidence = (evId: string) =>
  api.delete(`/qc-evidence/${evId}`);

export const seedI914Template = () =>
  api.post("/qc-checklists/seed/i914").then((r) => r.data);

export const seedI765Template = () =>
  api.post("/qc-checklists/seed/i765").then((r) => r.data);

export const seedI192Template = () =>
  api.post("/qc-checklists/seed/i192").then((r) => r.data);

export const seedAllQCTemplates = () =>
  api.post("/qc-checklists/seed/all").then((r) => r.data);

export const seedI914DocTaxonomy = () =>
  api.post("/templates/seed/i914-docs").then((r) => r.data);

export const saveQCAsTemplate = (clId: string) =>
  api.post(`/qc-checklists/${clId}/save-as-template`).then((r) => r.data);

export const saveDocTaxonomyAsTemplate = (caseId: string, name?: string) =>
  api.post(`/cases/${caseId}/save-doc-template`, null, { params: name ? { name } : {} }).then((r) => r.data);

export const aiVerifyQuestion = (qId: string) =>
  api.post<QCQuestion>(`/qc-questions/${qId}/ai-verify`).then((r) => r.data);

export const aiVerifyPart = (partId: string) =>
  api.post(`/qc-parts/${partId}/ai-verify-all`).then((r) => r.data);

/* ── QC Link Presets ───────────────────────────────────────────────── */

import type { QCLinkPreset } from "../types";

export const saveLinkPreset = (clId: string, data: { name?: string; doc_template_id?: string }) =>
  api.post<QCLinkPreset>(`/qc-checklists/${clId}/link-presets`, data).then((r) => r.data);

export const getLinkPresets = (qcTemplateId?: string) =>
  api.get<QCLinkPreset[]>("/qc-link-presets", { params: qcTemplateId ? { qc_template_id: qcTemplateId } : {} }).then((r) => r.data);

export const deleteLinkPreset = (presetId: string) =>
  api.delete(`/qc-link-presets/${presetId}`);

export const applyLinkPreset = (caseId: string, clId: string, presetId: string) =>
  api.post<QCChecklist>(`/cases/${caseId}/qc-checklists/${clId}/apply-link-preset/${presetId}`).then((r) => r.data);

export const autoLinkQCSections = (caseId: string, clId: string) =>
  api.post<QCChecklist>(`/cases/${caseId}/qc-checklists/${clId}/auto-link-sections`).then((r) => r.data);

/* ── Export ──────────────────────────────────────────────────────────── */

function downloadBlob(data: Blob, filename: string) {
  const url = URL.createObjectURL(data);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function withCacheKey(endpoint: string, cacheKey?: string | null) {
  const normalizedCacheKey = cacheKey?.trim();
  if (!normalizedCacheKey) {
    return endpoint;
  }
  const separator = endpoint.includes("?") ? "&" : "?";
  return `${endpoint}${separator}v=${encodeURIComponent(normalizedCacheKey)}`;
}

async function exportFile(endpoint: string, fallbackName: string, cacheKey?: string | null) {
  const toastId = toast.loading("Preparando documento para descarga…");
  try {
    const res = await api.get(withCacheKey(endpoint, cacheKey), { responseType: "blob" });
    const disposition = res.headers["content-disposition"] ?? "";
    const match = disposition.match(/filename="?([^"]+)"?/);
    const filename = match?.[1] ?? fallbackName;
    downloadBlob(res.data, filename);
    toast.success("Descarga iniciada", { id: toastId });
  } catch (err) {
    toast.error("Error al preparar la descarga", { id: toastId });
  }
}

export const downloadExportPdf = (caseId: string) =>
  exportFile(`/cases/${caseId}/export/pdf`, `expediente_${caseId}.pdf`);

export const downloadExportReport = (caseId: string) =>
  exportFile(`/cases/${caseId}/export/report`, `reporte_${caseId}.pdf`);

export const downloadExportQCReport = (caseId: string) =>
  exportFile(`/cases/${caseId}/export/qc-report`, `qc_reporte_${caseId}.pdf`);

export const downloadExportSingleQCReport = (caseId: string, clId: string) =>
  exportFile(`/cases/${caseId}/export/qc-report/${clId}`, `qc_reporte_${clId}.pdf`);

/* ── Form Filling ──────────────────────────────────────────────────── */

export const getAvailableFormTypes = () =>
  api.get<FormTypeInfo[]>("/questionnaire/form-types").then((r) => r.data);

export const getSharedQuestions = () =>
  api.get<QuestionnairePage[]>("/questionnaire/shared-questions").then((r) => r.data);

export const getFormClientQuestions = (formType: string) =>
  api
    .get<QuestionnairePage[]>(`/questionnaire/${formType}/client-questions`)
    .then((r) => r.data);

export const getFormAttorneyQuestions = (formType: string) =>
  api
    .get<QuestionnairePage[]>(`/questionnaire/${formType}/attorney-questions`)
    .then((r) => r.data);

export const getQuestionnaireAnswers = (caseId: string, formType?: string) =>
  api
    .get<QuestionnaireAnswerMap>(`/cases/${caseId}/questionnaire/answers`, {
      params: formType ? { form_type: formType } : {},
    })
    .then((r) => r.data);

export const getQuestionnaireVerifications = (caseId: string, formType?: string) =>
  api
    .get<VerificationMap>(`/cases/${caseId}/questionnaire/verifications`, {
      params: formType ? { form_type: formType } : {},
    })
    .then((r) => r.data);

export const saveQuestionnaireAnswers = (
  caseId: string,
  answers: SaveQuestionnaireAnswerPayload[]
) =>
  api
    .post<{ saved_count: number }>(`/cases/${caseId}/questionnaire/answers`, { answers })
    .then((r) => r.data);

interface AutofillOcrCallbacks {
  onOcrProgress?: (msg: string, pct: number) => void;
  onOcrComplete?: () => void;
  onJobStarted?: (jobId: string) => void;
  signal?: AbortSignal;
}

async function runAutofillJob(
  caseId: string,
  kind: "shared" | "attorney",
  callbacks?: AutofillOcrCallbacks,
): Promise<QuestionnaireAutofillResponse> {
  const startEndpoint = `/cases/${caseId}/questionnaire/${kind}/autofill`;
  const startRes = await api.post<AutofillJobStatus>(startEndpoint, null, {
    timeout: AUTOFILL_HTTP_TIMEOUT_MS,
    validateStatus: (s) => (s >= 200 && s < 300) || s === 202,
    signal: callbacks?.signal,
  });

  const job = startRes.data;
  if (!job || !job.id) {
    throw new Error("Autofill could not be started: no job id returned by server.");
  }
  callbacks?.onJobStarted?.(job.id);

  const statusEndpoint = `/questionnaire/autofill-jobs/${job.id}`;
  const startedAt = Date.now();
  let lastStatus: AutofillJobStatus["status"] | null = null;
  let transientFailures = 0;

  while (true) {
    if (Date.now() - startedAt > AUTOFILL_MAX_TOTAL_MS) {
      throw new Error("Autofill exceeded the maximum allowed time. Please try again later.");
    }
    if (callbacks?.signal?.aborted) {
      try {
        await api.delete(statusEndpoint, { timeout: AUTOFILL_HTTP_TIMEOUT_MS });
      } catch {
        // best-effort cancellation
      }
      throw new DOMException("Autofill cancelled", "AbortError");
    }

    let current: AutofillJobStatus;
    try {
      const statusRes = await api.get<AutofillJobStatus>(statusEndpoint, {
        timeout: AUTOFILL_HTTP_TIMEOUT_MS,
        signal: callbacks?.signal,
      });
      current = statusRes.data;
      transientFailures = 0;
    } catch (err) {
      if (axios.isCancel?.(err) || (err as { name?: string })?.name === "CanceledError") {
        throw err;
      }
      if (_isTransientNetworkError(err)) {
        transientFailures += 1;
        if (transientFailures >= AUTOFILL_POLL_MAX_TRANSIENT_FAILURES) {
          throw new Error(
            "Lost connection to the autofill service. The job is still running on the server; please refresh in a few moments.",
          );
        }
        await new Promise((r) => setTimeout(r, AUTOFILL_POLL_INTERVAL_MS));
        continue;
      }
      throw err;
    }

    const wasOcrPreparing = lastStatus === "ocr_preparing";
    if (current.status === "ocr_preparing") {
      callbacks?.onOcrProgress?.(
        current.progress_message ||
          `Reading documents... (${current.ocr_processed_pages}/${current.ocr_total_pages} pages)`,
        Math.round(Math.max(current.progress_pct, 2)),
      );
    } else if (current.status === "queued" || current.status === "running") {
      if (wasOcrPreparing) {
        callbacks?.onOcrComplete?.();
      }
      callbacks?.onOcrProgress?.(
        current.progress_message || "Analyzing answers...",
        Math.round(current.progress_pct),
      );
    }
    lastStatus = current.status;

    if (current.status === "completed") {
      if (!current.result) {
        throw new Error("Autofill completed but no result payload was returned.");
      }
      return current.result;
    }
    if (current.status === "failed") {
      throw new Error(current.error || "Autofill failed.");
    }
    if (current.status === "cancelled") {
      throw new DOMException("Autofill cancelled", "AbortError");
    }

    await new Promise((r) => setTimeout(r, AUTOFILL_POLL_INTERVAL_MS));
  }
}

export const autofillSharedQuestionnaireAnswers = (
  caseId: string,
  callbacks?: AutofillOcrCallbacks,
) => runAutofillJob(caseId, "shared", callbacks);

export const autofillAttorneyAnswers = (
  caseId: string,
  callbacks?: AutofillOcrCallbacks,
) => runAutofillJob(caseId, "attorney", callbacks);

export const cancelAutofillJob = (jobId: string) =>
  api
    .delete<AutofillJobStatus>(`/questionnaire/autofill-jobs/${jobId}`, {
      timeout: AUTOFILL_HTTP_TIMEOUT_MS,
    })
    .then((r) => r.data);

export const getAutofillJob = (jobId: string) =>
  api
    .get<AutofillJobStatus>(`/questionnaire/autofill-jobs/${jobId}`, {
      timeout: AUTOFILL_HTTP_TIMEOUT_MS,
    })
    .then((r) => r.data);

export const getActiveAutofillJob = (
  caseId: string,
  kind: "shared" | "attorney",
) =>
  api
    .get<AutofillJobStatus | null>(
      `/cases/${caseId}/questionnaire/${kind}/autofill-jobs/active`,
      { timeout: AUTOFILL_HTTP_TIMEOUT_MS },
    )
    .then((r) => r.data);

export const generateFormFromAnswers = (caseId: string, formType: string) =>
  api
    .post<FormFillingJob>(`/cases/${caseId}/form-fill/generate`, { form_type: formType })
    .then((r) => r.data);

export const getFormFillingJobs = (caseId: string) =>
  api.get<FormFillingJob[]>(`/cases/${caseId}/form-fill/jobs`).then((r) => r.data);

export const getFormFillingJobStatus = (jobId: string) =>
  api.get<FormFillingJob>(`/form-fill/jobs/${jobId}`).then((r) => r.data);

export const regenerateFilledPdf = (jobId: string, preserveManualCorrections = true) =>
  api.post<FormFillingJob>(`/form-fill/jobs/${jobId}/regenerate`, {
    preserve_manual_corrections: preserveManualCorrections,
  }).then((r) => r.data);

export const downloadFilledPdf = (
  jobId: string,
  fallbackName: string,
  cacheKey?: string | null
) => exportFile(`/form-fill/jobs/${jobId}/download`, fallbackName, cacheKey);

export const getFilledPdfBlobUrl = async (jobId: string, cacheKey?: string | null) => {
  const res = await api.get(withCacheKey(`/form-fill/jobs/${jobId}/download`, cacheKey), {
    responseType: "blob",
  });
  return URL.createObjectURL(res.data);
};

export const deleteFormFillingJob = (jobId: string) =>
  api.delete(`/form-fill/jobs/${jobId}`);

/* ── Extraction / OCR ──────────────────────────────────────────────── */

export const getExtractionStatus = () =>
  api.get<ExtractionStatus>("/extraction/status").then((r) => r.data);

export const extractPage = (pageId: string, hasTables?: boolean) =>
  api
    .post<ExtractionResult>(
      `/pages/${pageId}/extract`,
      null,
      { params: hasTables !== undefined ? { has_tables: hasTables } : {} }
    )
    .then((r) => r.data);

export const getExtraction = (pageId: string) =>
  api
    .get<ExtractionResult>(`/pages/${pageId}/extraction`)
    .then((r) => r.data);

export const extractBatch = (
  caseId: string,
  pageIds: string[],
  hasTables?: boolean
) =>
  api
    .post(`/cases/${caseId}/extract-batch`, {
      page_ids: pageIds,
      has_tables: hasTables,
    })
    .then((r) => r.data);

/* ── Pinecone Indexing / Reindex ──────────────────────────────────── */

export const reindexPage = (pageId: string) =>
  api.post<{ queued: number; page_ids: string[] }>(`/pages/${pageId}/reindex`).then((r) => r.data);

export const reindexCase = (caseId: string) =>
  api.post<{ queued: number; page_ids: string[] }>(`/cases/${caseId}/reindex`).then((r) => r.data);

/* ── RAG Semantic Query ──────────────────────────────────────────── */

export const ragQuery = (
  caseId: string,
  question: string,
  opts?: { top_k?: number; page_ids?: string[]; section_ids?: string[]; document_type_ids?: string[] }
) =>
  api
    .post<RagQueryResponse>(`/cases/${caseId}/rag/query`, {
      question,
      top_k: opts?.top_k,
      page_ids: opts?.page_ids ?? [],
      section_ids: opts?.section_ids ?? [],
      document_type_ids: opts?.document_type_ids ?? [],
    })
    .then((r) => r.data);

/* ── QC Semantic Query ───────────────────────────────────────────── */

export const qcSemanticQuery = (clId: string, question: string, topK = 3) =>
  api
    .post<RagQueryResponse>(`/qc-checklists/${clId}/semantic-query`, {
      question,
      top_k: topK,
    })
    .then((r) => r.data);

/* ── AI Autopilot ────────────────────────────────────────────────── */

export const startAutopilot = (clId: string) =>
  api.post<AutopilotJob>(`/qc-checklists/${clId}/ai-autopilot`).then((r) => r.data);

export const getAutopilotJob = (jobId: string) =>
  api.get<AutopilotJob>(`/qc-autopilot-jobs/${jobId}`).then((r) => r.data);

/* ── Audit ──────────────────────────────────────────────────────────── */

export const getAuditLog = (caseId: string) =>
  api.get<AuditEntry[]>(`/cases/${caseId}/audit`).then((r) => r.data);

/* ── Users & Roles (admin) ──────────────────────────────────────────── */

export interface UserRoleRef {
  id: number;
  name: string;
}

export interface UserDetail {
  id: number;
  email: string;
  name: string;
  roles: UserRoleRef[];
  permissions: string[];
  created_at?: string;
}

export interface RoleDetail {
  id: number;
  name: string;
  permissions?: { id: number; name: string }[];
  created_at?: string;
}

export const getUsers = () =>
  api.get<UserDetail[]>("/users").then((r) => r.data);

export const updateUserRoles = (userId: number, roleIds: number[]) =>
  api
    .put<UserDetail>(`/users/${userId}/roles`, { role_ids: roleIds })
    .then((r) => r.data);

export const deleteUser = (userId: number) =>
  api.delete(`/users/${userId}`);

export const getRoles = () =>
  api.get<RoleDetail[]>("/roles").then((r) => r.data);

/* ── Auth / SSO ────────────────────────────────────────────────────── */

export interface AuthUser {
  id: number;
  email: string;
  name: string;
  roles: string[];
  permissions: string[];
}

interface SSOLoginPayload {
  email: string;
  name: string;
  first_name?: string;
  last_name?: string;
  role?: string;
  signature: string;
}

interface SSOLoginResult {
  token: string;
  user: AuthUser;
}

export const authApi = {
  ssoLogin: (data: SSOLoginPayload) =>
    api.post<SSOLoginResult>("/sso-login", data).then((r) => r.data),

  getMe: () =>
    api.get<AuthUser>("/auth/me").then((r) => r.data),
};
