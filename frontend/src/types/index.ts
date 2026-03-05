/* ── Domain types mirroring the backend schemas ── */

export interface Case {
  id: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
  page_count: number;
  classified_count: number;
  checklist_count: number;
}

export interface Section {
  id: string;
  document_type_id: string;
  parent_section_id: string | null;
  name: string;
  code: string;
  path_code: string;
  depth: number;
  order: number;
  is_required: boolean;
  page_count: number;
  children: Section[];
}

export interface DocumentType {
  id: string;
  case_id: string;
  name: string;
  code: string;
  order: number;
  has_tables: boolean;
  created_at: string;
  sections: Section[];
}

export interface PageSectionLink {
  id: string;
  page_id: string;
  section_id: string;
  is_primary: boolean;
  order_in_section: number;
  created_at: string;
  section_path_code: string;
  section_name: string;
  document_type_code: string;
  document_type_name: string;
}

export interface Page {
  id: string;
  case_id: string;
  original_filename: string;
  original_page_number: number;
  thumbnail_path: string;
  file_path: string;
  document_type_id: string | null;
  section_id: string | null;
  subindex: string | null;
  order_in_section: number | null;
  status: "unclassified" | "classified" | "extra";
  metadata_json: Record<string, unknown>;
  ocr_text: string | null;
  extraction_status: "pending" | "processing" | "done" | "error";
  extraction_method: string | null;
  created_at: string;
  updated_at: string;
  section_links: PageSectionLink[];
  link_count: number;
}

export interface ExtractionResult {
  page_id: string;
  extraction_status: string;
  extraction_method: string | null;
  ocr_text: string | null;
}

export interface SectionTarget {
  id: string;
  section_id: string;
  section_path_code: string;
  section_name: string;
}

export interface EvidenceLink {
  id: string;
  checklist_item_id: string;
  page_id: string;
  notes: string;
  created_at: string;
  page: Page | null;
}

export interface ChecklistItem {
  id: string;
  checklist_id: string;
  description: string;
  status: "pending" | "complete" | "incomplete" | "na";
  order: number;
  notes: string;
  evidence_links: EvidenceLink[];
  target_sections: SectionTarget[];
}

export interface Checklist {
  id: string;
  case_id: string;
  name: string;
  created_at: string;
  items: ChecklistItem[];
  completion_pct: number;
}

export interface AuditEntry {
  id: string;
  case_id: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  details: Record<string, unknown>;
  user: string;
  created_at: string;
}

/* ── QC Checklist (complex hierarchical) ── */

export interface QCQuestionEvidence {
  id: string;
  question_id: string;
  page_id: string;
  notes: string;
  created_at: string;
}

export interface QCQuestion {
  id: string;
  part_id: string;
  code: string;
  description: string;
  where_to_verify: string;
  order: number;
  answer: "unanswered" | "yes" | "no" | "na";
  correction: string;
  notes: string;
  answered_by: string | null;
  answered_at: string | null;
  ai_answer: string | null;
  ai_notes: string;
  ai_confidence: string | null;
  ai_verified_at: string | null;
  target_section_ids: string[];
  evidence: QCQuestionEvidence[];
}

export interface QCPart {
  id: string;
  checklist_id: string;
  parent_part_id: string | null;
  name: string;
  code: string;
  order: number;
  depth: number;
  questions: QCQuestion[];
  children: QCPart[];
}

export interface QCChecklist {
  id: string;
  name: string;
  description: string;
  case_id: string | null;
  is_template: boolean;
  source_template_id: string | null;
  created_at: string;
  parts: QCPart[];
  total_questions: number;
  answered_questions: number;
}

/* ── QC Link Presets ── */

export interface QCLinkPresetMapping {
  id: string;
  question_code: string;
  section_path_codes: string[];
}

export interface QCLinkPreset {
  id: string;
  name: string;
  qc_template_id: string | null;
  doc_template_id: string | null;
  created_at: string;
  mappings: QCLinkPresetMapping[];
  mapping_count: number;
}

/* ── Template Library types ── */

export interface TemplateNode {
  id: string;
  template_id: string;
  parent_node_id: string | null;
  name: string;
  code: string;
  node_type: "doc_type" | "section";
  has_tables: boolean;
  is_required: boolean;
  depth: number;
  order: number;
  children: TemplateNode[];
  target_item_ids: string[];
}

export interface TemplateChecklistItem {
  id: string;
  description: string;
  order: number;
  target_node_ids: string[];
}

export interface TemplateChecklist {
  id: string;
  name: string;
  items: TemplateChecklistItem[];
}

export interface Template {
  id: string;
  name: string;
  description: string;
  created_at: string;
  nodes: TemplateNode[];
  checklists: TemplateChecklist[];
}
