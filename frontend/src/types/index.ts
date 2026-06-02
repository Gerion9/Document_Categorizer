/* ── Domain types mirroring the backend schemas ── */

export interface Case {
  id: string;
  name: string;
  description: string;
  created_by?: number | null;
  created_by_name?: string;
  created_at: string;
  updated_at: string;
  page_count: number;
  classified_count: number;
  checklist_count: number;
  generated_form_count: number;
  form_filling_source_document_ids?: string[] | null;
  qc_checklist_source_document_ids?: string[] | null;
}

export interface CaseManagerInfo {
  id: number;
  name: string;
}

export interface TeamInfo {
  uuid: string;
  name: string;
}

export interface SupervisorCase {
  case_id: string;
  case_uuid: string;
  name: string;
  description: string;
  case_manager: CaseManagerInfo;
  team: TeamInfo;
  created_at: string;
  updated_at: string;
}

export interface TeamSummary {
  uuid: string;
  name: string;
  members_count: number;
}

export interface TeamMember {
  uuid_team_user: string;
  id: number;
  name: string;
  email: string;
  is_primary: boolean;
}

export interface TeamDetail {
  team_uuid: string;
  team_name: string;
  supervisor: {
    id: number;
    name: string;
  };
  members: TeamMember[];
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

export type IndexStatus = "pending" | "processing" | "done" | "error" | "skipped";

export interface Page {
  id: string;
  case_id: string;
  source_document_id: string | null;
  original_filename: string;
  original_page_number: number;
  thumbnail_path: string;
  file_path: string;
  file_url: string;
  thumbnail_url: string;
  document_type_id: string | null;
  section_id: string | null;
  subindex: string | null;
  order_in_section: number | null;
  status: "unclassified" | "classified" | "extra";
  metadata_json: Record<string, unknown>;
  ocr_text: string | null;
  extraction_status: "pending" | "processing" | "done" | "error";
  extraction_method: string | null;
  index_status: IndexStatus;
  index_method: string | null;
  indexed_at: string | null;
  indexed_vector_count: number;
  pinecone_document_id: string | null;
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
  index_status: string;
  index_method: string | null;
  indexed_vector_count: number;
  pinecone_document_id: string | null;
}

export interface ExtractionStatus {
  configured: boolean;
  gemini_configured: boolean;
  pinecone_configured: boolean;
  indexing_configured: boolean;
}

export interface RagMatch {
  id: string;
  score: number;
  metadata: Record<string, unknown>;
}

export interface RagQueryResponse {
  question: string;
  total_matches: number;
  matches: RagMatch[];
}

export interface AutopilotJob {
  id: string;
  checklist_id: string;
  case_id: string | null;
  status: "queued" | "running" | "completed" | "failed";
  phase: string;
  ocr_total_pages: number;
  ocr_processed_pages: number;
  ocr_error_pages: number;
  index_total_chunks: number;
  index_processed_chunks: number;
  index_error_chunks: number;
  evidence_total_questions: number;
  evidence_processed_questions: number;
  total_questions: number;
  processed_questions: number;
  verified: number;
  skipped: number;
  errors: number;
  phase_progress_pct: number;
  overall_progress_pct: number;
  progress_pct: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface FormFillingField {
  id: string;
  job_id: string;
  field_name: string;
  field_label: string;
  field_type: string;
  questionnaire_item_id: string | null;
  questionnaire_field_id: string | null;
  questionnaire_option_value: string | null;
  page_number: number | null;
  responsible_party: string;
  extracted_value: string;
  confidence: string | null;
  evidence_source: string;
  manually_corrected: boolean;
  section: string;
  form_text: string;
  instruction: string | null;
  condition: string | null;
  optional: boolean;
  requires_manual_confirmation: boolean;
  questionnaire_options: FormFillingFieldOption[];
  created_at: string;
  updated_at: string;
}

export interface FormFillingFieldOption {
  value: string;
  label: string;
}

export interface FormFillingJobWarning {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

export interface FormFillingJob {
  id: string;
  case_id: string;
  form_type: string | null;
  status: "queued" | "running" | "completed" | "needs_review" | "failed";
  phase: string;
  progress_pct: number;
  original_pdf_path: string;
  filled_pdf_path: string;
  field_count: number;
  filled_count: number;
  client_field_count: number;
  client_filled_count: number;
  attorney_field_count: number;
  attorney_filled_count: number;
  error_message: string | null;
  warnings?: FormFillingJobWarning[];
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
  fields?: FormFillingField[];
}

export interface FormTypeInfo {
  form_type: string;
  label: string;
  description: string;
}

export interface QuestionnaireOption {
  value: string;
  label: string;
}

export type QuestionnaireOptionInput = QuestionnaireOption | string;

export interface QuestionnaireField {
  id: string;
  label: string;
  type: string;
  default_value?: unknown;
  force_default?: boolean;
  allow_literal_values?: string[];
  optional?: boolean;
  instruction?: string;
  condition?: string;
  format?: string;
  prefix?: string;
  repeatable?: boolean;
  options?: QuestionnaireOptionInput[];
}

export interface QuestionnaireItem {
  id: string;
  code: string;
  section: string;
  responsible_party: string;
  type: string;
  form_text: string;
  default_value?: unknown;
  force_default?: boolean;
  instruction?: string;
  condition?: string;
  optional?: boolean;
  format?: string;
  prefix?: string;
  repeatable?: boolean;
  visible_on_pages?: number[];
  visible_slots?: Array<string | number>;
  allow_overflow_rows?: boolean;
  also_validate_with?: string[];
  exclude_from_form_mapping?: boolean;
  options?: QuestionnaireOptionInput[];
  fields?: QuestionnaireField[];
  details_fields?: QuestionnaireField[];
}

export interface QuestionnaireExcludedSection {
  name: string;
  reason: string;
}

export interface QuestionnairePage {
  page: number;
  items: QuestionnaireItem[];
  excluded_sections: QuestionnaireExcludedSection[];
}

export type QuestionnaireAnswerMap = Record<string, unknown>;

export type FieldOrigin = "manual" | "autofill";
export type FieldOriginsMap = Record<string, Record<string, FieldOrigin>>;

export interface QuestionnaireAnswersBundle {
  answers: QuestionnaireAnswerMap;
  field_origins: FieldOriginsMap;
}

export interface FieldVerification {
  status: "approved" | "needs_review" | "rejected";
  reason: string;
  evidence?: string;
  model?: string;
  verified_at?: string | null;
  fields?: Record<string, FieldVerification>;
  slots?: Record<string, Record<string, FieldVerification>>;
}

export type VerificationMap = Record<string, FieldVerification>;

export interface SaveQuestionnaireAnswerPayload {
  question_id: string;
  value: unknown;
  source: string;
  form_type?: string | null;
  field_origins?: Record<string, FieldOrigin>;
}

export interface QuestionnaireAutofillResponse {
  answers: QuestionnaireAnswerMap;
  total_targets: number;
  suggested_count: number;
  confidence_map: Record<string, unknown>;
  skipped_low_confidence: number;
  form_answers: Record<string, QuestionnaireAnswerMap>;
  form_confidence_map: Record<string, Record<string, unknown>>;
  forced_answers?: QuestionnaireAnswerMap;
  forced_form_answers?: Record<string, QuestionnaireAnswerMap>;
  verification_map?: VerificationMap;
  form_verification_map?: Record<string, VerificationMap>;
  extraction_error_count?: number;
  extraction_error_breakdown?: Record<string, number>;
}

export type AutofillJobStatusValue =
  | "queued"
  | "running"
  | "ocr_preparing"
  | "completed"
  | "failed"
  | "cancelled";

export interface AutofillJobStatus {
  id: string;
  case_id: string;
  kind: "shared" | "attorney";
  status: AutofillJobStatusValue;
  progress_pct: number;
  progress_message: string;
  ocr_total_pages: number;
  ocr_processed_pages: number;
  error?: string | null;
  result?: QuestionnaireAutofillResponse | null;
  created_at: number;
  started_at?: number | null;
  finished_at?: number | null;
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
  answer: "unanswered" | "yes" | "no" | "na" | "insufficient";
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
