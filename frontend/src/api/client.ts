/**
 * Centralised API client using axios.
 * All calls go through the Vite proxy → FastAPI backend.
 */

import axios from "axios";
import type {
  AuditEntry,
  Case,
  Checklist,
  ChecklistItem,
  DocumentType,
  EvidenceLink,
  ExtractionResult,
  Page,
  PageSectionLink,
  Section,
  Template,
} from "../types";

const api = axios.create({ baseURL: "/api" });

/* ── Cases ──────────────────────────────────────────────────────────── */

export const getCases = () => api.get<Case[]>("/cases").then((r) => r.data);

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

export const getChecklists = (caseId: string) =>
  api.get<Checklist[]>(`/cases/${caseId}/checklists`).then((r) => r.data);

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

/* ── Export ──────────────────────────────────────────────────────────── */

export const exportPdf = (caseId: string) =>
  `/api/cases/${caseId}/export/pdf`;

export const exportReport = (caseId: string) =>
  `/api/cases/${caseId}/export/report`;

export const exportQCReport = (caseId: string) =>
  `/api/cases/${caseId}/export/qc-report`;

/* ── Extraction / OCR ──────────────────────────────────────────────── */

export const getExtractionStatus = () =>
  api.get<{ configured: boolean }>("/extraction/status").then((r) => r.data);

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

/* ── Audit ──────────────────────────────────────────────────────────── */

export const getAuditLog = (caseId: string) =>
  api.get<AuditEntry[]>(`/cases/${caseId}/audit`).then((r) => r.data);
