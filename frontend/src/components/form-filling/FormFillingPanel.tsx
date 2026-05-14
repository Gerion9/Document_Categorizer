import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type MouseEvent,
  type ReactNode,
  type SetStateAction,
} from "react";
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  FileDown,
  FileText,
  Loader2,
  Minus,
  Plus,
  RefreshCw,
  X,
} from "lucide-react";
import toast from "react-hot-toast";
import { GlassSurface } from "../glass/GlassSurface";
import CaseDocumentScopePicker from "../document-scopes/CaseDocumentScopePicker";
import { AnimatedAIBot } from "../ui/AnimatedAIBot";
import { EmptyState } from "./FormFillingPanelEmptyState";
import type {
  Case,
  FieldVerification,
  FormFillingJob,
  FormTypeInfo,
  Page,
  QuestionnaireAnswerMap,
  QuestionnaireField,
  QuestionnaireItem,
  QuestionnaireOption,
  QuestionnaireOptionInput,
  QuestionnairePage,
  SaveQuestionnaireAnswerPayload,
  VerificationMap,
} from "../../types";
import {
  autofillAttorneyAnswers,
  autofillSharedQuestionnaireAnswers,
  deleteFormFillingJob,
  downloadFilledPdf,
  generateFormFromAnswers,
  getAvailableFormTypes,
  getFilledPdfBlobUrl,
  getFormAttorneyQuestions,
  getFormClientQuestions,
  getFormFillingJobs,
  getFormFillingJobStatus,
  getQuestionnaireAnswers,
  getQuestionnaireVerifications,
  getSharedQuestions,
  regenerateFilledPdf,
  saveQuestionnaireAnswers,
  updateCase,
} from "../../api/client";
import {
  buildScopeUpdatePayload,
  listSelectableCaseDocuments,
  resolveSelectedSourceDocumentIds,
} from "../../utils/caseDocumentScopes";
import { getApiErrorMessage } from "../../utils/apiErrors";
import {
  LONG_DATE_PLACEHOLDER,
  MONTH_ABBR_EN,
  formatLongDate,
  formatLongDateTime,
  parseFlexibleDate,
} from "../../utils/dateFormat";
import {
  formatPendingFieldLabel,
  getClientConfirmationBlockMessage,
  getClientPendingFieldsLead,
  getClientRegenerationBlockMessage,
  getPreviewStepBlockedMessage,
  type MissingRequiredField,
} from "./formFillingClientMessages";
import {
  formatJobTimestamp,
  getJobDisplayTimestamp,
  getJobPhaseLabel,
  getJobSortTime,
  getJobTimestampLabel,
} from "./formFillingJobUtils";

const HIDDEN_FORM_TYPES = new Set(["i-914a"]);

function isHiddenFormType(formType?: string | null): boolean {
  return HIDDEN_FORM_TYPES.has((formType ?? "").toLowerCase());
}

interface Props {
  caseId: string;
  caseData: Case | null;
  pages: Page[];
  onCaseUpdated?: (updatedCase: Case) => void;
  onPagesUpdated?: () => void;
}

type WizardStep =
  | "client_questions"
  | "attorney_questions"
  | "preview";
type AnswerSetter = Dispatch<SetStateAction<QuestionnaireAnswerMap>>;
type RepeatableRow = Record<string, string>;
type ClientQuestionPlan = {
  pages: QuestionnairePage[];
  clearedAnswers: Array<Pick<SaveQuestionnaireAnswerPayload, "question_id" | "value">>;
};
type QuestionnaireSaveScope = "client" | "all";
type QuestionnaireSignatures = {
  shared: string;
  client: string;
  attorney: string;
};

function mergeVerificationMaps(
  verificationMap?: VerificationMap,
  formVerificationMap?: Record<string, VerificationMap>
): VerificationMap {
  const next: VerificationMap = { ...(verificationMap ?? {}) };
  for (const formMap of Object.values(formVerificationMap ?? {})) {
    Object.assign(next, formMap);
  }
  return next;
}

function getVerificationEntry(
  verificationMap: VerificationMap,
  ...keys: Array<string | undefined>
): FieldVerification | undefined {
  for (const key of keys) {
    if (key && verificationMap[key]) {
      return verificationMap[key];
    }
  }
  return undefined;
}

function normalizeDefaultComparisonValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "boolean") {
    return value ? "yes" : "no";
  }

  const normalized = toText(value).trim().toLowerCase();
  if (["true", "yes", "y", "1", "checked", "on"].includes(normalized)) {
    return "yes";
  }
  if (["false", "no", "n", "0", "unchecked", "off"].includes(normalized)) {
    return "no";
  }
  const compact = normalized.replace(/[^a-z0-9]+/g, " ").trim();
  if (
    [
      "ee uu",
      "e e u u",
      "estados unidos",
      "u s",
      "us",
      "usa",
      "united states",
      "united states of america",
    ].includes(compact)
  ) {
    return "united states";
  }
  return normalized;
}

function answerMatchesDefaultValue(value: unknown, defaultValue: unknown): boolean {
  if (defaultValue === undefined || defaultValue === null) {
    return false;
  }
  return normalizeDefaultComparisonValue(value) === normalizeDefaultComparisonValue(defaultValue);
}

function isPreFilledDefaultValue(
  value: unknown,
  defaultValue: unknown,
  forceDefault = false
): boolean {
  if (defaultValue === undefined || defaultValue === null) {
    return false;
  }
  if (forceDefault) {
    return true;
  }
  if (!hasMeaningfulAnswerValue(defaultValue)) {
    return false;
  }
  return answerMatchesDefaultValue(value, defaultValue);
}

function shouldShowOptionalBadge(
  optional: boolean | undefined,
  value: unknown,
  defaultValue: unknown,
  forceDefault = false
): boolean {
  return Boolean(optional && !isPreFilledDefaultValue(value, defaultValue, forceDefault));
}

function getDefaultAwareVerificationEntry(
  verificationMap: VerificationMap,
  value: unknown,
  defaultValue: unknown,
  ...keys: Array<string | undefined>
): FieldVerification | undefined {
  const verification = getVerificationEntry(verificationMap, ...keys);
  if (verification && answerMatchesDefaultValue(value, defaultValue)) {
    return undefined;
  }
  return verification;
}

function getRepeatableVerificationKeys(
  item: QuestionnaireItem,
  rowIndex: number,
  fieldId: string
): string[] {
  const canonicalKey = `${item.id}.${fieldId}`;
  if ((item.visible_slots?.length ?? 0) > rowIndex) {
    return [`${item.id}[${rowIndex}].${fieldId}`, canonicalKey];
  }
  return [canonicalKey];
}

function VerificationBadge({ verification }: { verification: FieldVerification }) {
  const [hovered, setHovered] = useState(false);
  const [pinned, setPinned] = useState(false);
  const containerRef = useRef<HTMLSpanElement | null>(null);

  const config = {
    approved: {
      label: "Approved",
      className: "border-emerald-200 bg-emerald-50 text-emerald-700",
      icon: CheckCircle2,
    },
    needs_review: {
      label: "Needs review",
      className: "border-amber-200 bg-amber-50 text-amber-700",
      icon: AlertCircle,
    },
    rejected: {
      label: "Rejected",
      className: "border-red-200 bg-red-50 text-red-700",
      icon: X,
    },
  } as const;

  const current = config[verification.status];
  const Icon = current.icon;

  const reasonText = (verification.reason || "").trim();
  const evidenceText = (verification.evidence || "").trim();
  const modelText = (verification.model || "").trim();
  const verifiedAtLabel = verification.verified_at
    ? formatLongDateTime(verification.verified_at)
    : "";

  const hasDetails = reasonText.length > 0 || evidenceText.length > 0;
  const isOpen = pinned || hovered;
  const ariaLabel = reasonText
    ? `${current.label}: ${reasonText}`
    : current.label;

  useEffect(() => {
    if (!pinned) return;
    const handleClickOutside = (event: globalThis.MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setPinned(false);
        setHovered(false);
      }
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setPinned(false);
        setHovered(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [pinned]);

  return (
    <span
      ref={containerRef}
      className="relative inline-flex"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <button
        type="button"
        className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${current.className} hover:brightness-95 focus:outline-none focus:ring-2 focus:ring-slate-400/40`}
        aria-label={ariaLabel}
        aria-expanded={isOpen}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          if (!hasDetails) return;
          setPinned((prev) => !prev);
        }}
        onFocus={() => setHovered(true)}
        onBlur={() => setHovered(false)}
      >
        <Icon aria-hidden="true" className="h-3.5 w-3.5" />
        <span>{current.label}</span>
      </button>
      {isOpen && hasDetails && (
        <div
          role="tooltip"
          className={`absolute left-1/2 top-full z-50 mt-2 w-80 -translate-x-1/2 rounded-lg border border-slate-200 bg-white p-3 text-left text-[11px] leading-relaxed text-slate-700 shadow-xl ${pinned ? "" : "pointer-events-none"}`}
        >
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-1 text-slate-500">
              <Icon aria-hidden="true" className={`h-3.5 w-3.5 ${current.className.split(" ").find((c) => c.startsWith("text-")) ?? ""}`} />
              <span className="font-semibold uppercase tracking-wide">{current.label}</span>
            </div>
            {pinned && (
              <button
                type="button"
                aria-label="Close"
                className="-mt-1 -mr-1 rounded p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 focus:outline-none focus:ring-2 focus:ring-slate-400/40"
                onClick={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  setPinned(false);
                  setHovered(false);
                }}
              >
                <X aria-hidden="true" className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
          {reasonText && (
            <div className="mt-2">
              <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                Reason
              </div>
              <div className="mt-0.5 whitespace-pre-wrap break-words text-slate-700">
                {reasonText}
              </div>
            </div>
          )}
          {evidenceText && (
            <div className="mt-2">
              <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                Evidence from documents
              </div>
              <div className="mt-0.5 max-h-40 overflow-y-auto whitespace-pre-wrap break-words rounded border border-slate-100 bg-slate-50 p-1.5 font-mono text-[10px] text-slate-600">
                {evidenceText}
              </div>
            </div>
          )}
          {(modelText || verifiedAtLabel) && (
            <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] text-slate-400">
              {modelText && <span>Verified by {modelText}</span>}
              {verifiedAtLabel && <span>{verifiedAtLabel}</span>}
            </div>
          )}
          {!pinned && (
            <div className="mt-2 text-[9px] uppercase tracking-wide text-slate-300">
              Click the badge to pin
            </div>
          )}
        </div>
      )}
    </span>
  );
}

const AUTOSAVE_DEBOUNCE_MS = 700;
const SHARED_PHYSICAL_ADDRESS_ID = "shared.current_physical_address";
const SHARED_SAFE_MAILING_ADDRESS_ID = "shared.safe_mailing_address";
const ADDRESS_COMPARE_FIELD_IDS = [
  "street_number_name",
  "unit_type",
  "unit_number",
  "city",
  "state",
  "zip_code",
] as const;
const ADDRESS_REQUIRED_COMPARE_FIELD_IDS = [
  "street_number_name",
  "city",
  "state",
  "zip_code",
] as const;
const US_STATE_OPTIONS: QuestionnaireOption[] = [
  { value: "AL", label: "Alabama" },
  { value: "AK", label: "Alaska" },
  { value: "AZ", label: "Arizona" },
  { value: "AR", label: "Arkansas" },
  { value: "CA", label: "California" },
  { value: "CO", label: "Colorado" },
  { value: "CT", label: "Connecticut" },
  { value: "DE", label: "Delaware" },
  { value: "DC", label: "District of Columbia" },
  { value: "FL", label: "Florida" },
  { value: "GA", label: "Georgia" },
  { value: "HI", label: "Hawaii" },
  { value: "ID", label: "Idaho" },
  { value: "IL", label: "Illinois" },
  { value: "IN", label: "Indiana" },
  { value: "IA", label: "Iowa" },
  { value: "KS", label: "Kansas" },
  { value: "KY", label: "Kentucky" },
  { value: "LA", label: "Louisiana" },
  { value: "ME", label: "Maine" },
  { value: "MD", label: "Maryland" },
  { value: "MA", label: "Massachusetts" },
  { value: "MI", label: "Michigan" },
  { value: "MN", label: "Minnesota" },
  { value: "MS", label: "Mississippi" },
  { value: "MO", label: "Missouri" },
  { value: "MT", label: "Montana" },
  { value: "NE", label: "Nebraska" },
  { value: "NV", label: "Nevada" },
  { value: "NH", label: "New Hampshire" },
  { value: "NJ", label: "New Jersey" },
  { value: "NM", label: "New Mexico" },
  { value: "NY", label: "New York" },
  { value: "NC", label: "North Carolina" },
  { value: "ND", label: "North Dakota" },
  { value: "OH", label: "Ohio" },
  { value: "OK", label: "Oklahoma" },
  { value: "OR", label: "Oregon" },
  { value: "PA", label: "Pennsylvania" },
  { value: "RI", label: "Rhode Island" },
  { value: "SC", label: "South Carolina" },
  { value: "SD", label: "South Dakota" },
  { value: "TN", label: "Tennessee" },
  { value: "TX", label: "Texas" },
  { value: "UT", label: "Utah" },
  { value: "VT", label: "Vermont" },
  { value: "VA", label: "Virginia" },
  { value: "WA", label: "Washington" },
  { value: "WV", label: "West Virginia" },
  { value: "WI", label: "Wisconsin" },
  { value: "WY", label: "Wyoming" },
  { value: "AS", label: "American Samoa" },
  { value: "GU", label: "Guam" },
  { value: "MP", label: "Northern Mariana Islands" },
  { value: "PR", label: "Puerto Rico" },
  { value: "VI", label: "U.S. Virgin Islands" },
];
const US_STATE_CODE_MAP = new Map(
  US_STATE_OPTIONS.map((option) => [option.value.toLowerCase(), option.value])
);
const US_STATE_NAME_MAP = new Map(
  US_STATE_OPTIONS.map((option) => [option.label.toLowerCase(), option.value])
);
const COUNTRY_DISPLAY_BY_KEY: Record<string, string> = {
  "united states": "United States",
  mexico: "Mexico",
  guatemala: "Guatemala",
  honduras: "Honduras",
  "el salvador": "El Salvador",
  nicaragua: "Nicaragua",
  "costa rica": "Costa Rica",
  panama: "Panama",
  colombia: "Colombia",
  venezuela: "Venezuela",
  ecuador: "Ecuador",
  peru: "Peru",
  bolivia: "Bolivia",
  chile: "Chile",
  argentina: "Argentina",
  paraguay: "Paraguay",
  uruguay: "Uruguay",
  brazil: "Brazil",
  canada: "Canada",
  spain: "Spain",
  germany: "Germany",
  italy: "Italy",
  france: "France",
  "united kingdom": "United Kingdom",
  "dominican republic": "Dominican Republic",
  netherlands: "Netherlands",
  switzerland: "Switzerland",
  turkey: "Turkey",
  greece: "Greece",
  japan: "Japan",
  china: "China",
};
const COUNTRY_ALIAS_TO_KEY = new Map<string, string>([
  ...Object.keys(COUNTRY_DISPLAY_BY_KEY).map((key) => [key, key] as const),
  ["american", "united states"],
  ["americana", "united states"],
  ["estadounidense", "united states"],
  ["ee uu", "united states"],
  ["eeuu", "united states"],
  ["estados unidos", "united states"],
  ["usa", "united states"],
  ["u s a", "united states"],
  ["u s", "united states"],
  ["mexican", "mexico"],
  ["mexicano", "mexico"],
  ["mexicana", "mexico"],
  ["guatemalan", "guatemala"],
  ["guatemalteco", "guatemala"],
  ["guatemalteca", "guatemala"],
  ["honduran", "honduras"],
  ["hondureno", "honduras"],
  ["hondurena", "honduras"],
  ["salvadoran", "el salvador"],
  ["salvadoreno", "el salvador"],
  ["salvadorena", "el salvador"],
  ["nicaraguan", "nicaragua"],
  ["nicaraguense", "nicaragua"],
  ["costa rican", "costa rica"],
  ["costarricense", "costa rica"],
  ["panamanian", "panama"],
  ["panameno", "panama"],
  ["panamena", "panama"],
  ["colombian", "colombia"],
  ["colombiano", "colombia"],
  ["colombiana", "colombia"],
  ["venezuelan", "venezuela"],
  ["venezolano", "venezuela"],
  ["venezolana", "venezuela"],
  ["ecuadorian", "ecuador"],
  ["ecuatoriano", "ecuador"],
  ["ecuatoriana", "ecuador"],
  ["peruvian", "peru"],
  ["peruano", "peru"],
  ["peruana", "peru"],
  ["bolivian", "bolivia"],
  ["boliviano", "bolivia"],
  ["boliviana", "bolivia"],
  ["chilean", "chile"],
  ["chileno", "chile"],
  ["chilena", "chile"],
  ["argentine", "argentina"],
  ["argentinian", "argentina"],
  ["argentino", "argentina"],
  ["argentina", "argentina"],
  ["paraguayan", "paraguay"],
  ["paraguayo", "paraguay"],
  ["paraguaya", "paraguay"],
  ["uruguayan", "uruguay"],
  ["uruguayo", "uruguay"],
  ["uruguaya", "uruguay"],
  ["brazilian", "brazil"],
  ["brasileno", "brazil"],
  ["brasilena", "brazil"],
  ["canadian", "canada"],
  ["canadiense", "canada"],
  ["espana", "spain"],
  ["espanol", "spain"],
  ["espanola", "spain"],
  ["alemania", "germany"],
  ["aleman", "germany"],
  ["alemana", "germany"],
  ["italia", "italy"],
  ["italiano", "italy"],
  ["italiana", "italy"],
  ["francia", "france"],
  ["frances", "france"],
  ["british", "united kingdom"],
  ["uk", "united kingdom"],
  ["u k", "united kingdom"],
  ["reino unido", "united kingdom"],
  ["republica dominicana", "dominican republic"],
  ["dominican", "dominican republic"],
  ["dominicano", "dominican republic"],
  ["dominicana", "dominican republic"],
  ["paises bajos", "netherlands"],
  ["dutch", "netherlands"],
  ["holandes", "netherlands"],
  ["holandesa", "netherlands"],
  ["suiza", "switzerland"],
  ["swiss", "switzerland"],
  ["suizo", "switzerland"],
  ["turquia", "turkey"],
  ["turkish", "turkey"],
  ["turco", "turkey"],
  ["grecia", "greece"],
  ["greek", "greece"],
  ["griego", "greece"],
  ["japon", "japan"],
  ["japanese", "japan"],
  ["japones", "japan"],
  ["japonesa", "japan"],
  ["chinese", "china"],
  ["chino", "china"],
]);
const IMMIGRATION_STATUS_CODE_RE = /\b[A-Z]{1,3}\s*[-/]?\s*\d[A-Z]?\b/i;
const IMMIGRATION_STATUS_KEYWORDS = [
  "status",
  "visa",
  "visitor",
  "tourist",
  "student",
  "exchange",
  "worker",
  "employment authorization",
  "ead",
  "overstay",
  "parole",
  "paroled",
  "asylum",
  "asylee",
  "refugee",
  "tps",
  "temporary protected status",
  "daca",
  "deferred action",
  "nonimmigrant",
  "immigrant",
  "permanent resident",
  "lawful permanent resident",
  "lpr",
  "adjustment",
  "pending asylum",
  "pending t",
  "pending u",
] as const;
const NO_LEGAL_STATUS_DISPLAY_BY_ALIAS: Record<string, string> = {
  "sin papeles": "No Legal Status",
  indocumentado: "No Legal Status",
  indocumentada: "No Legal Status",
  undocumented: "No Legal Status",
  "out of status": "No Legal Status",
  "no legal status": "No Legal Status",
  "sin estatus": "No Legal Status",
  "sin estatus legal": "No Legal Status",
  "sin estatus migratorio": "No Legal Status",
  "sin estado migratorio": "No Legal Status",
  "sin estado legal": "No Legal Status",
  "no tengo estatus": "No Legal Status",
  "ningun estatus": "No Legal Status",
  ninguno: "No Legal Status",
};

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function toText(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return "";
}

function hasText(value: string): boolean {
  return value.trim().length > 0;
}

function hasMeaningfulAnswerValue(value: unknown): boolean {
  if (typeof value === "string") {
    return hasText(value);
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return true;
  }
  if (Array.isArray(value)) {
    return value.some((entry) => hasMeaningfulAnswerValue(entry));
  }
  if (isPlainObject(value)) {
    return Object.values(value).some((entry) => hasMeaningfulAnswerValue(entry));
  }
  return false;
}

function cloneAnswerValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((entry) => cloneAnswerValue(entry));
  }
  if (isPlainObject(value)) {
    return Object.fromEntries(
      Object.entries(value).map(([key, entry]) => [key, cloneAnswerValue(entry)])
    );
  }
  return value;
}

function looksLikeStateSelect(id: string, ariaLabel: string): boolean {
  const normalizedId = id.toLowerCase();
  const normalizedLabel = ariaLabel.toLowerCase();
  return /(?:^|[_-])state(?:$|[_-])/.test(normalizedId) || /\bstate\b/.test(normalizedLabel);
}

function normalizeStateValue(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }

  const normalizedCode = US_STATE_CODE_MAP.get(trimmed.toLowerCase());
  if (normalizedCode) {
    return normalizedCode;
  }

  const normalizedName = US_STATE_NAME_MAP.get(trimmed.toLowerCase());
  return normalizedName ?? trimmed;
}

function resolveImplicitSelectOptions(
  type: string,
  id: string,
  ariaLabel: string
): QuestionnaireOption[] {
  if (type !== "select") {
    return [];
  }

  if (looksLikeStateSelect(id, ariaLabel)) {
    return US_STATE_OPTIONS;
  }

  return [];
}

function resolveSelectValue(
  rawValue: string,
  options: QuestionnaireOption[],
  id: string,
  ariaLabel: string
): string {
  const trimmed = rawValue.trim();
  if (!trimmed) {
    return "";
  }

  const normalizedStateValue = looksLikeStateSelect(id, ariaLabel)
    ? normalizeStateValue(trimmed)
    : trimmed;

  const byValue = options.find(
    (option) => option.value.toLowerCase() === normalizedStateValue.toLowerCase()
  );
  if (byValue) {
    return byValue.value;
  }

  const byLabel = options.find(
    (option) => option.label.toLowerCase() === normalizedStateValue.toLowerCase()
  );
  if (byLabel) {
    return byLabel.value;
  }

  return options.length > 0 ? "" : normalizedStateValue;
}

function resolveLiteralValue(rawValue: string, allowLiteralValues: string[]): string {
  const trimmed = rawValue.trim();
  if (!trimmed) {
    return "";
  }

  const match = allowLiteralValues.find(
    (literalValue) => literalValue.toLowerCase() === trimmed.toLowerCase()
  );
  return match ?? "";
}

function looksLikeQuestionAnswerDump(value: string): boolean {
  const normalized = value.toLowerCase();
  const questionCount = (normalized.match(/\b(?:pregunta|question)\s*:/g) ?? []).length;
  const answerCount = (normalized.match(/\b(?:respuesta|answer)\s*:/g) ?? []).length;
  return questionCount >= 2 || answerCount >= 2;
}

function normalizeOption(option: QuestionnaireOptionInput): QuestionnaireOption {
  return typeof option === "string"
    ? { value: option, label: option }
    : { value: option.value, label: option.label };
}

function isChoiceGroupType(type: string, options?: QuestionnaireOptionInput[]): boolean {
  const normalizedType = type.toLowerCase();
  return (
    normalizedType === "yes_no" ||
    (["single_choice", "choice", "radio", "button"].includes(normalizedType) &&
      (options ?? []).length > 0)
  );
}

function createEmptyGroupValue(fields: QuestionnaireField[]): RepeatableRow {
  return Object.fromEntries(fields.map((field) => [field.id, ""]));
}

function hasMeaningfulRepeatableRow(value: unknown): value is Record<string, unknown> {
  return isPlainObject(value) && Object.values(value).some((entry) => hasText(toText(entry)));
}

function normalizeGroupValue(
  value: unknown,
  fields: QuestionnaireField[]
): RepeatableRow {
  const fallback = createEmptyGroupValue(fields);
  if (!isPlainObject(value)) {
    return fallback;
  }

  const next = { ...fallback };
  for (const field of fields) {
    next[field.id] = toText(value[field.id]);
  }
  return next;
}

function normalizeRepeatableGroupValue(
  value: unknown,
  fields: QuestionnaireField[]
): RepeatableRow[] {
  if (Array.isArray(value)) {
    return value.map((entry) => normalizeGroupValue(entry, fields));
  }

  // Be forgiving with legacy shapes so saved repeatable answers still rehydrate.
  if (hasMeaningfulRepeatableRow(value)) {
    return [normalizeGroupValue(value, fields)];
  }

  if (fields.length === 1) {
    const scalar = toText(value);
    if (hasText(scalar)) {
      return [{ [fields[0].id]: scalar }];
    }
  }

  return [];
}

function isRowEmpty(row: RepeatableRow): boolean {
  return Object.values(row).every((value) => !hasText(value));
}

function trimTrailingEmptyRows(rows: RepeatableRow[]): RepeatableRow[] {
  const next = [...rows];
  while (next.length > 0 && isRowEmpty(next[next.length - 1])) {
    next.pop();
  }
  return next;
}

function trimTrailingEmptyScalars(values: string[]): string[] {
  const next = [...values];
  while (next.length > 0 && !hasText(next[next.length - 1])) {
    next.pop();
  }
  return next;
}

function isRepeatableItem(item: QuestionnaireItem): boolean {
  return Boolean(item.fields?.length && (item.type === "repeatable_group" || item.repeatable));
}

function normalizeValidationText(value: string): string {
  return value
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function buildFieldValidationContext(item: QuestionnaireItem, field?: QuestionnaireField): string {
  return normalizeValidationText(
    [
      item.id,
      field?.id,
      field?.label,
      item.form_text,
      item.section,
      item.instruction,
      item.condition,
      field?.instruction,
      field?.condition,
    ]
      .filter(Boolean)
      .join(" | ")
  );
}

function looksLikeUsStateField(item: QuestionnaireItem, field?: QuestionnaireField): boolean {
  const fieldId = (field?.id ?? item.id).toLowerCase();
  const label = field?.label ?? item.form_text;
  const context = buildFieldValidationContext(item, field);
  if (context.includes("state province") || context.includes("state or province")) {
    return false;
  }
  if (
    (fieldId === "state" || fieldId.endsWith("_state") || looksLikeStateSelect(fieldId, label)) &&
    ["address", "entry", "law enforcement", "lea"].some((term) => context.includes(term))
  ) {
    return true;
  }
  return false;
}

function looksLikeCountryField(item: QuestionnaireItem, field?: QuestionnaireField): boolean {
  const fieldId = (field?.id ?? item.id).toLowerCase();
  if (fieldId === "country" || fieldId.endsWith("_country") || fieldId.includes("country")) {
    return true;
  }
  const context = buildFieldValidationContext(item, field);
  return (
    context.includes("country of citizenship") ||
    context.includes("citizenship or nationality") ||
    context.includes("country of nationality") ||
    context.includes("country of birth") ||
    context.includes("issuing country")
  );
}

function looksLikeImmigrationStatusField(item: QuestionnaireItem, field?: QuestionnaireField): boolean {
  const fieldId = (field?.id ?? item.id).toLowerCase();
  if (["current_nonimmigrant_status", "current_immigration_status", "prior_entry_status"].includes(fieldId)) {
    return true;
  }
  const context = buildFieldValidationContext(item, field);
  if (context.includes("marital status")) {
    return false;
  }
  return (
    context.includes("current nonimmigrant status") ||
    context.includes("current immigration status") ||
    context.includes("prior entry status") ||
    (context.includes("immigration status") && context.includes("current"))
  );
}

function normalizeCountryValue(value: string): string {
  const normalizedKey = COUNTRY_ALIAS_TO_KEY.get(normalizeValidationText(value));
  return normalizedKey ? COUNTRY_DISPLAY_BY_KEY[normalizedKey] ?? "" : "";
}

function normalizeImmigrationStatusValue(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }
  if (normalizeCountryValue(trimmed)) {
    return "";
  }
  const normalized = normalizeValidationText(trimmed);
  const explicitNoStatus = NO_LEGAL_STATUS_DISPLAY_BY_ALIAS[normalized];
  if (explicitNoStatus) {
    return explicitNoStatus;
  }
  if (IMMIGRATION_STATUS_CODE_RE.test(trimmed)) {
    return trimmed;
  }
  if (IMMIGRATION_STATUS_KEYWORDS.some((keyword) => normalized.includes(keyword))) {
    return trimmed;
  }
  return "";
}

function sanitizeQuestionnaireFieldValue(
  item: QuestionnaireItem,
  rawValue: unknown,
  field?: QuestionnaireField
): string {
  const trimmed = toText(rawValue).trim();
  if (!trimmed) {
    return "";
  }
  if (looksLikeUsStateField(item, field)) {
    const normalizedState = normalizeStateValue(trimmed);
    return US_STATE_CODE_MAP.has(normalizedState.toLowerCase()) ? normalizedState : "";
  }
  if (looksLikeCountryField(item, field)) {
    return normalizeCountryValue(trimmed);
  }
  if (looksLikeImmigrationStatusField(item, field)) {
    return normalizeImmigrationStatusValue(trimmed);
  }
  return trimmed;
}

function splitCompoundLatamNameParts(
  givenName: string,
  middleName: string,
  familyName: string
): { givenName: string; middleName: string } | null {
  const normalizedGivenName = toText(givenName).trim();
  const normalizedMiddleName = toText(middleName).trim();
  const normalizedFamilyName = toText(familyName).trim();
  if (!normalizedGivenName || !normalizedFamilyName || normalizedMiddleName) {
    return null;
  }

  const givenTokens = normalizedGivenName.split(/\s+/);
  const familyTokens = normalizedFamilyName.split(/\s+/);
  if (givenTokens.length !== 2 || familyTokens.length !== 2) {
    return null;
  }

  return {
    givenName: givenTokens[0] ?? "",
    middleName: givenTokens[1] ?? "",
  };
}

function normalizeCompoundLatamNameRow(row: RepeatableRow): RepeatableRow {
  const nextRow = { ...row };

  for (const key of Object.keys(nextRow)) {
    if (key !== "family_name" && !key.endsWith("_family_name")) {
      continue;
    }

    const prefix = key.slice(0, -"family_name".length);
    const givenKey = `${prefix}given_name`;
    const middleKey = `${prefix}middle_name`;
    if (!(givenKey in nextRow) || !(middleKey in nextRow)) {
      continue;
    }

    const splitName = splitCompoundLatamNameParts(
      nextRow[givenKey] ?? "",
      nextRow[middleKey] ?? "",
      nextRow[key] ?? ""
    );
    if (!splitName) {
      continue;
    }

    nextRow[givenKey] = splitName.givenName;
    nextRow[middleKey] = splitName.middleName;
  }

  return nextRow;
}

function getSanitizedGroupValue(
  item: QuestionnaireItem,
  answers: QuestionnaireAnswerMap
): RepeatableRow {
  const fields = item.fields ?? [];
  const row = normalizeGroupValue(answers[item.id], fields);
  const sanitized = createEmptyGroupValue(fields);
  for (const field of fields) {
    const canonicalKey = `${item.id}.${field.id}`;
    const rawValue = hasText(row[field.id] ?? "") ? row[field.id] : answers[canonicalKey];
    sanitized[field.id] = sanitizeQuestionnaireFieldValue(item, rawValue, field);
  }
  return normalizeCompoundLatamNameRow(sanitized);
}

function sanitizeAnswersForPages(
  pages: QuestionnairePage[],
  answers: QuestionnaireAnswerMap
): QuestionnaireAnswerMap {
  const next: QuestionnaireAnswerMap = { ...answers };

  for (const page of pages) {
    for (const item of page.items) {
      if (item.fields?.length) {
        if (isRepeatableItem(item)) {
          const fields = item.fields ?? [];
          const rows = normalizeRepeatableGroupValue(answers[item.id], fields).map((row) =>
            normalizeCompoundLatamNameRow(
              Object.fromEntries(
                fields.map((field) => [
                  field.id,
                  sanitizeQuestionnaireFieldValue(item, row[field.id], field),
                ])
              )
            )
          );
          next[item.id] = trimTrailingEmptyRows(rows);
        } else {
          next[item.id] = getSanitizedGroupValue(item, answers);
        }
      } else {
        next[item.id] = sanitizeQuestionnaireFieldValue(item, answers[item.id]);
      }

      for (const detailField of item.details_fields ?? []) {
        const detailKey = `${item.id}.${detailField.id}`;
        if (detailField.repeatable) {
          const values = Array.isArray(answers[detailKey])
            ? answers[detailKey].map((entry) =>
                sanitizeQuestionnaireFieldValue(item, entry, detailField)
              )
            : [];
          next[detailKey] = trimTrailingEmptyScalars(values);
        } else {
          next[detailKey] = sanitizeQuestionnaireFieldValue(item, answers[detailKey], detailField);
        }
      }
    }
  }

  return next;
}

function getRepeatableRowCount(
  item: QuestionnaireItem,
  answers: QuestionnaireAnswerMap
): number {
  const fixedSlotCount = item.visible_slots?.length ?? 0;
  const groupCount =
    item.fields && isRepeatableItem(item)
      ? normalizeRepeatableGroupValue(answers[item.id], item.fields).length
      : 0;

  const repeatableDetails = (item.details_fields ?? []).filter((field) => field.repeatable);
  const detailCount = repeatableDetails.reduce((maxCount, field) => {
    const key = `${item.id}.${field.id}`;
    const value = answers[key];
    return Math.max(maxCount, Array.isArray(value) ? value.length : 0);
  }, 0);

  return Math.max(fixedSlotCount, groupCount, detailCount, 1);
}

function getRepeatableRowLabel(item: QuestionnaireItem, index: number): string {
  const slotLabel = item.visible_slots?.[index];
  return slotLabel ? String(slotLabel) : `Row ${index + 1}`;
}

function isAdditionalRepeatableRow(index: number): boolean {
  return index > 0;
}

function extractRelevantAnswers(
  answers: QuestionnaireAnswerMap,
  pages: QuestionnairePage[]
): QuestionnaireAnswerMap {
  const next: QuestionnaireAnswerMap = {};

  for (const page of pages) {
    for (const item of page.items) {
      if (item.fields?.length) {
        if (isRepeatableItem(item)) {
          const rows = trimTrailingEmptyRows(
            normalizeRepeatableGroupValue(answers[item.id], item.fields)
          );
          if (rows.length > 0) {
            next[item.id] = rows;
          }
        } else {
          const row = normalizeGroupValue(answers[item.id], item.fields);
          for (const field of item.fields) {
            const canonicalKey = `${item.id}.${field.id}`;
            if (!hasText(row[field.id]) && canonicalKey in answers) {
              row[field.id] = toText(answers[canonicalKey]);
            }
          }
          if (Object.values(row).some(hasText)) {
            next[item.id] = row;
          }
        }
      } else {
        const scalar = toText(answers[item.id]);
        if (hasText(scalar)) {
          next[item.id] = scalar;
        }
      }

      for (const detailField of item.details_fields ?? []) {
        const detailKey = `${item.id}.${detailField.id}`;
        if (detailField.repeatable) {
          const values = trimTrailingEmptyScalars(
            Array.isArray(answers[detailKey])
              ? answers[detailKey].map((entry) => toText(entry))
              : []
          );
          if (values.length > 0) {
            next[detailKey] = values;
          }
        } else {
          const scalar = toText(answers[detailKey]);
          if (hasText(scalar)) {
            next[detailKey] = scalar;
          }
        }
      }
    }
  }

  return next;
}

function applyQuestionnaireDefaults(
  pages: QuestionnairePage[],
  answers: QuestionnaireAnswerMap
): QuestionnaireAnswerMap {
  const next: QuestionnaireAnswerMap = { ...answers };

  for (const page of pages) {
    for (const item of page.items) {
      if (
        item.default_value !== undefined &&
        !item.fields?.length &&
        !hasMeaningfulAnswerValue(next[item.id])
      ) {
        next[item.id] = cloneAnswerValue(item.default_value);
      }

      if (item.fields?.length && !isRepeatableItem(item)) {
        const groupValue = normalizeGroupValue(next[item.id], item.fields);
        let groupChanged = false;

        for (const field of item.fields) {
          if (
            field.default_value !== undefined &&
            (field.force_default || !hasMeaningfulAnswerValue(groupValue[field.id]))
          ) {
            groupValue[field.id] = toText(field.default_value);
            groupChanged = true;
          }
        }

        if (groupChanged) {
          next[item.id] = groupValue;
        }
      }

      for (const detailField of item.details_fields ?? []) {
        if (detailField.repeatable || detailField.default_value === undefined) {
          continue;
        }
        const detailKey = `${item.id}.${detailField.id}`;
        if (!hasMeaningfulAnswerValue(next[detailKey])) {
          next[detailKey] = toText(detailField.default_value);
        }
      }
    }
  }

  return next;
}

function buildQuestionnairePayload(
  pages: QuestionnairePage[],
  answers: QuestionnaireAnswerMap,
  source: string,
  formType?: string | null
) {
  return pages.flatMap((page) =>
    page.items.flatMap((item) => {
      const payload: Array<{
        question_id: string;
        value: unknown;
        source: string;
        form_type?: string | null;
      }> = [];

      if (item.fields?.length) {
        if (isRepeatableItem(item)) {
          const fields = item.fields ?? [];
          payload.push({
            question_id: item.id,
            value: trimTrailingEmptyRows(
              normalizeRepeatableGroupValue(answers[item.id], fields).map((row) =>
                Object.fromEntries(
                  fields.map((field) => [
                    field.id,
                    sanitizeQuestionnaireFieldValue(item, row[field.id], field),
                  ])
                )
              )
            ),
            source,
            form_type: formType ?? null,
          });
        } else {
          payload.push({
            question_id: item.id,
            value: getSanitizedGroupValue(item, answers),
            source,
            form_type: formType ?? null,
          });
        }
      } else {
        payload.push({
          question_id: item.id,
          value: sanitizeQuestionnaireFieldValue(item, answers[item.id]),
          source,
          form_type: formType ?? null,
        });
      }

      for (const detailField of item.details_fields ?? []) {
        const detailKey = `${item.id}.${detailField.id}`;
        payload.push({
          question_id: detailKey,
          value: detailField.repeatable
            ? trimTrailingEmptyScalars(
                Array.isArray(answers[detailKey])
                  ? answers[detailKey].map((entry) =>
                      sanitizeQuestionnaireFieldValue(item, entry, detailField)
                    )
                  : []
              )
            : sanitizeQuestionnaireFieldValue(item, answers[detailKey], detailField),
          source,
          form_type: formType ?? null,
        });
      }

      return payload;
    })
  );
}

function buildClientSectionPayload(
  sharedPages: QuestionnairePage[],
  sharedAnswers: QuestionnaireAnswerMap,
  formTypes: FormTypeInfo[],
  allFormsClientPlan: Record<string, ClientQuestionPlan>,
  formAnswers: QuestionnaireAnswerMap
): SaveQuestionnaireAnswerPayload[] {
  const payload: SaveQuestionnaireAnswerPayload[] = [
    ...buildQuestionnairePayload(sharedPages, sharedAnswers, "shared"),
  ];

  for (const form of formTypes) {
    const plan = allFormsClientPlan[form.form_type];
    if (plan) {
      payload.push(
        ...buildQuestionnairePayload(plan.pages, formAnswers, "form_client", form.form_type),
        ...plan.clearedAnswers.map((entry) => ({
          ...entry,
          source: "form_client",
          form_type: form.form_type,
        }))
      );
    }
  }

  return payload;
}

function buildFullQuestionnairePayload(
  sharedPages: QuestionnairePage[],
  sharedAnswers: QuestionnaireAnswerMap,
  formTypes: FormTypeInfo[],
  allFormsClientPlan: Record<string, ClientQuestionPlan>,
  allFormsAttorneyPages: Record<string, QuestionnairePage[]>,
  formAnswers: QuestionnaireAnswerMap
): SaveQuestionnaireAnswerPayload[] {
  const payload = buildClientSectionPayload(
    sharedPages,
    sharedAnswers,
    formTypes,
    allFormsClientPlan,
    formAnswers
  );

  for (const form of formTypes) {
    const attPages = allFormsAttorneyPages[form.form_type];
    if (attPages) {
      payload.push(
        ...buildQuestionnairePayload(attPages, formAnswers, "form_attorney", form.form_type)
      );
    }
  }

  return payload;
}

function groupItemsBySection(items: QuestionnaireItem[]) {
  const sectionMap = new Map<string, QuestionnaireItem[]>();
  for (const item of items) {
    const sectionName = item.section || "Questions";
    const existing = sectionMap.get(sectionName) ?? [];
    existing.push(item);
    sectionMap.set(sectionName, existing);
  }
  return Array.from(sectionMap.entries());
}

function toStableJsonValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((entry) => toStableJsonValue(entry));
  }

  if (isPlainObject(value)) {
    return Object.keys(value)
      .sort()
      .reduce<Record<string, unknown>>((acc, key) => {
        acc[key] = toStableJsonValue(value[key]);
        return acc;
      }, {});
  }

  return value;
}

function getAnswersSignature(answers: QuestionnaireAnswerMap): string {
  return JSON.stringify(toStableJsonValue(answers));
}

function cleanQuestionText(value: unknown): string {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ");
}

function mentionsAny(haystack: string, ...terms: string[]): boolean {
  return terms.some((term) => haystack.includes(term));
}

function normalizeAddressFieldId(fieldId: string): string {
  let normalized = cleanQuestionText(fieldId);
  if (!normalized) {
    return "";
  }
  if (normalized.startsWith("safe_")) {
    normalized = normalized.slice(5);
  }
  if (normalized.startsWith("mailing_")) {
    normalized = normalized.slice(8);
  }
  if (normalized.startsWith("physical_")) {
    normalized = normalized.slice(9);
  }
  if (normalized.startsWith("current_")) {
    normalized = normalized.slice(8);
  }
  return normalized;
}

function clearDuplicateSafeAddress(
  answers: QuestionnaireAnswerMap
): QuestionnaireAnswerMap {
  const physicalValue = answers[SHARED_PHYSICAL_ADDRESS_ID];
  const safeValue = answers[SHARED_SAFE_MAILING_ADDRESS_ID];
  if (!isPlainObject(safeValue)) {
    return answers;
  }

  const nextSafeValue: Record<string, unknown> = { ...safeValue };
  let changed = false;
  for (const [fieldId, rawValue] of Object.entries(nextSafeValue)) {
    const textValue = toText(rawValue);
    if (!hasText(textValue) || !looksLikeQuestionAnswerDump(textValue)) {
      continue;
    }
    nextSafeValue[fieldId] = "";
    changed = true;
  }

  if (!isPlainObject(physicalValue)) {
    return changed
      ? {
          ...answers,
          [SHARED_SAFE_MAILING_ADDRESS_ID]: nextSafeValue,
        }
      : answers;
  }

  const comparableKeys = ADDRESS_COMPARE_FIELD_IDS.filter((key) =>
    hasText(toText(nextSafeValue[key]))
  );
  if (comparableKeys.length === 0) {
    return changed
      ? {
          ...answers,
          [SHARED_SAFE_MAILING_ADDRESS_ID]: nextSafeValue,
        }
      : answers;
  }

  const hasRequiredAddressEvidence = ADDRESS_REQUIRED_COMPARE_FIELD_IDS.some((key) =>
    hasText(toText(nextSafeValue[key]))
  );
  if (!hasRequiredAddressEvidence) {
    return changed
      ? {
          ...answers,
          [SHARED_SAFE_MAILING_ADDRESS_ID]: nextSafeValue,
        }
      : answers;
  }

  const isDuplicate = comparableKeys.every(
    (key) =>
      cleanQuestionText(toText(nextSafeValue[key])) ===
      cleanQuestionText(toText(physicalValue[key]))
  );
  if (!isDuplicate) {
    return changed
      ? {
          ...answers,
          [SHARED_SAFE_MAILING_ADDRESS_ID]: nextSafeValue,
        }
      : answers;
  }

  changed = changed || comparableKeys.length > 0;
  if (!changed) {
    return answers;
  }

  for (const [fieldId, rawValue] of Object.entries(nextSafeValue)) {
    if (!hasText(toText(rawValue))) {
      continue;
    }
    nextSafeValue[fieldId] = "";
  }

  return {
    ...answers,
    [SHARED_SAFE_MAILING_ADDRESS_ID]: nextSafeValue,
  };
}

function clearLeaUnitAutofill(
  answers: QuestionnaireAnswerMap
): {
  answers: QuestionnaireAnswerMap;
  cleared: boolean;
} {
  const next: QuestionnaireAnswerMap = { ...answers };
  let cleared = false;

  if (isPlainObject(next["p3_5"])) {
    const groupValue = { ...(next["p3_5"] as Record<string, unknown>) };
    if (hasText(toText(groupValue.lea_unit_number))) {
      groupValue.lea_unit_number = "";
      next["p3_5"] = groupValue;
      cleared = true;
    }
  }

  if (hasText(toText(next["p3_5.lea_unit_number"]))) {
    next["p3_5.lea_unit_number"] = "";
    cleared = true;
  }

  return {
    answers: cleared ? next : answers,
    cleared,
  };
}

function getSharedAnswerAliases(item: QuestionnaireItem, field?: QuestionnaireField): string[] {
  const itemId = cleanQuestionText(item.id);
  const fieldId = cleanQuestionText(field?.id);
  const label = cleanQuestionText(field?.label);
  const formText = cleanQuestionText(item.form_text);
  const section = cleanQuestionText(item.section);
  const combined = [itemId, fieldId, label, formText, section].filter(Boolean).join(" | ");
  const aliases: string[] = [];

  const add = (alias: string) => {
    if (!aliases.includes(alias)) {
      aliases.push(alias);
    }
  };

  const relatedPersonContextExclusions = ["spouse", "child", "parent", "family member"];
  const nameContextExclusions = [
    ...relatedPersonContextExclusions,
    "interpreter",
    "preparer",
    "attorney",
  ];

  const normalizedNameFieldId = fieldId.startsWith("other_") ? fieldId.slice(6) : fieldId;
  if (["family_name", "given_name", "middle_name"].includes(normalizedNameFieldId)) {
    if (mentionsAny(combined, "other name", "alias", "nickname", "maiden")) {
      add(`shared.other_names_used.${normalizedNameFieldId}`);
    } else if (!mentionsAny(combined, ...nameContextExclusions)) {
      add(`shared.name.${normalizedNameFieldId}`);
    }
  }

  if (mentionsAny(combined, "alien registration", "a-number")) {
    add("shared.identifiers.a_number");
  }
  if (mentionsAny(combined, "social security", "ssn")) {
    add("shared.identifiers.ssn");
  }
  if (mentionsAny(combined, "uscis online account")) {
    add("shared.identifiers.uscis_online_account_number");
  }
  if (mentionsAny(combined, "i-94", "arrival-departure record")) {
    add("shared.identifiers.i94_record_number");
  }
  if (
    mentionsAny(combined, "passport or travel document number") &&
    !mentionsAny(combined, "issue date", "expiration", "issuing country")
  ) {
    add("shared.identifiers.passport_number");
    add("shared.identifiers.travel_document_number");
  } else if (
    mentionsAny(combined, "passport number") &&
    !mentionsAny(combined, "issue date", "expiration", "issuing country")
  ) {
    add("shared.identifiers.passport_number");
  }
  if (mentionsAny(combined, "travel document number")) {
    add("shared.identifiers.travel_document_number");
  }
  if (mentionsAny(combined, "sevis")) {
    add("shared.identifiers.sevis_number");
  }

  if (!mentionsAny(combined, ...relatedPersonContextExclusions)) {
    if (mentionsAny(combined, "date of birth")) {
      add("shared.biographics.date_of_birth");
    }
    if (
      fieldId === "birth_city" ||
      fieldId === "birth_city_town_village" ||
      (combined.includes("birth") && fieldId.includes("city") && !combined.includes("marriage"))
    ) {
      add("shared.biographics.birth_city");
    }
    if (
      fieldId === "birth_state_province" ||
      fieldId === "birth_state_or_province" ||
      (combined.includes("birth") && fieldId.includes("state") && !combined.includes("marriage"))
    ) {
      add("shared.biographics.birth_state_or_province");
    }
    if (fieldId === "birth_country" || mentionsAny(combined, "country of birth")) {
      add("shared.biographics.birth_country");
    }
    if (mentionsAny(combined, "sex")) {
      add("shared.biographics.sex");
    }
    if (mentionsAny(combined, "marital status")) {
      add("shared.biographics.marital_status");
    }
    if (mentionsAny(combined, "number of times married", "times married")) {
      add("shared.biographics.times_married");
    }

    if (mentionsAny(combined, "citizenship", "nationality")) {
      if (fieldId.startsWith("country_")) {
        const parts = fieldId.split("_");
        const slotNumber = Number(parts[parts.length - 1]);
        const slotIndex = Number.isFinite(slotNumber) && slotNumber > 0 ? slotNumber - 1 : 0;
        add(`shared.country_of_citizenship.country.${slotIndex}`);
      } else {
        add("shared.country_of_citizenship.country.0");
      }
    }
  }

  if (!mentionsAny(combined, "interpreter", "preparer", "employer", "law enforcement")) {
    if (mentionsAny(combined, "safe daytime telephone")) {
      add("shared.contact.safe_daytime_telephone_number");
    } else if (mentionsAny(combined, "daytime telephone")) {
      add("shared.contact.daytime_telephone_number");
    } else if (mentionsAny(combined, "mobile telephone")) {
      add("shared.contact.mobile_telephone_number");
    } else if (mentionsAny(combined, "email address", "email")) {
      add("shared.contact.email_address");
    }
  }

  const normalizedAddressFieldId = normalizeAddressFieldId(fieldId);
  if (
    normalizedAddressFieldId &&
    !mentionsAny(combined, "interpreter", "preparer", "employer", "law enforcement")
  ) {
    if (mentionsAny(combined, "address history", "last five years")) {
      add(`shared.address_history_last_five_years.${normalizedAddressFieldId}`);
    } else if (mentionsAny(combined, "safe mailing address", "u.s. mailing address", "mailing address")) {
      add(`shared.safe_mailing_address.${normalizedAddressFieldId}`);
    } else if (mentionsAny(combined, "physical address", "current physical address", "current address")) {
      add(`shared.current_physical_address.${normalizedAddressFieldId}`);
    }
  }

  return aliases;
}

function getEmptyAnswerValue(item: QuestionnaireItem): unknown {
  if (item.fields?.length) {
    return isRepeatableItem(item) ? [] : {};
  }
  return "";
}

function buildClientQuestionDedupResult(
  pages: QuestionnairePage[]
): {
  pages: QuestionnairePage[];
  clearedAnswers: Array<Pick<SaveQuestionnaireAnswerPayload, "question_id" | "value">>;
} {
  const clearedAnswers: Array<Pick<SaveQuestionnaireAnswerPayload, "question_id" | "value">> =
    [];

  const nextPages = pages
    .map((page) => {
      const nextItems = page.items.flatMap((item) => {
        if (!item.fields?.length) {
          if (getSharedAnswerAliases(item).length > 0) {
            clearedAnswers.push({
              question_id: item.id,
              value: getEmptyAnswerValue(item),
            });
            return [];
          }
          return [item];
        }

        const remainingFields = item.fields.filter(
          (field) => getSharedAnswerAliases(item, field).length === 0
        );

        if (remainingFields.length === item.fields.length) {
          return [item];
        }

        if (remainingFields.length === 0) {
          clearedAnswers.push({
            question_id: item.id,
            value: getEmptyAnswerValue(item),
          });
          return [];
        }

        return [
          {
            ...item,
            fields: remainingFields,
          },
        ];
      });

      return {
        ...page,
        items: nextItems,
      };
    })
    .filter((page) => page.items.length > 0);

  return {
    pages: nextPages,
    clearedAnswers,
  };
}

function mergeAutofillAnswers(
  currentAnswers: QuestionnaireAnswerMap,
  suggestedAnswers: QuestionnaireAnswerMap
): {
  answers: QuestionnaireAnswerMap;
  appliedCount: number;
} {
  const next: QuestionnaireAnswerMap = { ...currentAnswers };
  let appliedCount = 0;

  for (const [questionId, rawSuggestedValue] of Object.entries(suggestedAnswers)) {
    if (Array.isArray(rawSuggestedValue)) {
      const existing = next[questionId];
      const existingRows = Array.isArray(existing)
        ? existing.map((row) => (isPlainObject(row) ? { ...row } : {}))
        : [];
      const validRows = rawSuggestedValue.filter(hasMeaningfulRepeatableRow);
      if (validRows.length > 0) {
        if (existingRows.length === 0) {
          next[questionId] = validRows.map((row) =>
            Object.fromEntries(Object.entries(row).map(([fieldId, fieldValue]) => [fieldId, toText(fieldValue)]))
          );
          for (const row of validRows) {
            appliedCount += Object.values(row).filter((v) => hasText(toText(v))).length;
          }
          continue;
        }

        let changed = false;
        const mergedRows = [...existingRows];
        validRows.forEach((row, rowIndex) => {
          const targetRow = isPlainObject(mergedRows[rowIndex]) ? { ...mergedRows[rowIndex] } : {};
          for (const [fieldId, fieldValue] of Object.entries(row)) {
            const suggestedText = toText(fieldValue);
            if (!hasText(suggestedText) || hasText(toText(targetRow[fieldId]))) {
              continue;
            }
            targetRow[fieldId] = suggestedText;
            appliedCount += 1;
            changed = true;
          }
          mergedRows[rowIndex] = targetRow;
        });

        if (changed) {
          next[questionId] = mergedRows;
        }
      }
      continue;
    }

    if (isPlainObject(rawSuggestedValue)) {
      const existingValue = isPlainObject(next[questionId])
        ? { ...(next[questionId] as Record<string, unknown>) }
        : {};
      let changed = false;

      for (const [fieldId, rawFieldValue] of Object.entries(rawSuggestedValue)) {
        const suggestedText = toText(rawFieldValue);
        if (!hasText(suggestedText) || hasText(toText(existingValue[fieldId]))) {
          continue;
        }
        existingValue[fieldId] = suggestedText;
        appliedCount += 1;
        changed = true;
      }

      if (changed) {
        next[questionId] = existingValue;
      }
      continue;
    }

    const suggestedText = toText(rawSuggestedValue);
    if (!hasText(suggestedText) || hasText(toText(next[questionId]))) {
      continue;
    }

    next[questionId] = suggestedText;
    appliedCount += 1;
  }

  return {
    answers: next,
    appliedCount,
  };
}

function countFilledInputs(
  pages: QuestionnairePage[],
  answers: QuestionnaireAnswerMap
): { filled: number; total: number } {
  let filled = 0;
  let total = 0;

  for (const page of pages) {
    for (const item of page.items) {
      if (item.fields?.length) {
        if (isRepeatableItem(item)) {
          const rowCount = getRepeatableRowCount(item, answers);
          const rows = normalizeRepeatableGroupValue(answers[item.id], item.fields);
          total += rowCount * item.fields.length;
          for (let index = 0; index < rowCount; index += 1) {
            const row = rows[index] ?? createEmptyGroupValue(item.fields);
            for (const field of item.fields) {
              if (hasText(row[field.id] ?? "")) {
                filled += 1;
              }
            }
          }
        } else {
          const row = normalizeGroupValue(answers[item.id], item.fields);
          total += item.fields.length;
          for (const field of item.fields) {
            if (hasText(row[field.id] ?? "")) {
              filled += 1;
            }
          }
        }
      } else {
        total += 1;
        if (hasText(toText(answers[item.id]))) {
          filled += 1;
        }
      }

      for (const detailField of item.details_fields ?? []) {
        const detailKey = `${item.id}.${detailField.id}`;
        if (detailField.repeatable) {
          const rowCount = getRepeatableRowCount(item, answers);
          const values = Array.isArray(answers[detailKey])
            ? answers[detailKey].map((entry) => toText(entry))
            : [];
          total += rowCount;
          for (let index = 0; index < rowCount; index += 1) {
            if (hasText(values[index] ?? "")) {
              filled += 1;
            }
          }
        } else {
          total += 1;
          if (hasText(toText(answers[detailKey]))) {
            filled += 1;
          }
        }
      }
    }
  }

  return { filled, total };
}

function normalizeConditionalAnswerValue(value: unknown): string {
  const normalized = cleanQuestionText(value);
  if (["true", "yes", "y", "1", "checked", "on"].includes(normalized)) {
    return "yes";
  }
  if (["false", "no", "n", "0", "unchecked", "off"].includes(normalized)) {
    return "no";
  }
  return normalized;
}

function fieldConditionApplies(
  item: QuestionnaireItem,
  condition: string | undefined,
  answers: QuestionnaireAnswerMap
): boolean {
  const normalizedCondition = normalizeValidationText(condition ?? "");
  if (!normalizedCondition) {
    return true;
  }

  const currentAnswer = normalizeConditionalAnswerValue(answers[item.id]);
  if (normalizedCondition.includes("if yes")) {
    return currentAnswer === "yes";
  }
  if (normalizedCondition.includes("if no")) {
    return currentAnswer === "no";
  }
  return true;
}

function hasMeaningfulOptionalItemValue(
  item: QuestionnaireItem,
  answers: QuestionnaireAnswerMap
): boolean {
  if (item.fields?.length) {
    if (isRepeatableItem(item)) {
      return normalizeRepeatableGroupValue(answers[item.id], item.fields).some((row) => !isRowEmpty(row));
    }

    const row = normalizeGroupValue(answers[item.id], item.fields);
    return item.fields.some((field) => {
      const canonicalKey = `${item.id}.${field.id}`;
      return hasText(row[field.id] ?? "") || hasText(toText(answers[canonicalKey]));
    });
  }

  if (hasText(toText(answers[item.id]))) {
    return true;
  }

  return (item.details_fields ?? []).some((detailField) => {
    const detailKey = `${item.id}.${detailField.id}`;
    const value = answers[detailKey];
    return Array.isArray(value)
      ? value.some((entry) => hasText(toText(entry)))
      : hasText(toText(value));
  });
}

function optionalItemShouldValidate(
  item: QuestionnaireItem,
  answers: QuestionnaireAnswerMap,
  sharedAnswers: QuestionnaireAnswerMap
): boolean {
  if (hasMeaningfulOptionalItemValue(item, answers)) {
    return true;
  }

  return false;
}

function fieldIsRequiredForValidation(
  item: QuestionnaireItem,
  field: QuestionnaireField,
  _row?: RepeatableRow
): boolean {
  if (field.optional) {
    return false;
  }

  return true;
}

function shouldSkipRepeatableRowValidation(item: QuestionnaireItem, index: number): boolean {
  return isAdditionalRepeatableRow(index);
}

function collectMissingFields(
  item: QuestionnaireItem,
  answers: QuestionnaireAnswerMap,
  sharedAnswers: QuestionnaireAnswerMap = answers
): MissingRequiredField[] {
  const missing: MissingRequiredField[] = [];
  const missingKind: MissingRequiredField["kind"] = item.optional ? "review" : "required";
  const addMissing = (inputId: string, label: string, rowLabel?: string) => {
    missing.push({
      inputId,
      label,
      rowLabel,
      sectionCode: item.code || undefined,
      kind: missingKind,
    });
  };

  if (item.optional && !optionalItemShouldValidate(item, answers, sharedAnswers)) {
    return missing;
  }

  if (item.fields?.length) {
    if (isRepeatableItem(item)) {
      const rows = normalizeRepeatableGroupValue(answers[item.id], item.fields);
      const rowIndexes = item.optional
        ? rows
            .map((row, index) => (!isRowEmpty(row) ? index : -1))
            .filter((index) => index >= 0)
        : Array.from({ length: getRepeatableRowCount(item, answers) }, (_, index) => index);
      for (const index of rowIndexes) {
        if (shouldSkipRepeatableRowValidation(item, index)) {
          continue;
        }
        const row = rows[index] ?? createEmptyGroupValue(item.fields);
        const rowLabel = getRepeatableRowLabel(item, index);
        for (const field of item.fields) {
          if (
            !fieldIsRequiredForValidation(item, field, row) ||
            !fieldConditionApplies(item, field.condition, answers) ||
            hasText(row[field.id] ?? "")
          ) {
            continue;
          }
          addMissing(`${item.id}-${index}-${field.id}`, field.label, rowLabel);
        }
      }
    } else {
      const row = normalizeGroupValue(answers[item.id], item.fields);
      for (const field of item.fields) {
        if (
          !fieldIsRequiredForValidation(item, field, row) ||
          !fieldConditionApplies(item, field.condition, answers)
        ) {
          continue;
        }

        const canonicalKey = `${item.id}.${field.id}`;
        const value = hasText(row[field.id] ?? "")
          ? row[field.id] ?? ""
          : canonicalKey in answers
            ? toText(answers[canonicalKey])
            : "";

        if (!hasText(value)) {
          addMissing(`${item.id}-${field.id}`, field.label);
        }
      }
    }
  } else if (!hasText(toText(answers[item.id]))) {
    addMissing(item.id, item.form_text);
  }

  for (const detailField of item.details_fields ?? []) {
    if (
      detailField.optional ||
      !fieldConditionApplies(item, detailField.condition, answers)
    ) {
      continue;
    }

    const detailKey = `${item.id}.${detailField.id}`;
    if (detailField.repeatable) {
      const rowCount = getRepeatableRowCount(item, answers);
      const values = Array.isArray(answers[detailKey])
        ? answers[detailKey].map((entry) => toText(entry))
        : [];
      for (let index = 0; index < rowCount; index += 1) {
        if (isAdditionalRepeatableRow(index)) {
          continue;
        }
        if (hasText(values[index] ?? "")) {
          continue;
        }
        addMissing(`${detailKey}-${index}`, detailField.label, getRepeatableRowLabel(item, index));
      }
    } else if (!hasText(toText(answers[detailKey]))) {
      addMissing(detailKey, detailField.label);
    }
  }

  return missing;
}

function collectMissingRequiredFields(
  pages: QuestionnairePage[],
  answers: QuestionnaireAnswerMap,
  sharedAnswers: QuestionnaireAnswerMap = answers
): MissingRequiredField[] {
  const missing: MissingRequiredField[] = [];

  for (const page of pages) {
    for (const item of page.items) {
      missing.push(...collectMissingFields(item, answers, sharedAnswers));
    }
  }

  return missing;
}

function getJobPdfCacheKey(
  job: Pick<FormFillingJob, "id" | "filled_pdf_path" | "updated_at" | "completed_at">
): string {
  return [
    job.id,
    job.filled_pdf_path ?? "",
    job.completed_at ?? "",
    job.updated_at ?? "",
  ].join("|");
}

function formatDateLabel(value: string | null | undefined): string {
  return formatJobTimestamp(value);
}

type DateSelectPart = "month" | "day" | "year";
type DateSelectParts = Record<DateSelectPart, string>;

const EMPTY_DATE_SELECT_PARTS: DateSelectParts = {
  month: "",
  day: "",
  year: "",
};
const MIN_DATE_SELECT_YEAR = 1900;
const FUTURE_DATE_SELECT_YEAR_BUFFER = 20;

function getDateSelectParts(value: string, literalValue?: boolean): DateSelectParts {
  if (literalValue) {
    return { ...EMPTY_DATE_SELECT_PARTS };
  }
  const dt = parseFlexibleDate(value);
  if (!dt) {
    return { ...EMPTY_DATE_SELECT_PARTS };
  }
  return {
    month: String(dt.getMonth() + 1),
    day: String(dt.getDate()).padStart(2, "0"),
    year: String(dt.getFullYear()),
  };
}

function getDaysInSelectedMonth(month: string, year: string): number {
  const monthNumber = Number(month);
  if (!monthNumber) {
    return 31;
  }
  const yearNumber = Number(year) || new Date().getFullYear();
  return new Date(yearNumber, monthNumber, 0).getDate();
}

function formatDateSelectValue(parts: DateSelectParts): string {
  if (!parts.month || !parts.day || !parts.year) {
    return "";
  }
  const month = Number(parts.month);
  const day = Number(parts.day);
  const year = Number(parts.year);
  const dt = new Date(year, month - 1, day);
  if (
    dt.getFullYear() !== year ||
    dt.getMonth() !== month - 1 ||
    dt.getDate() !== day
  ) {
    return "";
  }
  return formatLongDate(dt);
}

function DateField({
  id,
  value,
  onChange,
  hasError,
  labelledBy,
  ariaLabel,
  combinedDescribedBy,
  literalValue,
}: {
  id: string;
  value: string;
  onChange: (val: string) => void;
  hasError?: boolean;
  labelledBy?: string;
  ariaLabel?: string;
  combinedDescribedBy?: string;
  literalValue?: boolean;
}) {
  const [parts, setParts] = useState<DateSelectParts>(() =>
    getDateSelectParts(value, literalValue)
  );
  const pendingLocalChangeRef = useRef(false);

  useEffect(() => {
    if (pendingLocalChangeRef.current) {
      pendingLocalChangeRef.current = false;
      return;
    }
    setParts(getDateSelectParts(value, literalValue));
  }, [literalValue, value]);

  const daysInMonth = getDaysInSelectedMonth(parts.month, parts.year);
  const dayOptions = Array.from({ length: daysInMonth }, (_, index) =>
    String(index + 1).padStart(2, "0")
  );
  const yearOptions = useMemo(() => {
    const currentYear = new Date().getFullYear();
    const maxYear = currentYear + FUTURE_DATE_SELECT_YEAR_BUFFER;
    const years = Array.from(
      { length: maxYear - MIN_DATE_SELECT_YEAR + 1 },
      (_, index) => String(maxYear - index)
    );
    if (parts.year && !years.includes(parts.year)) {
      years.push(parts.year);
      years.sort((a, b) => Number(b) - Number(a));
    }
    return years;
  }, [parts.year]);

  const updatePart = (part: DateSelectPart, nextValue: string) => {
    const nextParts: DateSelectParts = {
      ...parts,
      [part]: nextValue,
    };
    if (part !== "day") {
      const maxDay = getDaysInSelectedMonth(nextParts.month, nextParts.year);
      if (nextParts.day && Number(nextParts.day) > maxDay) {
        nextParts.day = "";
      }
    }
    setParts(nextParts);
    pendingLocalChangeRef.current = true;
    onChange(formatDateSelectValue(nextParts));
  };

  const selectClassName = `rounded-xl border px-3 py-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 ${
    hasError
      ? "border-red-300 bg-red-50 text-red-900 focus-visible:border-red-500 focus-visible:ring-red-200"
      : "border-gray-200 bg-white text-gray-800 focus-visible:border-brand-500 focus-visible:ring-brand-100"
  }`;

  return (
    <div
      role="group"
      aria-labelledby={labelledBy}
      aria-describedby={combinedDescribedBy}
      className="grid grid-cols-3 gap-2"
    >
      <select
        id={id}
        name={`${id}-month`}
        value={parts.month}
        autoComplete="off"
        aria-label={labelledBy ? "Month" : `${ariaLabel} month`}
        aria-describedby={combinedDescribedBy}
        aria-invalid={hasError ? "true" : undefined}
        onChange={(event) => updatePart("month", event.target.value)}
        className={selectClassName}
      >
        <option value="">Mmm</option>
        {MONTH_ABBR_EN.map((month, index) => (
          <option key={`${id}-month-${month}`} value={String(index + 1)}>
            {month}
          </option>
        ))}
      </select>
      <select
        name={`${id}-day`}
        value={parts.day}
        autoComplete="off"
        aria-label={labelledBy ? "Day" : `${ariaLabel} day`}
        aria-describedby={combinedDescribedBy}
        aria-invalid={hasError ? "true" : undefined}
        onChange={(event) => updatePart("day", event.target.value)}
        className={selectClassName}
      >
        <option value="">DD</option>
        {dayOptions.map((day) => (
          <option key={`${id}-day-${day}`} value={day}>
            {day}
          </option>
        ))}
      </select>
      <select
        name={`${id}-year`}
        value={parts.year}
        autoComplete="off"
        aria-label={labelledBy ? "Year" : `${ariaLabel} year`}
        aria-describedby={combinedDescribedBy}
        aria-invalid={hasError ? "true" : undefined}
        onChange={(event) => updatePart("year", event.target.value)}
        className={selectClassName}
      >
        <option value="">YYYY</option>
        {yearOptions.map((year) => (
          <option key={`${id}-year-${year}`} value={year}>
            {year}
          </option>
        ))}
      </select>
    </div>
  );
}

export default function FormFillingPanel({
  caseId,
  caseData,
  pages,
  onCaseUpdated,
  onPagesUpdated,
}: Props) {
  const [step, setStep] = useState<WizardStep>("client_questions");

  const [sharedPages, setSharedPages] = useState<QuestionnairePage[]>([]);
  const [sharedAnswers, setSharedAnswers] = useState<QuestionnaireAnswerMap>({});
  const [loadingShared, setLoadingShared] = useState(true);
  const [savingClientQuestions, setSavingClientQuestions] = useState(false);
  const [autofillingFormQuestions, setAutofillingFormQuestions] = useState(false);
  const [autofillingSharedQuestions, setAutofillingSharedQuestions] = useState(false);
  const [autofillProgress, setAutofillProgress] = useState(0);
  const [autofillPhaseMessage, setAutofillPhaseMessage] = useState("");
  const [verificationMap, setVerificationMap] = useState<VerificationMap>({});

  const [autofillingAttorneyQuestions, setAutofillingAttorneyQuestions] = useState(false);
  const [attorneyAutofillProgress, setAttorneyAutofillProgress] = useState(0);
  const [attorneyAutofillPhaseMessage, setAttorneyAutofillPhaseMessage] = useState("");

  const [formTypes, setFormTypes] = useState<FormTypeInfo[]>([]);
  const [, setLoadingFormTypes] = useState(true);

  const [, setAllFormsClientPages] = useState<Record<string, QuestionnairePage[]>>({});
  const [allFormsAttorneyPages, setAllFormsAttorneyPages] = useState<Record<string, QuestionnairePage[]>>({});
  const [allFormsClientPlan, setAllFormsClientPlan] = useState<Record<string, ClientQuestionPlan>>(
    {}
  );

  const [formAnswers, setFormAnswers] = useState<QuestionnaireAnswerMap>({});
  const [loadingFormDetails, setLoadingFormDetails] = useState(false);
  const [savingAttorneyQuestions, setSavingAttorneyQuestions] = useState(false);
  const [generatingFormType, setGeneratingFormType] = useState<string | null>(null);
  const [autosaveStatus, setAutosaveStatus] = useState<"idle" | "saving" | "saved" | "error">(
    "idle"
  );

  const [jobs, setJobs] = useState<FormFillingJob[]>([]);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [job, setJob] = useState<FormFillingJob | null>(null);
  const [loadingJobs, setLoadingJobs] = useState(true);
  const [loadingJobDetails, setLoadingJobDetails] = useState(false);
  const [, setRefreshingJob] = useState(false);
  const [regeneratingJob, setRegeneratingJob] = useState(false);
  const [pdfPreviewUrl, setPdfPreviewUrl] = useState<string | null>(null);
  const [loadingPdfPreview, setLoadingPdfPreview] = useState(false);
  const [sharedLoadError, setSharedLoadError] = useState<string | null>(null);
  const [formLoadError, setFormLoadError] = useState<string | null>(null);
  const [jobsLoadError, setJobsLoadError] = useState<string | null>(null);
  const [jobDetailsError, setJobDetailsError] = useState<string | null>(null);
  const [previewLoadError, setPreviewLoadError] = useState<string | null>(null);
  const [previewRetryCount, setPreviewRetryCount] = useState(0);
  const [savingDocumentScope, setSavingDocumentScope] = useState(false);
  const [savedSharedAnswersSignature, setSavedSharedAnswersSignature] = useState<string | null>(
    null
  );
  const [savedClientAnswersSignature, setSavedClientAnswersSignature] = useState<string | null>(
    null
  );
  const [savedAttorneyAnswersSignature, setSavedAttorneyAnswersSignature] =
    useState<string | null>(null);
  const [confirmedSharedAnswersSignature, setConfirmedSharedAnswersSignature] = useState<
    string | null
  >(null);
  const [confirmedClientAnswersSignature, setConfirmedClientAnswersSignature] = useState<
    string | null
  >(null);
  const [confirmedAttorneyAnswersSignature, setConfirmedAttorneyAnswersSignature] = useState<
    string | null
  >(null);
  const [activeClientFormType, setActiveClientFormType] = useState<string | null>(null);
  const [activeAttorneyFormType, setActiveAttorneyFormType] = useState<string | null>(null);
  const sharedAnswersRef = useRef<QuestionnaireAnswerMap>({});
  const formAnswersRef = useRef<QuestionnaireAnswerMap>({});
  const autosaveTimerRef = useRef<number | null>(null);
  const autosaveRequestIdRef = useRef(0);
  const hasInitializedConfirmationRef = useRef(false);
  const completedJobsSeenRef = useRef<Set<string>>(new Set());
  const didPrimeCompletedJobsRef = useRef(false);

  const [selectedArea, setSelectedArea] = useState<"Todas" | "Visa T" | "SIJS">("Todas");
  const [selectedFormToGenerate, setSelectedFormToGenerate] = useState<string>("");

  const formScopeDocuments = useMemo(() => listSelectableCaseDocuments(pages), [pages]);
  const selectedFormSourceDocumentIds = useMemo(
    () =>
      resolveSelectedSourceDocumentIds(
        caseData,
        "form_filling_source_document_ids",
        formScopeDocuments
      ),
    [caseData, formScopeDocuments]
  );
  const canRunFormAutofill =
    pages.length > 0 &&
    (formScopeDocuments.length === 0 || selectedFormSourceDocumentIds.length > 0);
  const showUnifiedAutofillControl =
    step === "client_questions" || step === "attorney_questions";
  const activeFormAutofillPhaseMessage = autofillingSharedQuestions
    ? `Client: ${autofillPhaseMessage}`
    : autofillingAttorneyQuestions
      ? `Attorney: ${attorneyAutofillPhaseMessage}`
      : "";
  const activeFormAutofillProgress = autofillingSharedQuestions
    ? Math.round(autofillProgress)
    : autofillingAttorneyQuestions
      ? Math.round(attorneyAutofillProgress)
      : 0;

  useEffect(() => {
    sharedAnswersRef.current = sharedAnswers;
  }, [sharedAnswers]);

  useEffect(() => {
    formAnswersRef.current = formAnswers;
  }, [formAnswers]);

  const handleFormScopeChange = useCallback(
    async (nextSelectedIds: string[]) => {
      setSavingDocumentScope(true);
      try {
        const updatedCase = await updateCase(
          caseId,
          buildScopeUpdatePayload(
            "form_filling_source_document_ids",
            nextSelectedIds,
            formScopeDocuments
          )
        );
        onCaseUpdated?.(updatedCase);
      } catch {
        toast.error("No se pudo guardar el alcance de documentos para formularios");
      } finally {
        setSavingDocumentScope(false);
      }
    },
    [caseId, formScopeDocuments, onCaseUpdated]
  );

  const sharedCounts = useMemo(
    () => countFilledInputs(sharedPages, sharedAnswers),
    [sharedAnswers, sharedPages]
  );

  const clientQuestionPages = useMemo(
    () => Object.values(allFormsClientPlan).flatMap((plan) => plan?.pages ?? []),
    [allFormsClientPlan]
  );

  const attorneyQuestionPages = useMemo(
    () => Object.values(allFormsAttorneyPages).flat(),
    [allFormsAttorneyPages]
  );

  const sharedAnswersSignature = useMemo(
    () => getAnswersSignature(extractRelevantAnswers(sharedAnswers, sharedPages)),
    [sharedAnswers, sharedPages]
  );

  const clientAnswersSignature = useMemo(
    () => getAnswersSignature(extractRelevantAnswers(formAnswers, clientQuestionPages)),
    [clientQuestionPages, formAnswers]
  );

  const attorneyAnswersSignature = useMemo(
    () => getAnswersSignature(extractRelevantAnswers(formAnswers, attorneyQuestionPages)),
    [attorneyQuestionPages, formAnswers]
  );

  const clientCounts = useMemo(() => {
    let filled = 0;
    let total = 0;
    for (const plan of Object.values(allFormsClientPlan)) {
      if (plan) {
        const c = countFilledInputs(plan.pages, formAnswers);
        filled += c.filled;
        total += c.total;
      }
    }
    return { filled, total };
  }, [allFormsClientPlan, formAnswers]);

  const attorneyCounts = useMemo(() => {
    let filled = 0;
    let total = 0;
    for (const pages of Object.values(allFormsAttorneyPages)) {
      if (pages) {
        const c = countFilledInputs(pages, formAnswers);
        filled += c.filled;
        total += c.total;
      }
    }
    return { filled, total };
  }, [allFormsAttorneyPages, formAnswers]);
  const clientSectionCounts = useMemo(
    () => ({
      filled: sharedCounts.filled + clientCounts.filled,
      total: sharedCounts.total + clientCounts.total,
    }),
    [clientCounts, sharedCounts]
  );

  const clientFormsWithQuestions = useMemo(
    () =>
      formTypes.filter((form) => {
        const plan = allFormsClientPlan[form.form_type];
        return Boolean(plan && plan.pages.length > 0);
      }),
    [allFormsClientPlan, formTypes]
  );

  const clientFormCounts = useMemo<Record<string, { filled: number; total: number }>>(
    () =>
      Object.fromEntries(
        clientFormsWithQuestions.map((form) => [
          form.form_type,
          countFilledInputs(allFormsClientPlan[form.form_type]?.pages ?? [], formAnswers),
        ])
      ),
    [allFormsClientPlan, clientFormsWithQuestions, formAnswers]
  );

  const activeClientForm =
    clientFormsWithQuestions.find((form) => form.form_type === activeClientFormType) ??
    clientFormsWithQuestions[0] ??
    null;
  const activeClientPlan = activeClientForm
    ? allFormsClientPlan[activeClientForm.form_type] ?? null
    : null;
  const activeClientCounts = activeClientForm
    ? clientFormCounts[activeClientForm.form_type] ?? { filled: 0, total: 0 }
    : null;
  const missingClientRequiredFields = useMemo<MissingRequiredField[]>(
    () => collectMissingRequiredFields(sharedPages, sharedAnswers, sharedAnswers),
    [sharedAnswers, sharedPages]
  );
  const firstMissingClientRequiredField =
    missingClientRequiredFields[0] ?? null;

  const attorneyFormsWithQuestions = useMemo(
    () =>
      formTypes.filter((form) => {
        const pages = allFormsAttorneyPages[form.form_type];
        return Boolean(pages && pages.length > 0);
      }),
    [allFormsAttorneyPages, formTypes]
  );

  const attorneyFormCounts = useMemo<Record<string, { filled: number; total: number }>>(
    () =>
      Object.fromEntries(
        attorneyFormsWithQuestions.map((form) => [
          form.form_type,
          countFilledInputs(allFormsAttorneyPages[form.form_type] ?? [], formAnswers),
        ])
      ),
    [allFormsAttorneyPages, attorneyFormsWithQuestions, formAnswers]
  );

  const activeAttorneyForm =
    attorneyFormsWithQuestions.find((form) => form.form_type === activeAttorneyFormType) ??
    attorneyFormsWithQuestions[0] ??
    null;
  const activeAttorneyPages = activeAttorneyForm
    ? allFormsAttorneyPages[activeAttorneyForm.form_type] ?? null
    : null;
  const activeAttorneyCounts = activeAttorneyForm
    ? attorneyFormCounts[activeAttorneyForm.form_type] ?? { filled: 0, total: 0 }
    : null;

  const clientStepAutosaved =
    savedSharedAnswersSignature !== null &&
    savedClientAnswersSignature !== null &&
    sharedAnswersSignature === savedSharedAnswersSignature &&
    clientAnswersSignature === savedClientAnswersSignature;

  const attorneyStepAutosaved =
    clientStepAutosaved &&
    savedAttorneyAnswersSignature !== null &&
    attorneyAnswersSignature === savedAttorneyAnswersSignature;

  const clientPersonalDataRequiredComplete =
    missingClientRequiredFields.length === 0;
  const clientStepConfirmed =
    clientPersonalDataRequiredComplete &&
    confirmedSharedAnswersSignature !== null &&
    confirmedClientAnswersSignature !== null &&
    sharedAnswersSignature === confirmedSharedAnswersSignature &&
    clientAnswersSignature === confirmedClientAnswersSignature;

  const attorneyStepConfirmed =
    clientStepConfirmed &&
    confirmedAttorneyAnswersSignature !== null &&
    attorneyAnswersSignature === confirmedAttorneyAnswersSignature;

  const clientStepStarted = clientSectionCounts.filled > 0;
  const attorneyStepStarted = attorneyCounts.filled > 0;
  const hasPreviewHistory = jobs.length > 0;
  const canOpenAttorneyStep =
    !loadingShared &&
    !loadingFormDetails &&
    !sharedLoadError &&
    !formLoadError;
  const canOpenPreviewStep =
    !loadingFormDetails && !formLoadError && (clientStepConfirmed || hasPreviewHistory);

  const clearAutosaveTimer = () => {
    if (autosaveTimerRef.current !== null) {
      window.clearTimeout(autosaveTimerRef.current);
      autosaveTimerRef.current = null;
    }
  };

  const buildPayloadForAnswers = (
    scope: QuestionnaireSaveScope,
    nextSharedAnswers: QuestionnaireAnswerMap,
    nextFormAnswers: QuestionnaireAnswerMap
  ) =>
    scope === "client"
      ? buildClientSectionPayload(
          sharedPages,
          nextSharedAnswers,
          formTypes,
          allFormsClientPlan,
          nextFormAnswers
        )
      : buildFullQuestionnairePayload(
          sharedPages,
          nextSharedAnswers,
          formTypes,
          allFormsClientPlan,
          allFormsAttorneyPages,
          nextFormAnswers
        );

  const buildPayloadForScope = (scope: QuestionnaireSaveScope) =>
    buildPayloadForAnswers(scope, sharedAnswers, formAnswers);

  const markScopeAsSaved = (
    scope: QuestionnaireSaveScope,
    signatures: QuestionnaireSignatures
  ) => {
    setSavedSharedAnswersSignature(signatures.shared);
    setSavedClientAnswersSignature(signatures.client);
    if (scope === "all") {
      setSavedAttorneyAnswersSignature(signatures.attorney);
    }
  };

  const markScopeAsConfirmed = (
    scope: QuestionnaireSaveScope,
    signatures: QuestionnaireSignatures
  ) => {
    setConfirmedSharedAnswersSignature(signatures.shared);
    setConfirmedClientAnswersSignature(signatures.client);
    if (scope === "all") {
      setConfirmedAttorneyAnswersSignature(signatures.attorney);
    }
  };

  const getCurrentSignatures = (): QuestionnaireSignatures => ({
    shared: sharedAnswersSignature,
    client: clientAnswersSignature,
    attorney: attorneyAnswersSignature,
  });

  const preparePersistedAnswerState = useCallback(
    (
      nextSharedAnswers: QuestionnaireAnswerMap,
      nextFormAnswers: QuestionnaireAnswerMap
    ): {
      sharedAnswers: QuestionnaireAnswerMap;
      formAnswers: QuestionnaireAnswerMap;
      signatures: QuestionnaireSignatures;
    } => {
      const sanitizedSharedAnswers = sanitizeAnswersForPages(
        sharedPages,
        nextSharedAnswers
      );
      const sanitizedFormAnswers = sanitizeAnswersForPages(
        [...clientQuestionPages, ...attorneyQuestionPages],
        nextFormAnswers
      );

      return {
        sharedAnswers: sanitizedSharedAnswers,
        formAnswers: sanitizedFormAnswers,
        signatures: {
          shared: getAnswersSignature(extractRelevantAnswers(sanitizedSharedAnswers, sharedPages)),
          client: getAnswersSignature(
            extractRelevantAnswers(sanitizedFormAnswers, clientQuestionPages)
          ),
          attorney: getAnswersSignature(
            extractRelevantAnswers(sanitizedFormAnswers, attorneyQuestionPages)
          ),
        },
      };
    },
    [attorneyQuestionPages, clientQuestionPages, sharedPages]
  );

  const persistAutofillAnswers = async (
    scope: QuestionnaireSaveScope,
    nextSharedAnswers: QuestionnaireAnswerMap,
    nextFormAnswers: QuestionnaireAnswerMap
  ) => {
    clearAutosaveTimer();
    ++autosaveRequestIdRef.current;
    const prepared = preparePersistedAnswerState(nextSharedAnswers, nextFormAnswers);
    sharedAnswersRef.current = prepared.sharedAnswers;
    formAnswersRef.current = prepared.formAnswers;
    setSharedAnswers(prepared.sharedAnswers);
    setFormAnswers(prepared.formAnswers);

    setAutosaveStatus("saving");
    await saveQuestionnaireAnswers(
      caseId,
      buildPayloadForAnswers(scope, prepared.sharedAnswers, prepared.formAnswers)
    );

    markScopeAsSaved(scope, prepared.signatures);
    setAutosaveStatus("saved");
  };

  const getAutosaveStatusMessage = () => {
    switch (autosaveStatus) {
      case "saving":
        return "Saving changes...";
      case "saved":
        return "Changes saved.";
      case "error":
        return "The latest changes could not be saved. Confirm to retry.";
      default:
        return "";
    }
  };

  const syncJobInList = useCallback((updatedJob: FormFillingJob) => {
    setJobs((prev) => {
      const exists = prev.some((item) => item.id === updatedJob.id);
      const next = exists
        ? prev.map((item) => (item.id === updatedJob.id ? updatedJob : item))
        : [updatedJob, ...prev];
      return [...next].sort((left, right) => getJobSortTime(right) - getJobSortTime(left));
    });
  }, []);

  const loadPersistedVerifications = async () => {
    try {
      const data = await getQuestionnaireVerifications(caseId);
      if (data && Object.keys(data).length > 0) {
        setVerificationMap((prev) => ({ ...data, ...prev }));
      }
    } catch {
      // Non-blocking: badges only fail to appear if persistence is unavailable.
    }
  };

  const loadSharedStep = async () => {
    setLoadingShared(true);
    setSharedLoadError(null);
    try {
      const pages = await getSharedQuestions();
      setSharedPages(pages);

      try {
        const answers = await getQuestionnaireAnswers(caseId);
        const rawRelevantAnswers = extractRelevantAnswers(answers, pages);
        const relevantAnswers = clearDuplicateSafeAddress(rawRelevantAnswers);
        const defaultedAnswers = applyQuestionnaireDefaults(pages, relevantAnswers);
        const sanitizedAnswers = sanitizeAnswersForPages(pages, defaultedAnswers);
        setSharedAnswers(sanitizedAnswers);
        setSavedSharedAnswersSignature(
          getAnswersSignature(extractRelevantAnswers(sanitizedAnswers, pages))
        );
      } catch {
        setSharedAnswers({});
        setSavedSharedAnswersSignature(null);
        setSharedLoadError("Saved shared answers could not be loaded.");
        toast.error("Saved shared answers could not be loaded");
      }
    } catch {
      setSharedPages([]);
      setSharedAnswers({});
      setSavedSharedAnswersSignature(null);
      setSharedLoadError("Shared questions could not be loaded.");
      toast.error("Shared questions could not be loaded");
    } finally {
      setLoadingShared(false);
    }
  };

  const loadFormTypesAndQuestions = async () => {
    setLoadingFormTypes(true);
    setLoadingFormDetails(true);
    setFormLoadError(null);
    try {
      const data = (await getAvailableFormTypes()).filter(
        (form) => !isHiddenFormType(form.form_type)
      );
      setFormTypes(data);

      const clientMap: Record<string, QuestionnairePage[]> = {};
      const attorneyMap: Record<string, QuestionnairePage[]> = {};
      const planMap: Record<string, ClientQuestionPlan> = {};

      const promises = data.map(async (form) => {
        const [client, attorney] = await Promise.all([
          getFormClientQuestions(form.form_type).catch(() => []),
          getFormAttorneyQuestions(form.form_type).catch(() => []),
        ]);
        clientMap[form.form_type] = client;
        attorneyMap[form.form_type] = attorney;
        planMap[form.form_type] = buildClientQuestionDedupResult(client);
      });

      await Promise.all(promises);

      setAllFormsClientPages(clientMap);
      setAllFormsAttorneyPages(attorneyMap);
      setAllFormsClientPlan(planMap);

      const savedAnswers = await getQuestionnaireAnswers(caseId);
      const allPages = [
        ...Object.values(planMap).flatMap((p) => p.pages),
        ...Object.values(attorneyMap).flat(),
      ];
      const defaultedFormAnswers = applyQuestionnaireDefaults(
        allPages,
        extractRelevantAnswers(savedAnswers, allPages)
      );
      const sanitizedFormAnswers = sanitizeAnswersForPages(
        allPages,
        defaultedFormAnswers
      );
      setFormAnswers(sanitizedFormAnswers);
      setSavedClientAnswersSignature(
        getAnswersSignature(
          extractRelevantAnswers(
            sanitizedFormAnswers,
            Object.values(planMap).flatMap((plan) => plan.pages)
          )
        )
      );
      setSavedAttorneyAnswersSignature(
        getAnswersSignature(
          extractRelevantAnswers(sanitizedFormAnswers, Object.values(attorneyMap).flat())
        )
      );
    } catch {
      setSavedClientAnswersSignature(null);
      setSavedAttorneyAnswersSignature(null);
      setFormLoadError("Form questions or answers could not be loaded.");
      toast.error("Forms or questions could not be loaded");
    } finally {
      setLoadingFormTypes(false);
      setLoadingFormDetails(false);
    }
  };

  const loadJobs = async (showLoading = false, silent = false) => {
    if (showLoading) {
      setLoadingJobs(true);
    }
    try {
      const data = await getFormFillingJobs(caseId);
      const sortedJobs = data
        .filter((item) => !isHiddenFormType(item.form_type))
        .sort((left, right) => getJobSortTime(right) - getJobSortTime(left));
      if (!didPrimeCompletedJobsRef.current) {
        completedJobsSeenRef.current = new Set(
          sortedJobs
            .filter((item) => item.status === "completed" && Boolean(item.filled_pdf_path))
            .map((item) => item.id)
        );
        didPrimeCompletedJobsRef.current = true;
      }
      setJobsLoadError(null);
      setJobs(sortedJobs);
      setActiveJobId((current) => {
        if (current && sortedJobs.some((item) => item.id === current)) {
          return current;
        }
        return sortedJobs[0]?.id ?? null;
      });
    } catch {
      setJobsLoadError("Form history could not be loaded.");
      if (showLoading) {
        setJobs([]);
      }
      if (!silent) {
        toast.error("Form history could not be loaded");
      }
    } finally {
      if (showLoading) {
        setLoadingJobs(false);
      }
    }
  };

  useEffect(() => {
    setStep("client_questions");
    setAllFormsClientPages({});
    setAllFormsAttorneyPages({});
    setAllFormsClientPlan({});
    setFormAnswers({});
    setJobs([]);
    setActiveJobId(null);
    setJob(null);
    setPdfPreviewUrl(null);
    setLoadingPdfPreview(false);
    setSharedLoadError(null);
    setFormLoadError(null);
    setJobsLoadError(null);
    setJobDetailsError(null);
    setPreviewLoadError(null);
    setPreviewRetryCount(0);
    setVerificationMap({});
    setSavedSharedAnswersSignature(null);
    setSavedClientAnswersSignature(null);
    setSavedAttorneyAnswersSignature(null);
    setConfirmedSharedAnswersSignature(null);
    setConfirmedClientAnswersSignature(null);
    setConfirmedAttorneyAnswersSignature(null);
    setActiveClientFormType(null);
    setActiveAttorneyFormType(null);
    setAutosaveStatus("idle");
    clearAutosaveTimer();
    autosaveRequestIdRef.current = 0;
    hasInitializedConfirmationRef.current = false;
    completedJobsSeenRef.current = new Set();
    didPrimeCompletedJobsRef.current = false;

    void loadSharedStep();
    void loadFormTypesAndQuestions();
    void loadJobs(true, true);
    void loadPersistedVerifications();
  }, [caseId]);

  useEffect(() => {
    if (clientFormsWithQuestions.length === 0) {
      setActiveClientFormType(null);
      return;
    }

    setActiveClientFormType((current) =>
      current && clientFormsWithQuestions.some((form) => form.form_type === current)
        ? current
        : clientFormsWithQuestions[0].form_type
    );
  }, [clientFormsWithQuestions]);

  useEffect(() => {
    if (attorneyFormsWithQuestions.length === 0) {
      setActiveAttorneyFormType(null);
      return;
    }

    setActiveAttorneyFormType((current) =>
      current && attorneyFormsWithQuestions.some((form) => form.form_type === current)
        ? current
        : attorneyFormsWithQuestions[0].form_type
    );
  }, [attorneyFormsWithQuestions]);

  useEffect(() => {
    if (
      hasInitializedConfirmationRef.current ||
      loadingShared ||
      loadingFormDetails ||
      sharedLoadError ||
      formLoadError
    ) {
      return;
    }

    hasInitializedConfirmationRef.current = true;

    if (clientSectionCounts.filled > 0) {
      setConfirmedSharedAnswersSignature(sharedAnswersSignature);
      setConfirmedClientAnswersSignature(clientAnswersSignature);
    }

    if (attorneyCounts.filled > 0) {
      setConfirmedAttorneyAnswersSignature(attorneyAnswersSignature);
    }
  }, [
    attorneyAnswersSignature,
    attorneyCounts.filled,
    clientAnswersSignature,
    clientSectionCounts.filled,
    formLoadError,
    loadingFormDetails,
    loadingShared,
    sharedAnswersSignature,
    sharedLoadError,
  ]);

  useEffect(() => {
    return () => {
      clearAutosaveTimer();
      autosaveRequestIdRef.current += 1;
    };
  }, []);

  useEffect(() => {
    if (loadingShared || loadingFormDetails || sharedLoadError || formLoadError) {
      return;
    }

    const scope: QuestionnaireSaveScope = step === "client_questions" ? "client" : "all";
    const signatures = getCurrentSignatures();
    const isCurrentScopeSaved =
      signatures.shared === savedSharedAnswersSignature &&
      signatures.client === savedClientAnswersSignature &&
      (scope === "client" || signatures.attorney === savedAttorneyAnswersSignature);

    if (isCurrentScopeSaved) {
      return;
    }

    clearAutosaveTimer();
    setAutosaveStatus("saving");

    autosaveTimerRef.current = window.setTimeout(() => {
      const requestId = ++autosaveRequestIdRef.current;
      const payload = buildPayloadForScope(scope);

      void saveQuestionnaireAnswers(caseId, payload)
        .then(() => {
          if (requestId !== autosaveRequestIdRef.current) {
            return;
          }

          markScopeAsSaved(scope, signatures);
          setAutosaveStatus("saved");
        })
        .catch(() => {
          if (requestId !== autosaveRequestIdRef.current) {
            return;
          }

          setAutosaveStatus("error");
        });
    }, AUTOSAVE_DEBOUNCE_MS);

    return () => {
      clearAutosaveTimer();
    };
  }, [
    allFormsAttorneyPages,
    allFormsClientPlan,
    attorneyAnswersSignature,
    caseId,
    clientAnswersSignature,
    formAnswers,
    formLoadError,
    formTypes,
    loadingFormDetails,
    loadingShared,
    savedAttorneyAnswersSignature,
    savedClientAnswersSignature,
    savedSharedAnswersSignature,
    sharedAnswers,
    sharedAnswersSignature,
    sharedLoadError,
    sharedPages,
    step,
  ]);

  useEffect(() => {
    if (!activeJobId) {
      setJob(null);
      setLoadingJobDetails(false);
      setJobDetailsError(null);
      setPreviewLoadError(null);
      setPdfPreviewUrl(null);
      return;
    }

    let cancelled = false;
    setLoadingJobDetails(true);
    setJob(null);
    setJobDetailsError(null);
    setPreviewLoadError(null);

    void getFormFillingJobStatus(activeJobId)
      .then((data) => {
        if (cancelled) {
          return;
        }
        setJob(data);
        syncJobInList(data);
      })
      .catch(() => {
        if (!cancelled) {
          setJob(null);
          setJobDetailsError("The selected form details could not be loaded.");
          toast.error("Form details could not be loaded");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoadingJobDetails(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [activeJobId, syncJobInList]);

  useEffect(() => {
    if (!activeJobId || !job || !["queued", "running"].includes(job.status)) {
      return;
    }

    let cancelled = false;
    const intervalId = window.setInterval(() => {
      void getFormFillingJobStatus(activeJobId)
        .then((data) => {
          if (cancelled) {
            return;
          }
          setJob(data);
          syncJobInList(data);
        })
        .catch(() => {
          // Keep the polling loop alive; the manual refresh action still surfaces errors explicitly.
        });
    }, 3000);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [activeJobId, job, syncJobInList]);

  useEffect(() => {
    if (!job || job.status !== "completed" || !job.filled_pdf_path) {
      return;
    }

    if (completedJobsSeenRef.current.has(job.id)) {
      return;
    }

    completedJobsSeenRef.current.add(job.id);
    onPagesUpdated?.();
  }, [job, onPagesUpdated]);

  useEffect(() => {
    let currentUrl: string | null = null;
    let cancelled = false;

    if (job?.status === "completed" && job.filled_pdf_path) {
      setLoadingPdfPreview(true);
      setPreviewLoadError(null);
      setPdfPreviewUrl(null);
      void getFilledPdfBlobUrl(job.id, getJobPdfCacheKey(job))
        .then((nextUrl) => {
          if (cancelled) {
            URL.revokeObjectURL(nextUrl);
            return;
          }
          setPdfPreviewUrl(nextUrl);
          currentUrl = nextUrl;
        })
        .catch(() => {
          if (!cancelled) {
            setPdfPreviewUrl(null);
            setPreviewLoadError("The PDF preview could not be loaded.");
          }
        })
        .finally(() => {
          if (!cancelled) {
            setLoadingPdfPreview(false);
          }
        });
    } else {
      setPreviewLoadError(null);
      setLoadingPdfPreview(false);
      setPdfPreviewUrl(null);
    }

    return () => {
      cancelled = true;
      if (currentUrl) {
        URL.revokeObjectURL(currentUrl);
      }
    };
  }, [job?.completed_at, job?.filled_pdf_path, job?.id, job?.status, job?.updated_at, previewRetryCount]);

  const updateScalarAnswer = (
    setter: AnswerSetter,
    questionId: string,
    value: string
  ) => {
    setter((prev) => ({
      ...prev,
      [questionId]: value,
    }));
  };

  const updateGroupAnswer = (
    setter: AnswerSetter,
    questionId: string,
    fields: QuestionnaireField[],
    fieldId: string,
    value: string
  ) => {
    setter((prev) => {
      const next = normalizeGroupValue(prev[questionId], fields);
      next[fieldId] = value;
      return {
        ...prev,
        [questionId]: next,
      };
    });
  };

  const updateRepeatableGroupAnswer = (
    setter: AnswerSetter,
    item: QuestionnaireItem,
    rowIndex: number,
    fieldId: string,
    value: string
  ) => {
    setter((prev) => {
      const fields = item.fields ?? [];
      const rows = normalizeRepeatableGroupValue(prev[item.id], fields);
      while (rows.length <= rowIndex) {
        rows.push(createEmptyGroupValue(fields));
      }
      rows[rowIndex][fieldId] = value;
      return {
        ...prev,
        [item.id]: rows,
      };
    });
  };

  const updateRepeatableDetailAnswer = (
    setter: AnswerSetter,
    detailKey: string,
    rowIndex: number,
    value: string
  ) => {
    setter((prev) => {
      const nextValues = Array.isArray(prev[detailKey])
        ? prev[detailKey].map((entry) => toText(entry))
        : [];
      while (nextValues.length <= rowIndex) {
        nextValues.push("");
      }
      nextValues[rowIndex] = value;
      return {
        ...prev,
        [detailKey]: nextValues,
      };
    });
  };

  const addRepeatableRow = (
    setter: AnswerSetter,
    answers: QuestionnaireAnswerMap,
    item: QuestionnaireItem
  ) => {
    if (item.visible_slots?.length) {
      return;
    }

    setter((prev) => {
      if (item.fields?.length && isRepeatableItem(item)) {
        const rows = normalizeRepeatableGroupValue(prev[item.id], item.fields);
        return {
          ...prev,
          [item.id]: [...rows, createEmptyGroupValue(item.fields)],
        };
      }

      const repeatableDetails = (item.details_fields ?? []).filter((field) => field.repeatable);
      if (repeatableDetails.length === 0) {
        return prev;
      }

      const next = { ...prev };
      const rowCount = getRepeatableRowCount(item, answers);
      for (const field of repeatableDetails) {
        const detailKey = `${item.id}.${field.id}`;
        const values = Array.isArray(prev[detailKey])
          ? prev[detailKey].map((entry) => toText(entry))
          : [];
        while (values.length < rowCount) {
          values.push("");
        }
        values.push("");
        next[detailKey] = values;
      }
      return next;
    });
  };

  const removeRepeatableRow = (
    setter: AnswerSetter,
    answers: QuestionnaireAnswerMap,
    item: QuestionnaireItem
  ) => {
    if (item.visible_slots?.length || getRepeatableRowCount(item, answers) <= 1) {
      return;
    }

    setter((prev) => {
      if (item.fields?.length && isRepeatableItem(item)) {
        const rows = normalizeRepeatableGroupValue(prev[item.id], item.fields).slice(0, -1);
        return {
          ...prev,
          [item.id]: rows,
        };
      }

      const repeatableDetails = (item.details_fields ?? []).filter((field) => field.repeatable);
      if (repeatableDetails.length === 0) {
        return prev;
      }

      const next = { ...prev };
      for (const field of repeatableDetails) {
        const detailKey = `${item.id}.${field.id}`;
        const values = Array.isArray(prev[detailKey])
          ? prev[detailKey].map((entry) => toText(entry)).slice(0, -1)
          : [];
        next[detailKey] = values;
      }
      return next;
    });
  };

  const handleSaveClientQuestions = async () => {
    if (missingClientRequiredFields.length > 0) {
      toast.error(
        firstMissingClientRequiredField
          ? `${getClientPendingFieldsLead(missingClientRequiredFields)} ${formatPendingFieldLabel(firstMissingClientRequiredField)}`
          : getClientPendingFieldsLead(missingClientRequiredFields)
      );
      if (firstMissingClientRequiredField?.inputId) {
        const el = document.getElementById(firstMissingClientRequiredField.inputId);
        if (el) {
          el.focus();
          el.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      }
      return;
    }

    setSavingClientQuestions(true);
    clearAutosaveTimer();
    autosaveRequestIdRef.current += 1;
    const toastId = toast.loading("Confirming client answers...");

    try {
      const prepared = preparePersistedAnswerState(
        sharedAnswersRef.current,
        formAnswersRef.current
      );
      sharedAnswersRef.current = prepared.sharedAnswers;
      formAnswersRef.current = prepared.formAnswers;
      setSharedAnswers(prepared.sharedAnswers);
      setFormAnswers(prepared.formAnswers);
      await saveQuestionnaireAnswers(
        caseId,
        buildPayloadForAnswers("client", prepared.sharedAnswers, prepared.formAnswers)
      );
      markScopeAsSaved("client", prepared.signatures);
      markScopeAsConfirmed("client", prepared.signatures);
      setAutosaveStatus("saved");
      toast.success("Client answers confirmed", { id: toastId });
      setStep("attorney_questions");
    } catch {
      setAutosaveStatus("error");
      toast.error("Client answers could not be confirmed", { id: toastId });
    } finally {
      setSavingClientQuestions(false);
    }
  };

  const handleAutofillSharedQuestions = async (): Promise<boolean> => {
    setAutofillingSharedQuestions(true);
    setAutofillProgress(0);
    setAutofillPhaseMessage("Preparando documentos...");
    const currentSharedAnswers = sharedAnswersRef.current;
    let nextFormAnswers = formAnswersRef.current;

    const postOcrPhases = [
      { delay: 0,      pct: 52, msg: "Preparando busqueda en documentos..." },
      { delay: 8000,   pct: 58, msg: "Buscando informacion relevante..." },
      { delay: 20000,  pct: 65, msg: "Completando respuestas..." },
      { delay: 50000,  pct: 78, msg: "Procesando formularios..." },
      { delay: 120000, pct: 90, msg: "Revisando respuestas sugeridas..." },
      { delay: 180000, pct: 95, msg: "Finalizando analisis..." },
    ];
    const defaultPhases = [
      { delay: 0,      pct: 5,  msg: "Preparando documentos..." },
      { delay: 3000,   pct: 15, msg: "Leyendo documentos..." },
      { delay: 8000,   pct: 30, msg: "Preparando busqueda en documentos..." },
      { delay: 20000,  pct: 50, msg: "Buscando informacion relevante..." },
      { delay: 40000,  pct: 65, msg: "Completando respuestas..." },
      { delay: 70000,  pct: 78, msg: "Procesando formularios..." },
      { delay: 120000, pct: 90, msg: "Revisando respuestas sugeridas..." },
      { delay: 180000, pct: 95, msg: "Finalizando analisis..." },
    ];
    let timers = defaultPhases.map(({ delay, pct, msg }) =>
      setTimeout(() => {
        setAutofillPhaseMessage(msg);
        setAutofillProgress(pct);
      }, delay)
    );

    try {
      const result = await autofillSharedQuestionnaireAnswers(caseId, {
        onOcrProgress: (msg, pct) => {
          timers.forEach(clearTimeout);
          setAutofillPhaseMessage(msg);
          setAutofillProgress(Math.round(pct));
        },
        onOcrComplete: () => {
          timers.forEach(clearTimeout);
          timers = postOcrPhases.map(({ delay, pct, msg }) =>
            setTimeout(() => {
              setAutofillPhaseMessage(msg);
              setAutofillProgress(pct);
            }, delay)
          );
        },
      });
      setAutofillProgress(100);
      setAutofillPhaseMessage("Completado");
      setVerificationMap(mergeVerificationMaps(result.verification_map, result.form_verification_map));

      const sharedMerge = mergeAutofillAnswers(currentSharedAnswers, result.answers);
      const nextSharedAnswers = clearDuplicateSafeAddress(sharedMerge.answers);

      const forcedShared = result.forced_answers || {};
      for (const [key, value] of Object.entries(forcedShared)) {
        nextSharedAnswers[key] = value;
      }

      sharedAnswersRef.current = nextSharedAnswers;
      setSharedAnswers(nextSharedAnswers);

      let formApplied = 0;
      const formAnswersMap = result.form_answers || {};
      if (Object.keys(formAnswersMap).length > 0) {
        const allFormSuggested: QuestionnaireAnswerMap = {};
        for (const ftAnswers of Object.values(formAnswersMap)) {
          Object.assign(allFormSuggested, ftAnswers);
        }
        const formMerge = mergeAutofillAnswers(nextFormAnswers, allFormSuggested);
        formApplied = formMerge.appliedCount;
        nextFormAnswers = formMerge.answers;
      }

      const forcedFormMap = result.forced_form_answers || {};
      for (const ftForced of Object.values(forcedFormMap)) {
        for (const [key, value] of Object.entries(ftForced)) {
          nextFormAnswers[key] = value;
        }
      }
      const leaUnitNumberCleanup = clearLeaUnitAutofill(nextFormAnswers);
      nextFormAnswers = leaUnitNumberCleanup.answers;

      const hasForcedAnswers =
        Object.keys(forcedShared).length > 0 ||
        Object.values(forcedFormMap).some((m) => Object.keys(m).length > 0);

      if (formApplied > 0 || leaUnitNumberCleanup.cleared || hasForcedAnswers) {
        formAnswersRef.current = nextFormAnswers;
        setFormAnswers(nextFormAnswers);
      }

      const appliedCount = sharedMerge.appliedCount + formApplied;
      if (appliedCount > 0 || leaUnitNumberCleanup.cleared || hasForcedAnswers) {
        try {
          await persistAutofillAnswers("client", nextSharedAnswers, nextFormAnswers);
        } catch {
          setAutosaveStatus("error");
          toast.error(
            "The OCR results were applied, but they could not be saved automatically. Review and confirm them before reloading."
          );
        }
      }
      const skipped = result.skipped_low_confidence || 0;

      if (appliedCount > 0) {
        const parts = [`${appliedCount} fields were completed with OCR (medium/high confidence).`];
        if (leaUnitNumberCleanup.cleared) {
          parts.push("Part 3.5 Number was cleared because it must be entered manually.");
        }
        if (skipped > 0) {
          parts.push(`${skipped} were skipped due to low confidence.`);
        }
        parts.push("Review the information before confirming it.");
        toast.success(parts.join(" "));
      } else if (leaUnitNumberCleanup.cleared) {
        const parts = [
          "Part 3.5 Number was cleared because it must be entered manually.",
        ];
        if (skipped > 0) {
          parts.push(`${skipped} were skipped due to low confidence.`);
        }
        toast.success(parts.join(" "));
      } else if (result.suggested_count > 0) {
        toast.success("The OCR-suggested fields were already complete.");
      } else {
        const msg = skipped > 0
          ? `No data with sufficient confidence was found (${skipped} skipped).`
          : "No clear data was found for automatic completion.";
        toast(msg);
      }
      return true;
    } catch (error: unknown) {
      timers.forEach(clearTimeout);
      toast.error(
        getApiErrorMessage(error, "Client data could not be extracted with OCR")
      );
      return false;
    } finally {
      setAutofillingSharedQuestions(false);
      setAutofillProgress(0);
      setAutofillPhaseMessage("");
    }
  };

  const handleAutofillAttorneyQuestions = async (): Promise<boolean> => {
    setAutofillingAttorneyQuestions(true);
    setAttorneyAutofillProgress(0);
    setAttorneyAutofillPhaseMessage("Preparando documentos...");
    let nextFormAnswers = formAnswersRef.current;

    const attPostOcrPhases = [
      { delay: 0,      pct: 52, msg: "Preparando busqueda en documentos..." },
      { delay: 8000,   pct: 58, msg: "Buscando informacion relevante..." },
      { delay: 20000,  pct: 65, msg: "Completando respuestas..." },
      { delay: 50000,  pct: 78, msg: "Procesando preguntas del abogado..." },
      { delay: 120000, pct: 90, msg: "Revisando respuestas sugeridas..." },
      { delay: 180000, pct: 95, msg: "Finalizando analisis..." },
    ];
    const attDefaultPhases = [
      { delay: 0,      pct: 5,  msg: "Preparando documentos..." },
      { delay: 3000,   pct: 15, msg: "Leyendo documentos..." },
      { delay: 8000,   pct: 30, msg: "Preparando busqueda en documentos..." },
      { delay: 20000,  pct: 50, msg: "Buscando informacion relevante..." },
      { delay: 40000,  pct: 65, msg: "Completando respuestas..." },
      { delay: 70000,  pct: 78, msg: "Procesando preguntas del abogado..." },
      { delay: 120000, pct: 90, msg: "Revisando respuestas sugeridas..." },
      { delay: 180000, pct: 95, msg: "Finalizando analisis..." },
    ];
    let timers = attDefaultPhases.map(({ delay, pct, msg }) =>
      setTimeout(() => {
        setAttorneyAutofillPhaseMessage(msg);
        setAttorneyAutofillProgress(pct);
      }, delay)
    );

    try {
      const result = await autofillAttorneyAnswers(caseId, {
        onOcrProgress: (msg, pct) => {
          timers.forEach(clearTimeout);
          setAttorneyAutofillPhaseMessage(msg);
          setAttorneyAutofillProgress(Math.round(pct));
        },
        onOcrComplete: () => {
          timers.forEach(clearTimeout);
          timers = attPostOcrPhases.map(({ delay, pct, msg }) =>
            setTimeout(() => {
              setAttorneyAutofillPhaseMessage(msg);
              setAttorneyAutofillProgress(pct);
            }, delay)
          );
        },
      });
      setAttorneyAutofillProgress(100);
      setAttorneyAutofillPhaseMessage("Completado");
      const nextVerificationMap = mergeVerificationMaps(
        result.verification_map,
        result.form_verification_map
      );
      setVerificationMap((prev) => ({ ...prev, ...nextVerificationMap }));

      const formAnswersMap = result.form_answers || {};
      let formApplied = 0;
      if (Object.keys(formAnswersMap).length > 0) {
        const allFormSuggested: QuestionnaireAnswerMap = {};
        for (const ftAnswers of Object.values(formAnswersMap)) {
          Object.assign(allFormSuggested, ftAnswers);
        }
        const formMerge = mergeAutofillAnswers(nextFormAnswers, allFormSuggested);
        formApplied = formMerge.appliedCount;
        nextFormAnswers = formMerge.answers;
      }

      const directAnswers = result.answers || {};
      let directApplied = 0;
      if (Object.keys(directAnswers).length > 0) {
        const directMerge = mergeAutofillAnswers(nextFormAnswers, directAnswers);
        directApplied = directMerge.appliedCount;
        if (directApplied > 0 || formApplied > 0) {
          nextFormAnswers = directMerge.answers;
        }
      }

      const appliedCount = formApplied + directApplied;
      if (appliedCount > 0) {
        formAnswersRef.current = nextFormAnswers;
        setFormAnswers(nextFormAnswers);
        try {
          await persistAutofillAnswers("all", sharedAnswersRef.current, nextFormAnswers);
        } catch {
          setAutosaveStatus("error");
          toast.error(
            "The OCR results were applied, but they could not be saved automatically. Review and confirm them before reloading."
          );
        }
      }
      const skipped = result.skipped_low_confidence || 0;

      if (appliedCount > 0) {
        const parts = [`${appliedCount} attorney fields were completed with OCR (medium/high confidence).`];
        if (skipped > 0) {
          parts.push(`${skipped} were skipped due to low confidence.`);
        }
        parts.push("Review the information before confirming it.");
        toast.success(parts.join(" "));
      } else if (result.suggested_count > 0) {
        toast.success("The OCR-suggested attorney fields were already complete.");
      } else {
        const msg = skipped > 0
          ? `No attorney data with sufficient confidence was found (${skipped} skipped).`
          : "No clear data was found for automatic attorney completion.";
        toast(msg);
      }
      return true;
    } catch (error: unknown) {
      timers.forEach(clearTimeout);
      toast.error(
        getApiErrorMessage(error, "Attorney data could not be extracted with OCR")
      );
      return false;
    } finally {
      setAutofillingAttorneyQuestions(false);
      setAttorneyAutofillProgress(0);
      setAttorneyAutofillPhaseMessage("");
    }
  };

  const handleAutofillAllQuestions = async () => {
    if (autofillingFormQuestions) {
      return;
    }

    setAutofillingFormQuestions(true);
    try {
      const clientSucceeded = await handleAutofillSharedQuestions();
      if (!clientSucceeded) {
        return;
      }
      await handleAutofillAttorneyQuestions();
    } finally {
      setAutofillingFormQuestions(false);
    }
  };

  const handleSaveAttorneyQuestions = async () => {
    setSavingAttorneyQuestions(true);
    clearAutosaveTimer();
    autosaveRequestIdRef.current += 1;
    const toastId = toast.loading("Confirming answers...");

    try {
      const prepared = preparePersistedAnswerState(
        sharedAnswersRef.current,
        formAnswersRef.current
      );
      sharedAnswersRef.current = prepared.sharedAnswers;
      formAnswersRef.current = prepared.formAnswers;
      setSharedAnswers(prepared.sharedAnswers);
      setFormAnswers(prepared.formAnswers);
      await saveQuestionnaireAnswers(
        caseId,
        buildPayloadForAnswers("all", prepared.sharedAnswers, prepared.formAnswers)
      );
      markScopeAsSaved("all", prepared.signatures);
      markScopeAsConfirmed("all", prepared.signatures);
      setAutosaveStatus("saved");
      if (clientPersonalDataRequiredComplete || hasPreviewHistory) {
        toast.success("Answers confirmed successfully", { id: toastId });
        setStep("preview");
      } else {
        toast.success(
          "Attorney answers were confirmed. Complete and confirm the required client answers to generate a new PDF.",
          { id: toastId }
        );
      }
    } catch {
      setAutosaveStatus("error");
      toast.error("Answers could not be confirmed", { id: toastId });
    } finally {
      setSavingAttorneyQuestions(false);
    }
  };

  const handleGenerate = async (formType: string) => {
    if (!clientStepConfirmed) {
      toast.error(getClientConfirmationBlockMessage(missingClientRequiredFields));
      return;
    }

    setGeneratingFormType(formType);
    clearAutosaveTimer();
    autosaveRequestIdRef.current += 1;
    const toastId = toast.loading("Saving answers and generating PDF...");

    try {
      const prepared = preparePersistedAnswerState(
        sharedAnswersRef.current,
        formAnswersRef.current
      );
      sharedAnswersRef.current = prepared.sharedAnswers;
      formAnswersRef.current = prepared.formAnswers;
      setSharedAnswers(prepared.sharedAnswers);
      setFormAnswers(prepared.formAnswers);
      await saveQuestionnaireAnswers(
        caseId,
        buildPayloadForAnswers("all", prepared.sharedAnswers, prepared.formAnswers)
      );
      markScopeAsSaved("all", prepared.signatures);
      markScopeAsConfirmed("all", prepared.signatures);
      setAutosaveStatus("saved");
      const createdJob = await generateFormFromAnswers(caseId, formType);

      syncJobInList(createdJob);
      setActiveJobId(createdJob.id);
      setJob(createdJob);
      await loadJobs(false, true);

      toast.success("Form generation started.", { id: toastId });
    } catch (error) {
      toast.error(
        getApiErrorMessage(
          error,
          "The PDF could not be generated with the current answers."
        ),
        { id: toastId }
      );
    } finally {
      setGeneratingFormType(null);
    }
  };

  const handleRefreshActiveJob = async () => {
    if (!activeJobId) {
      await loadJobs(false, true);
      return;
    }

    setRefreshingJob(true);
    setJobDetailsError(null);
    setPreviewLoadError(null);
    try {
      const updated = await getFormFillingJobStatus(activeJobId);
      setJob(updated);
      syncJobInList(updated);
      await loadJobs(false, true);
    } catch {
      toast.error("Form status could not be updated");
    } finally {
      setRefreshingJob(false);
    }
  };

  const handleRegenerate = async () => {
    if (!job) {
      return;
    }

    if (!clientStepConfirmed) {
      toast.error(getClientRegenerationBlockMessage(missingClientRequiredFields));
      return;
    }

    setRegeneratingJob(true);
    const toastId = toast.loading("Regenerating PDF...");

    try {
      const updated = await regenerateFilledPdf(job.id, true);
      setJob(updated);
      syncJobInList(updated);
      toast.success("PDF regenerated", { id: toastId });
    } catch (error) {
      toast.error(
        getApiErrorMessage(error, "The PDF could not be regenerated."),
        { id: toastId }
      );
    } finally {
      setRegeneratingJob(false);
    }
  };

  const handleDeleteJob = async (jobId: string, event: MouseEvent) => {
    event.stopPropagation();
    if (!window.confirm("Do you want to remove this form from the history?")) {
      return;
    }

    try {
      await deleteFormFillingJob(jobId);
      const nextJobs = jobs.filter((item) => item.id !== jobId);
      setJobs(nextJobs);
      if (activeJobId === jobId) {
        setActiveJobId(nextJobs[0]?.id ?? null);
      }
      toast.success("Form removed from history");
    } catch {
      toast.error("The form could not be removed");
    }
  };

  const handleEditCurrentForm = () => {
    setStep(clientStepConfirmed ? "attorney_questions" : "client_questions");
  };

  const renderAnswerControl = ({
    id,
    type,
    value,
    onChange,
    options,
    prefix,
    format,
    allowLiteralValues,
    ariaLabel,
    labelledBy,
    describedBy,
    hasError,
    errorId,
  }: {
    id: string;
    type: string;
    value: string;
    onChange: (nextValue: string) => void;
    options?: QuestionnaireOptionInput[];
    prefix?: string;
    format?: string;
    allowLiteralValues?: string[];
    ariaLabel: string;
    labelledBy?: string;
    describedBy?: string;
    hasError?: boolean;
    errorId?: string;
  }) => {
    const combinedDescribedBy = [describedBy, errorId].filter(Boolean).join(" ") || undefined;
    const normalizedType = type.toLowerCase();
    const normalizedOptions = (options ?? []).map((option) => normalizeOption(option));
    const literalOptions = allowLiteralValues ?? [];
    const resolvedSelectOptions =
      normalizedOptions.length > 0
        ? normalizedOptions
        : resolveImplicitSelectOptions(normalizedType, id, ariaLabel);
    const resolvedSelectValue = resolveSelectValue(value, resolvedSelectOptions, id, ariaLabel);
    const selectOptions =
      hasText(resolvedSelectValue) &&
      !resolvedSelectOptions.some((option) => option.value === resolvedSelectValue)
        ? [{ value: resolvedSelectValue, label: resolvedSelectValue }, ...resolvedSelectOptions]
        : resolvedSelectOptions;

    if (normalizedType === "yes_no") {
      return (
        <div className="space-y-3">
          <div
            id={id}
            tabIndex={-1}
            role="radiogroup"
            aria-label={labelledBy ? undefined : ariaLabel}
            aria-labelledby={labelledBy}
            aria-describedby={combinedDescribedBy}
          aria-invalid={hasError ? "true" : undefined}
            className="flex flex-wrap gap-2 outline-none"
          >
            {[
              { label: "Yes", value: "yes" },
              { label: "No", value: "no" },
            ].map((option) => {
              const optionId = `${id}-${option.value}`;
              const selected = value.trim().toLowerCase() === option.value;
              return (
                <label
                  key={optionId}
                  htmlFor={optionId}
                  className={`inline-flex cursor-pointer items-center gap-2 rounded-xl border px-3 py-2 text-sm font-medium transition has-[:focus-visible]:border-brand-500 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand-100 ${
                    selected
                      ? "border-brand-500 bg-brand-50 text-brand-800"
                      : "border-gray-200 bg-white text-gray-700 hover:border-gray-300"
                  }`}
                >
                  <input
                    id={optionId}
                    name={id}
                    type="radio"
                    checked={selected}
                    onChange={() => onChange(option.value)}
                    className="h-4 w-4 border-gray-300 text-brand-600 focus-visible:ring-brand-500"
                  />
                  <span>{option.label}</span>
                </label>
              );
            })}
          </div>
          <button
            type="button"
            onClick={() => onChange("")}
            className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm text-gray-600 hover:border-gray-300"
          >
            Clear
          </button>
        </div>
      );
    }

    if (normalizedType === "checkbox") {
      const checked = ["1", "true", "yes", "y", "on", "checked", "x"].includes(
        value.trim().toLowerCase()
      );
      return (
        <label className="inline-flex items-center gap-3 rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700">
          <input
            id={id}
            name={id}
            type="checkbox"
            checked={checked}
            aria-label={labelledBy ? undefined : ariaLabel}
            aria-labelledby={labelledBy}
            aria-describedby={combinedDescribedBy}
          aria-invalid={hasError ? "true" : undefined}
            onChange={(event) => onChange(event.target.checked ? "yes" : "")}
            className="h-4 w-4 rounded border-gray-300 text-brand-600 focus-visible:ring-brand-500"
          />
          <span>Mark answer</span>
        </label>
      );
    }

    if (
      ["single_choice", "choice", "radio", "button"].includes(normalizedType) &&
      normalizedOptions.length > 0
    ) {
      return (
        <div
          id={id}
          tabIndex={-1}
          role="radiogroup"
          aria-label={labelledBy ? undefined : ariaLabel}
          aria-labelledby={labelledBy}
          aria-describedby={combinedDescribedBy}
          aria-invalid={hasError ? "true" : undefined}
          className="grid gap-2 outline-none"
        >
          {normalizedOptions.map((option) => {
            const optionId = `${id}-${option.value}`;
            const selected = value === option.value;
            return (
              <label
                key={optionId}
                htmlFor={optionId}
                className={`flex cursor-pointer items-start gap-3 rounded-xl border px-3 py-3 text-left text-sm transition has-[:focus-visible]:border-brand-500 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand-100 ${
                  selected
                    ? "border-brand-500 bg-brand-50 text-brand-800"
                    : "border-gray-200 bg-white text-gray-700 hover:border-gray-300"
                }`}
              >
                <input
                  id={optionId}
                  name={id}
                  type="radio"
                  checked={selected}
                  onChange={() => onChange(option.value)}
                  className="mt-0.5 h-4 w-4 shrink-0 border-gray-300 text-brand-600 focus-visible:ring-brand-500"
                />
                <span className="font-medium">{option.label}</span>
              </label>
            );
          })}
          <button
            type="button"
            onClick={() => onChange("")}
            className="justify-self-start rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm text-gray-600 hover:border-gray-300"
          >
            Clear selection
          </button>
        </div>
      );
    }

    if (["select"].includes(normalizedType) && selectOptions.length > 0) {
      return (
        <select
          id={id}
          name={id}
          value={resolvedSelectValue}
          autoComplete="off"
          aria-label={labelledBy ? undefined : ariaLabel}
          aria-labelledby={labelledBy}
          aria-describedby={combinedDescribedBy}
          aria-invalid={hasError ? "true" : undefined}
          onChange={(event) => onChange(event.target.value)}
          className={`w-full rounded-xl border px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 ${hasError ? "border-red-300 bg-red-50 text-red-900 focus-visible:border-red-500 focus-visible:ring-red-200" : "border-gray-200 bg-white text-gray-800 focus-visible:border-brand-500 focus-visible:ring-brand-100"}`}
        >
          <option value="">Select an option</option>
          {selectOptions.map((option) => (
            <option key={`${id}-${option.value}`} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      );
    }

    if (normalizedType === "date") {
      return (
        <DateField
          id={id}
          value={value}
          onChange={onChange}
          hasError={hasError}
          labelledBy={labelledBy}
          ariaLabel={ariaLabel}
          combinedDescribedBy={combinedDescribedBy}
        />
      );
    }

    if (normalizedType === "date_or_text" && literalOptions.length > 0) {
      const literalValue = resolveLiteralValue(value, literalOptions);
      return (
        <div className="space-y-3">
          <DateField
            id={id}
            value={value}
            onChange={onChange}
            hasError={hasError}
            labelledBy={labelledBy}
            ariaLabel={ariaLabel}
            combinedDescribedBy={combinedDescribedBy}
            literalValue={!!literalValue}
          />
          <div className="flex flex-wrap gap-2">
            {literalOptions.map((literalOption) => {
              const selected = literalValue === literalOption;
              return (
                <button
                  key={`${id}-${literalOption}`}
                  type="button"
                  onClick={() => onChange(literalOption)}
                  className={`rounded-xl border px-3 py-2 text-sm font-medium transition ${
                    selected
                      ? "border-brand-500 bg-brand-50 text-brand-800"
                      : "border-gray-200 bg-white text-gray-700 hover:border-gray-300"
                  }`}
                >
                  {literalOption}
                </button>
              );
            })}
            <button
              type="button"
              onClick={() => onChange("")}
              className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm text-gray-600 hover:border-gray-300"
            >
              Clear
            </button>
          </div>
        </div>
      );
    }

    if (["textarea", "table", "note"].includes(normalizedType)) {
      return (
        <textarea
          id={id}
          name={id}
          value={value}
          autoComplete="off"
          aria-label={labelledBy ? undefined : ariaLabel}
          aria-labelledby={labelledBy}
          aria-describedby={combinedDescribedBy}
          aria-invalid={hasError ? "true" : undefined}
          onChange={(event) => onChange(event.target.value)}
          rows={normalizedType === "note" ? 2 : 4}
          placeholder={format || undefined}
          className={`w-full rounded-xl border px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 ${hasError ? "border-red-300 bg-red-50 text-red-900 focus-visible:border-red-500 focus-visible:ring-red-200" : "border-gray-200 bg-white text-gray-800 focus-visible:border-brand-500 focus-visible:ring-brand-100"}`}
        />
      );
    }

    if (normalizedType === "signature") {
      return (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          This field is a signature. Confirm the information here and complete the signature outside the system.
        </div>
      );
    }

    const inputType = normalizedType === "number" ? "number" : "text";
    const placeholder =
      normalizedType === "date" || normalizedType === "date_or_text"
        ? format || LONG_DATE_PLACEHOLDER
        : undefined;

    if (prefix) {
      return (
        <div className={`flex overflow-hidden rounded-xl border ${hasError ? "border-red-300 bg-red-50 has-[:focus-visible]:border-red-500 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-red-200" : "border-gray-200 bg-white has-[:focus-visible]:border-brand-500 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand-100"}`}>
          <span className="flex items-center border-r border-gray-200 bg-gray-50 px-3 text-sm font-medium text-gray-600">
            {prefix}
          </span>
          <input
            id={id}
            name={id}
            type={inputType}
            value={value}
            autoComplete="off"
            aria-label={labelledBy ? undefined : ariaLabel}
            aria-labelledby={labelledBy}
            aria-describedby={combinedDescribedBy}
          aria-invalid={hasError ? "true" : undefined}
            onChange={(event) => onChange(event.target.value)}
            placeholder={placeholder}
            className={`w-full px-3 py-2 text-sm outline-none bg-transparent ${hasError ? "text-red-900" : "text-gray-800"}`}
          />
        </div>
      );
    }

    return (
      <input
        id={id}
        name={id}
        type={inputType}
        value={value}
        autoComplete="off"
        aria-label={labelledBy ? undefined : ariaLabel}
        aria-labelledby={labelledBy}
        aria-describedby={combinedDescribedBy}
          aria-invalid={hasError ? "true" : undefined}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className={`w-full rounded-xl border px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 ${hasError ? "border-red-300 bg-red-50 text-red-900 focus-visible:border-red-500 focus-visible:ring-red-200" : "border-gray-200 bg-white text-gray-800 focus-visible:border-brand-500 focus-visible:ring-brand-100"}`}
      />
    );
  };

  const renderFieldBlock = ({
    id,
    label,
    labelId,
    descriptionId,
    badge,
    optional,
    instruction,
    condition,
    grouped = false,
    control,
    error,
  }: {
    id: string;
    label: string;
    labelId: string;
    descriptionId?: string;
    badge?: ReactNode;
    optional?: boolean;
    instruction?: string;
    condition?: string;
    grouped?: boolean;
    control: ReactNode;
    error?: string;
  }) => (
    <div key={id} className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        {grouped ? (
          <p id={labelId} className="text-sm font-medium text-gray-800">
            {label}
          </p>
        ) : (
          <label htmlFor={id} id={labelId} className="text-sm font-medium text-gray-800">
            {label}
          </label>
        )}
        {badge}
        {optional && (
          <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-medium text-gray-600">
            Optional
          </span>
        )}
      </div>
      {(instruction || condition) && (
        <div id={descriptionId} className="space-y-1 text-xs text-gray-500">
          {instruction && <p>{instruction}</p>}
          {condition && <p>{condition}</p>}
        </div>
      )}
      {control}
      {error && (
        <p className="text-xs font-medium text-red-600" id={`${id}-error`}>
          {error}
        </p>
      )}
    </div>
  );

  const renderQuestionnaireItem = (
    item: QuestionnaireItem,
    answers: QuestionnaireAnswerMap,
    setter: AnswerSetter
  ) => {
    const missingRequiredFields = collectMissingFields(item, answers, sharedAnswers);
    const hasPendingFields = missingRequiredFields.length > 0;
    const hasOnlyReviewFields =
      hasPendingFields && missingRequiredFields.every((field) => field.kind === "review");
    const repeatableRows = getRepeatableRowCount(item, answers);
    const repeatableDetails = (item.details_fields ?? []).filter((field) => field.repeatable);
    const singleDetails = (item.details_fields ?? []).filter((field) => !field.repeatable);
    const itemHeadingId = `${item.id}-heading`;
    const itemDescriptionId =
      item.section || item.instruction || item.condition ? `${item.id}-description` : undefined;
    const itemVerification = getDefaultAwareVerificationEntry(
      verificationMap,
      answers[item.id],
      item.default_value,
      item.id
    );

    return (
      <div
        key={item.id}
        className={`rounded-2xl border bg-white p-4 shadow-sm ${
          hasPendingFields ? "border-amber-300 ring-1 ring-amber-100" : "border-gray-200"
        }`}
      >
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            {item.code && (
              <span
                className={`rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide ${
                  hasPendingFields
                    ? "bg-amber-100 text-amber-900 ring-1 ring-amber-200"
                    : "bg-brand-50 text-brand-800"
                }`}
                title={
                  hasPendingFields
                    ? `Section ${item.code} has pending fields`
                    : undefined
                }
              >
                {item.code}
              </span>
            )}
            {hasPendingFields && (
              <span className="rounded-full bg-amber-50 px-2.5 py-1 text-[10px] font-medium text-amber-800">
                {hasOnlyReviewFields ? "Needs review" : "Pending section"}
              </span>
            )}
            {shouldShowOptionalBadge(item.optional, answers[item.id], item.default_value) && (
              <span className="rounded-full bg-gray-100 px-2.5 py-1 text-[10px] font-medium text-gray-600">
                Optional
              </span>
            )}
            {itemVerification && <VerificationBadge verification={itemVerification} />}
            {item.also_validate_with?.length ? (
              <span className="rounded-full bg-purple-50 px-2.5 py-1 text-[10px] font-medium text-purple-800">
                Validate with {item.also_validate_with.join(", ")}
              </span>
            ) : null}
          </div>
          <h4 id={itemHeadingId} className="text-base font-semibold text-gray-900">
            {item.form_text}
          </h4>
          <div id={itemDescriptionId} className="space-y-1 text-sm text-gray-500">
            {item.section && <p>{item.section}</p>}
            {item.instruction && <p>{item.instruction}</p>}
            {item.condition && <p>{item.condition}</p>}
          </div>
        </div>

        <div className="mt-4 space-y-4">
          {item.fields?.length && !isRepeatableItem(item) && (
            <div className="grid gap-4 md:grid-cols-2">
              {item.fields.map((field) => {
                const groupValue = normalizeGroupValue(answers[item.id], item.fields ?? []);
                const inputId = `${item.id}-${field.id}`;
                const fieldVerification = getDefaultAwareVerificationEntry(
                  verificationMap,
                  groupValue[field.id],
                  field.default_value,
                  `${item.id}.${field.id}`
                );
                const labelId = `${inputId}-label`;
                const descriptionId =
                  field.instruction || field.condition ? `${inputId}-description` : undefined;
                const grouped = isChoiceGroupType(field.type, field.options);
                const hasError = missingRequiredFields.some(m => m.label === field.label && !m.rowLabel);
                const errorId = hasError ? `${inputId}-error` : undefined;
                return renderFieldBlock({
                  error: hasError ? "This field is required" : undefined,
                  id: inputId,
                  label: field.label,
                  labelId,
                  descriptionId,
                  badge: fieldVerification ? (
                    <VerificationBadge verification={fieldVerification} />
                  ) : undefined,
                  optional: shouldShowOptionalBadge(
                    field.optional,
                    groupValue[field.id],
                    field.default_value,
                    field.force_default
                  ),
                  instruction: field.instruction,
                  condition: field.condition,
                  grouped,
                  control: renderAnswerControl({
                    id: inputId,
                    type: field.type,
                    value: groupValue[field.id] ?? "",
                    onChange: (value) =>
                      updateGroupAnswer(
                        setter,
                        item.id,
                        item.fields ?? [],
                        field.id,
                        value
                      ),
                    options: field.options,
                    prefix: field.prefix,
                    format: field.format,
                    allowLiteralValues: field.allow_literal_values,
                    ariaLabel: field.label,
                    labelledBy: labelId,
                    describedBy: descriptionId,
                    hasError,
                    errorId,
                  }),
                });
              })}
            </div>
          )}

          {item.fields?.length && isRepeatableItem(item) && (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                {!item.visible_slots?.length && (
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => addRepeatableRow(setter, answers, item)}
                      className="inline-flex items-center gap-1 rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs font-medium text-gray-700 hover:border-gray-300"
                    >
                      <Plus className="h-3.5 w-3.5" />
                      Add row
                    </button>
                    <button
                      type="button"
                      onClick={() => removeRepeatableRow(setter, answers, item)}
                      disabled={repeatableRows <= 1}
                      title={repeatableRows <= 1 ? "Cannot remove the last row" : undefined}
                      className="inline-flex items-center gap-1 rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs font-medium text-gray-700 hover:border-gray-300 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <Minus className="h-3.5 w-3.5" />
                      Remove row
                    </button>
                  </div>
                )}
              </div>

              <div className="space-y-3">
                {Array.from({ length: repeatableRows }).map((_, rowIndex) => {
                  const fields = item.fields ?? [];
                  const rows = normalizeRepeatableGroupValue(answers[item.id], fields);
                  const row = rows[rowIndex] ?? createEmptyGroupValue(fields);

                  return (
                    <div
                      key={`${item.id}-row-${rowIndex}`}
                      className="rounded-2xl border border-dashed border-gray-200 bg-gray-50 p-4"
                    >
                      <p className="mb-3 text-sm font-semibold text-gray-700">
                        {getRepeatableRowLabel(item, rowIndex)}
                      </p>
                      <div className="grid gap-4 md:grid-cols-2">
                        {fields.map((field) => {
                          const inputId = `${item.id}-${rowIndex}-${field.id}`;
                          const fieldVerification = getDefaultAwareVerificationEntry(
                            verificationMap,
                            row[field.id],
                            field.default_value,
                            ...getRepeatableVerificationKeys(item, rowIndex, field.id)
                          );
                          const labelId = `${inputId}-label`;
                          const descriptionId =
                            field.instruction || field.condition
                              ? `${inputId}-description`
                              : undefined;
                          const grouped = isChoiceGroupType(field.type, field.options);
                          const rowLabel = getRepeatableRowLabel(item, rowIndex);
                          const hasError = missingRequiredFields.some(m => m.label === field.label && m.rowLabel === rowLabel);
                          const errorId = hasError ? `${inputId}-error` : undefined;

                          return renderFieldBlock({
                            error: hasError ? "This field is required" : undefined,
                            id: inputId,
                            label: field.label,
                            labelId,
                            descriptionId,
                            badge: fieldVerification ? (
                              <VerificationBadge verification={fieldVerification} />
                            ) : undefined,
                            optional: shouldShowOptionalBadge(
                              field.optional,
                              row[field.id],
                              field.default_value,
                              field.force_default
                            ),
                            instruction: field.instruction,
                            condition: field.condition,
                            grouped,
                            control: renderAnswerControl({
                              id: inputId,
                              type: field.type,
                              value: row[field.id] ?? "",
                              onChange: (value) =>
                                updateRepeatableGroupAnswer(
                                  setter,
                                  item,
                                  rowIndex,
                                  field.id,
                                  value
                                ),
                              options: field.options,
                              prefix: field.prefix,
                              format: field.format,
                              allowLiteralValues: field.allow_literal_values,
                              ariaLabel: `${field.label} ${rowIndex + 1}`,
                              labelledBy: labelId,
                              describedBy: descriptionId,
                              hasError,
                              errorId,
                            }),
                          });
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {!item.fields?.length && (() => {
            const hasError = missingRequiredFields.some(m => m.label === item.form_text && !m.rowLabel);
            const errorId = hasError ? `${item.id}-error` : undefined;
            return (
              <div className="space-y-2">
                {renderAnswerControl({
                  id: item.id,
                  type: item.type,
                  value: toText(answers[item.id]),
                  onChange: (value) => updateScalarAnswer(setter, item.id, value),
                  options: item.options,
                  prefix: item.prefix,
                  format: item.format,
                  ariaLabel: item.form_text,
                  labelledBy: itemHeadingId,
                  describedBy: itemDescriptionId,
                  hasError,
                  errorId,
                })}
                {hasError && (
                  <p className="text-xs font-medium text-red-600" id={`${item.id}-error`}>
                    This field is required
                  </p>
                )}
              </div>
            );
          })()}

          {(singleDetails.length > 0 || repeatableDetails.length > 0) && (
            <div className="rounded-2xl border border-gray-100 bg-gray-50 p-4">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-gray-800">Additional details</p>
                  <p className="text-xs text-gray-500">
                    Complete the supplementary fields that apply to this answer.
                  </p>
                </div>
                {repeatableDetails.length > 0 && !item.visible_slots?.length && (
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => addRepeatableRow(setter, answers, item)}
                      className="inline-flex items-center gap-1 rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs font-medium text-gray-700 hover:border-gray-300"
                    >
                      <Plus className="h-3.5 w-3.5" />
                      Add row
                    </button>
                    <button
                      type="button"
                      onClick={() => removeRepeatableRow(setter, answers, item)}
                      disabled={repeatableRows <= 1}
                      title={repeatableRows <= 1 ? "Cannot remove the last row" : undefined}
                      className="inline-flex items-center gap-1 rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs font-medium text-gray-700 hover:border-gray-300 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <Minus className="h-3.5 w-3.5" />
                      Remove row
                    </button>
                  </div>
                )}
              </div>

              {singleDetails.length > 0 && (
                <div className="grid gap-4 md:grid-cols-2">
                  {singleDetails.map((field) => {
                    const detailKey = `${item.id}.${field.id}`;
                    const detailVerification = getDefaultAwareVerificationEntry(
                      verificationMap,
                      answers[detailKey],
                      field.default_value,
                      detailKey
                    );
                    const labelId = `${detailKey}-label`;
                    const descriptionId =
                      field.instruction || field.condition ? `${detailKey}-description` : undefined;
                    const grouped = isChoiceGroupType(field.type, field.options);
                    const hasError = missingRequiredFields.some(m => m.label === field.label && !m.rowLabel);
                    const errorId = hasError ? `${detailKey}-error` : undefined;
                    return renderFieldBlock({
                      error: hasError ? "This field is required" : undefined,
                      id: detailKey,
                      label: field.label,
                      labelId,
                      descriptionId,
                      badge: detailVerification ? (
                        <VerificationBadge verification={detailVerification} />
                      ) : undefined,
                      optional: shouldShowOptionalBadge(
                        field.optional,
                        answers[detailKey],
                        field.default_value,
                        field.force_default
                      ),
                      instruction: field.instruction,
                      condition: field.condition,
                      grouped,
                      control: renderAnswerControl({
                        id: detailKey,
                        type: field.type,
                        value: toText(answers[detailKey]),
                        onChange: (value) => updateScalarAnswer(setter, detailKey, value),
                        options: field.options,
                        prefix: field.prefix,
                        format: field.format,
                        allowLiteralValues: field.allow_literal_values,
                        ariaLabel: field.label,
                        labelledBy: labelId,
                        describedBy: descriptionId,
                        hasError,
                        errorId,
                      }),
                    });
                  })}
                </div>
              )}

              {repeatableDetails.length > 0 && (
                <div className="mt-4 space-y-3">
                  {Array.from({ length: repeatableRows }).map((_, rowIndex) => (
                    <div
                      key={`${item.id}-details-${rowIndex}`}
                      className="rounded-2xl border border-dashed border-gray-200 bg-white p-4"
                    >
                      <p className="mb-3 text-sm font-semibold text-gray-700">
                        {getRepeatableRowLabel(item, rowIndex)}
                      </p>
                      <div className="grid gap-4 md:grid-cols-2">
                        {repeatableDetails.map((field) => {
                          const detailKey = `${item.id}.${field.id}`;
                          const detailValues = Array.isArray(answers[detailKey])
                            ? answers[detailKey].map((entry) => toText(entry))
                            : [];
                          const detailVerification = getDefaultAwareVerificationEntry(
                            verificationMap,
                            detailValues[rowIndex] ?? "",
                            field.default_value,
                            detailKey
                          );
                          const inputId = `${detailKey}-${rowIndex}`;
                          const labelId = `${inputId}-label`;
                          const descriptionId =
                            field.instruction || field.condition
                              ? `${inputId}-description`
                              : undefined;
                          const grouped = isChoiceGroupType(field.type, field.options);
                          const rowLabel = getRepeatableRowLabel(item, rowIndex);
                          const hasError = missingRequiredFields.some(m => m.label === field.label && m.rowLabel === rowLabel);
                          const errorId = hasError ? `${inputId}-error` : undefined;
                          return renderFieldBlock({
                            error: hasError ? "This field is required" : undefined,
                            id: inputId,
                            label: field.label,
                            labelId,
                            descriptionId,
                            badge: detailVerification ? (
                              <VerificationBadge verification={detailVerification} />
                            ) : undefined,
                            optional: shouldShowOptionalBadge(
                              field.optional,
                              detailValues[rowIndex] ?? "",
                              field.default_value,
                              field.force_default
                            ),
                            instruction: field.instruction,
                            condition: field.condition,
                            grouped,
                            control: renderAnswerControl({
                              id: inputId,
                              type: field.type,
                              value: detailValues[rowIndex] ?? "",
                              onChange: (value) =>
                                updateRepeatableDetailAnswer(
                                  setter,
                                  detailKey,
                                  rowIndex,
                                  value
                                ),
                              options: field.options,
                              prefix: field.prefix,
                              format: field.format,
                              allowLiteralValues: field.allow_literal_values,
                              ariaLabel: `${field.label} ${rowIndex + 1}`,
                              labelledBy: labelId,
                              describedBy: descriptionId,
                              hasError,
                              errorId,
                            }),
                          });
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    );
  };

  const renderQuestionnairePages = (
    pages: QuestionnairePage[],
    answers: QuestionnaireAnswerMap,
    setter: AnswerSetter,
    emptyMessage: string
  ) => {
    if (pages.length === 0) {
      return (
        <EmptyState
          description={emptyMessage}
          className="min-h-[320px] bg-white"
        />
      );
    }

    return (
      <div className="space-y-6">
        {pages.map((page) => (
          <section
            key={`page-${page.page}`}
            className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm"
          >
            <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-brand-700">
                  Page {page.page}
                </p>
              </div>
            </div>

            <div className="space-y-6">
              {groupItemsBySection(page.items).map(([sectionName, items]) => (
                <div key={`${page.page}-${sectionName}`} className="space-y-4">
                  <div>
                    <h3 className="text-sm font-semibold uppercase tracking-wide text-gray-600">
                      {sectionName}
                    </h3>
                  </div>
                  <div className="space-y-4">
                    {items.map((item) => renderQuestionnaireItem(item, answers, setter))}
                  </div>
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    );
  };

  const stepItems: Array<{
    id: WizardStep;
    label: string;
    description: string;
    statusText: string;
    enabled: boolean;
    tone: "brand" | "success" | "warning" | "neutral" | "danger";
  }> = [
    {
      id: "client_questions",
      label: "Client",
      description: `${clientSectionCounts.filled}/${clientSectionCounts.total || 0} fields`,
      statusText:
        sharedLoadError || formLoadError
          ? "Check error"
          : loadingShared || loadingFormDetails
            ? "Loading..."
            : clientStepConfirmed
              ? clientStepStarted
                ? "Saved"
                : "Pending"
              : step === "client_questions" && autosaveStatus === "saving"
                ? "Saving..."
                : step === "client_questions" && autosaveStatus === "error"
                  ? "Save error"
                  : clientStepAutosaved
                    ? "Unconfirmed"
                    : "Pending",
      enabled: true,
      tone:
        sharedLoadError || formLoadError
          ? "danger"
          : clientStepConfirmed
              ? step === "client_questions"
                ? "brand"
                : "success"
              : step === "client_questions"
                ? "brand"
                : clientStepAutosaved
                  ? "warning"
                  : "neutral",
    },
    {
      id: "attorney_questions",
      label: "Attorney",
      description:
        loadingShared || loadingFormDetails
          ? "Loading questions"
          : sharedLoadError || formLoadError
            ? "Resolve errors to continue"
            : `${attorneyCounts.filled}/${attorneyCounts.total || 0} fields`,
      statusText: sharedLoadError || formLoadError
        ? "Check error"
        : loadingShared || loadingFormDetails
          ? "Loading..."
          : attorneyStepConfirmed
            ? attorneyStepStarted
              ? "Saved"
              : "Pending"
            : canOpenAttorneyStep
              ? step === "attorney_questions" && autosaveStatus === "saving"
                ? "Saving..."
                : step === "attorney_questions" && autosaveStatus === "error"
                  ? "Save error"
                  : attorneyStepAutosaved
                    ? "Unconfirmed"
                    : "Pending"
              : "Locked",
      enabled: step === "attorney_questions" || canOpenAttorneyStep,
      tone: sharedLoadError || formLoadError
        ? "danger"
        : attorneyStepConfirmed && attorneyStepStarted
            ? step === "attorney_questions"
              ? "brand"
              : "success"
            : step === "attorney_questions"
              ? "brand"
              : canOpenAttorneyStep && attorneyStepAutosaved
                ? "warning"
              : "neutral",
    },
    {
      id: "preview",
      label: "Generate & Preview",
      description:
        activeJobId && job
          ? `${job.progress_pct.toFixed(0)}% complete`
          : jobs.length > 0
            ? `${jobs.length} forms in history`
            : canOpenPreviewStep
              ? "Ready to generate"
                : getPreviewStepBlockedMessage(missingClientRequiredFields),
      statusText:
        jobsLoadError || jobDetailsError || previewLoadError
          ? "Check error"
          : loadingJobs || loadingJobDetails || loadingPdfPreview
            ? "Loading..."
            : activeJobId && job
              ? job.status === "completed"
                ? "PDF ready"
                : getJobPhaseLabel(job)
              : canOpenPreviewStep
                ? jobs.length > 0
                  ? "History ready"
                  : "Pending"
                : "Locked",
      enabled: step === "preview" || canOpenPreviewStep,
      tone:
        jobsLoadError || jobDetailsError || previewLoadError
          ? "danger"
          : activeJobId && job?.status === "completed"
            ? "success"
            : step === "preview"
              ? "brand"
              : canOpenPreviewStep
                ? activeJobId && job
                  ? "warning"
                  : "neutral"
                : "neutral",
    },
  ];

  return (
    <div
      className={`flex h-[calc(100vh-40px)] flex-col gap-5 ${
        step === "preview" ? "min-h-[1280px]" : "min-h-[1080px]"
      }`}
    >
      <GlassSurface filterId="forms-wizard-header" className="rounded-3xl p-5">
        <div className="flex flex-col gap-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">
              Form generation
            </h2>
            <p className="mt-1 text-sm text-gray-600">
              Complete shared data, review one form at a time, and generate the PDF from saved answers.
            </p>
          </div>

          <nav aria-label="Wizard progress" className="relative">
            <div className="absolute left-0 top-1/2 hidden h-0.5 w-full -translate-y-1/2 bg-gray-200 md:block" />
            <ol className="relative grid gap-3 md:grid-cols-3">
              {stepItems.map((item, index) => {
                const isCurrent = item.id === step;
                const badgeContent =
                  item.tone === "success" && !isCurrent ? (
                    <CheckCircle2 aria-hidden="true" className="h-5 w-5" />
                  ) : item.tone === "danger" ? (
                    <AlertCircle aria-hidden="true" className="h-5 w-5" />
                  ) : (
                    index + 1
                  );
                const shellClass = isCurrent
                  ? "border-brand-500 bg-brand-50 shadow-sm"
                  : item.tone === "success"
                    ? "border-green-200 bg-green-50"
                    : item.tone === "warning"
                      ? "border-amber-200 bg-amber-50"
                      : item.tone === "danger"
                        ? "border-red-200 bg-red-50"
                        : "border-gray-200 bg-white hover:border-gray-300";
                const badgeClass = isCurrent
                  ? "bg-brand-600 text-white shadow-md shadow-brand-200"
                  : item.tone === "success"
                    ? "bg-green-600 text-white shadow-md shadow-green-200"
                    : item.tone === "warning"
                      ? "bg-amber-500 text-white shadow-md shadow-amber-200"
                      : item.tone === "danger"
                        ? "bg-red-600 text-white shadow-md shadow-red-200"
                        : "bg-gray-100 text-gray-500";
                const statusClass = isCurrent
                  ? "bg-brand-100 text-brand-800"
                  : item.tone === "success"
                    ? "bg-green-100 text-green-800"
                    : item.tone === "warning"
                      ? "bg-amber-100 text-amber-900"
                      : item.tone === "danger"
                        ? "bg-red-100 text-red-800"
                        : "bg-gray-100 text-gray-700";
                const textClass = isCurrent
                  ? "text-brand-900"
                  : item.tone === "success"
                    ? "text-green-900"
                    : item.tone === "danger"
                      ? "text-red-900"
                      : "text-gray-900";

                return (
                  <li key={item.id}>
                    <button
                      type="button"
                      disabled={!item.enabled}
                      title={!item.enabled ? "Complete previous steps first" : undefined}
                      aria-current={isCurrent ? "step" : undefined}
                      aria-controls={`wizard-panel-${item.id}`}
                      onClick={() => item.enabled && setStep(item.id)}
                      className={`relative flex w-full flex-col items-center gap-3 rounded-2xl border px-4 py-3 text-center transition md:flex-row md:items-start md:text-left ${shellClass} disabled:cursor-not-allowed disabled:opacity-50`}
                    >
                      <span
                        className={`relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold transition-colors ${badgeClass}`}
                      >
                        {badgeContent}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center justify-center gap-2 md:justify-between">
                          <p className={`truncate text-sm font-semibold ${textClass}`}>
                            {item.label}
                          </p>
                          <span
                            className={`rounded-full px-2 py-1 text-[10px] font-semibold uppercase tracking-wide ${statusClass}`}
                          >
                            {item.statusText}
                          </span>
                        </div>
                        <p
                          id={`step-description-${item.id}`}
                          className={`mt-1 truncate text-xs ${
                            isCurrent
                              ? "text-brand-600"
                              : item.tone === "success"
                                ? "text-green-700"
                                : item.tone === "danger"
                                  ? "text-red-700"
                                  : "text-gray-500"
                          }`}
                        >
                          {item.description}
                        </p>
                      </div>
                    </button>
                  </li>
                );
              })}
            </ol>
          </nav>
        </div>
      </GlassSurface>

      <CaseDocumentScopePicker
        title="Form Documents"
        description="Select which case documents OCR autofill can use to complete questions and forms."
        documents={formScopeDocuments}
        selectedIds={selectedFormSourceDocumentIds}
        saving={savingDocumentScope}
        collapsible
        defaultCollapsed
        listMaxHeightClassName="max-h-40"
        onChange={handleFormScopeChange}
      />

      <GlassSurface
        filterId="forms-wizard-content"
        className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-3xl"
        contentClassName="relative z-10 flex flex-col h-full min-h-0"
      >
        {showUnifiedAutofillControl && (
          <div className="shrink-0 border-b border-gray-100 bg-white/80 px-5 py-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div role="status" aria-live="polite" className="min-w-0">
                {autofillingFormQuestions ? (
                  <div className="flex flex-col gap-1">
                    <span className="text-sm font-medium text-purple-600">
                      {activeFormAutofillPhaseMessage || "Procesando preguntas..."}
                    </span>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-gray-400">{activeFormAutofillProgress}%</span>
                      <div className="h-1.5 w-28 overflow-hidden rounded-full bg-purple-100">
                        <div
                          className="h-full rounded-full bg-gradient-to-r from-purple-500 to-blue-500 transition-[width]"
                          style={{ width: `${activeFormAutofillProgress}%` }}
                        />
                      </div>
                    </div>
                  </div>
                ) : (
                  <>
                    <p className="text-sm font-medium text-gray-900">
                      AI Autofill
                    </p>
                    <p className="text-xs text-gray-500">
                      Completa ambas secciones con una sola ejecución usando los
                      documentos seleccionados.
                    </p>
                  </>
                )}
              </div>
              <button
                type="button"
                onClick={handleAutofillAllQuestions}
                disabled={
                  loadingShared ||
                  loadingFormDetails ||
                  autofillingFormQuestions ||
                  !canRunFormAutofill
                }
                title={autofillingFormQuestions ? "Autofill in progress" : !canRunFormAutofill ? "Cannot run autofill at this time" : undefined}
                aria-busy={autofillingFormQuestions}
                className="group/ai relative inline-flex shrink-0 items-center gap-2 overflow-hidden rounded-xl border border-gray-700 bg-[#0B0F19] px-3 py-1.5 text-xs font-bold text-white shadow-lg transition-[background-color,border-color,color,box-shadow,opacity] hover:border-purple-500/50 hover:shadow-purple-500/25 disabled:opacity-50"
              >
                <div className="absolute inset-0 bg-gradient-to-r from-transparent via-purple-500/20 to-transparent translate-x-[-100%] group-hover/ai:animate-[shimmer_1.5s_infinite]" />
                {autofillingFormQuestions ? (
                  <Loader2 className="relative z-10 h-4 w-4 animate-spin text-purple-400" />
                ) : (
                  <AnimatedAIBot className="relative z-10 h-4 w-4 text-purple-400" />
                )}
                <span className="relative z-10 tracking-wide text-transparent bg-clip-text bg-gradient-to-r from-purple-400 to-blue-400">
                  {autofillingFormQuestions ? "ANALIZANDO..." : "AI AUTOFILL"}
                </span>
              </button>
            </div>
          </div>
        )}

        {step === "client_questions" && (
          <>
            <div
              id="wizard-panel-client_questions"
              className="shrink-0 border-b border-gray-100 bg-white/70 px-5 py-4"
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 className="text-base font-semibold text-gray-900">
                    Client details
                  </h3>
                </div>
                <div className="shrink-0 min-w-[150px]">
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-gray-400">
                      {clientSectionCounts.filled}/{clientSectionCounts.total || 0} fields
                    </span>
                    <div className="w-20 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-green-500 rounded-full transition-[width]"
                        style={{
                          width: `${clientSectionCounts.total > 0 ? Math.round((clientSectionCounts.filled / clientSectionCounts.total) * 100) : 0}%`
                        }}
                      />
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div className={`min-h-0 flex-1 overflow-y-auto bg-gray-50 p-5 custom-scroll relative${autofillingFormQuestions ? " select-none" : ""}`}>
              {autofillingFormQuestions && (
                <div className="pointer-events-auto absolute inset-0 z-20 bg-white/40" aria-hidden="true" />
              )}
              <div className={`space-y-8${autofillingFormQuestions ? " pointer-events-none opacity-60" : ""}`}>
                <section className="space-y-4">
                  

                  {sharedLoadError ? (
                    <EmptyState
                      icon={AlertCircle}
                      title="Shared questions could not be loaded."
                      description="Retry the load before continuing to avoid working with an incomplete state."
                      tone="danger"
                      role="alert"
                      className="min-h-[220px] bg-white"
                      action={
                        <button
                          type="button"
                          onClick={() => void loadSharedStep()}
                          className="inline-flex items-center gap-2 rounded-xl border border-red-200 bg-white px-4 py-2 text-sm font-medium text-red-700 hover:border-red-300 hover:bg-red-50"
                        >
                          <RefreshCw aria-hidden="true" className="h-4 w-4" />
                          Retry
                        </button>
                      }
                    />
                  ) : loadingShared ? (
                    <div
                      className="animate-pulse space-y-4 rounded-3xl border border-gray-200 bg-white p-5 shadow-sm"
                      role="status"
                      aria-live="polite"
                      aria-busy="true"
                    >
                      <span className="sr-only">Loading shared questions...</span>
                      <div className="h-4 w-1/4 rounded bg-gray-200"></div>
                      <div className="space-y-3">
                        <div className="h-10 rounded-2xl bg-gray-100"></div>
                        <div className="h-10 rounded-2xl bg-gray-100"></div>
                        <div className="h-10 rounded-2xl bg-gray-100"></div>
                      </div>
                    </div>
                  ) : (
                    renderQuestionnairePages(
                      sharedPages,
                      sharedAnswers,
                      setSharedAnswers,
                      "No shared questions are configured."
                    )
                  )}
                </section>

                <section className="space-y-4">
                  <div className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <h4 className="mt-1 text-base font-semibold text-gray-900">
                          Questions by form
                        </h4>
                        <p className="mt-1 text-sm text-gray-500">
                          Switch between forms to review only the relevant information at each moment.
                        </p>
                      </div>
                      {activeClientCounts && (
                        <div className="rounded-2xl bg-gray-50 px-3 py-2 text-sm text-gray-600">
                          {activeClientCounts.filled}/{activeClientCounts.total || 0} fields
                        </div>
                      )}
                    </div>

                    {clientFormsWithQuestions.length > 0 ? (
                      <div
                        role="tablist"
                        aria-label="Select client form"
                        className="mt-4 flex flex-wrap gap-2"
                      >
                        {clientFormsWithQuestions.map((form) => {
                          const isSelected = form.form_type === activeClientForm?.form_type;
                          const counts = clientFormCounts[form.form_type] ?? {
                            filled: 0,
                            total: 0,
                          };

                          return (
                            <button
                              key={`client-tab-${form.form_type}`}
                              id={`client-form-tab-${form.form_type}`}
                              role="tab"
                              type="button"
                              aria-selected={isSelected}
                              aria-controls={`client-form-panel-${form.form_type}`}
                              onClick={() => setActiveClientFormType(form.form_type)}
                              className={`inline-flex items-center gap-2 rounded-2xl border px-4 py-2 text-sm font-medium transition ${
                                isSelected
                                  ? "border-brand-500 bg-brand-50 text-brand-800"
                                  : "border-gray-200 bg-white text-gray-700 hover:border-gray-300"
                              }`}
                            >
                              <span>{form.label}</span>
                              <span
                                className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                                  isSelected
                                    ? "bg-brand-100 text-brand-800"
                                    : "bg-gray-100 text-gray-700"
                                }`}
                              >
                                {counts.filled}/{counts.total || 0}
                              </span>
                            </button>
                          );
                        })}
                      </div>
                    ) : (
                      <p className="mt-4 text-sm text-gray-500">
                        There are no client questions for the available forms.
                      </p>
                    )}
                  </div>

                  {formLoadError ? (
                    <EmptyState
                      icon={AlertCircle}
                      title="Form questions could not be loaded."
                      description="Retry before continuing to avoid working with incomplete forms."
                      tone="danger"
                      role="alert"
                      className="min-h-[220px] bg-white"
                      action={
                        <button
                          type="button"
                          onClick={() => void loadFormTypesAndQuestions()}
                          className="inline-flex items-center gap-2 rounded-xl border border-red-200 bg-white px-4 py-2 text-sm font-medium text-red-700 hover:border-red-300 hover:bg-red-50"
                        >
                          <RefreshCw aria-hidden="true" className="h-4 w-4" />
                          Retry
                        </button>
                      }
                    />
                  ) : loadingFormDetails ? (
                    <div
                      className="animate-pulse space-y-4 rounded-3xl border border-gray-200 bg-white p-5 shadow-sm"
                      role="status"
                      aria-live="polite"
                      aria-busy="true"
                    >
                      <span className="sr-only">Loading form questions...</span>
                      <div className="h-3 w-1/6 rounded bg-gray-200"></div>
                      <div className="h-5 w-1/3 rounded bg-gray-200"></div>
                      <div className="mt-4 space-y-3">
                        <div className="h-12 rounded-2xl bg-gray-100"></div>
                        <div className="h-12 rounded-2xl bg-gray-100"></div>
                      </div>
                    </div>
                  ) : activeClientPlan && activeClientForm ? (
                    <div
                      id={`client-form-panel-${activeClientForm.form_type}`}
                      role="tabpanel"
                      aria-labelledby={`client-form-tab-${activeClientForm.form_type}`}
                    >
                      {renderQuestionnairePages(
                        activeClientPlan.pages,
                        formAnswers,
                        setFormAnswers,
                        "There are no client questions for this form."
                      )}
                    </div>
                  ) : (
                    <EmptyState
                      description="There are no client questions to review."
                      className="min-h-[220px] bg-white"
                    />
                  )}
                </section>
              </div>
            </div>

            <div className="shrink-0 border-t border-gray-100 bg-white/80 px-5 py-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div role="status" aria-live="polite" className="min-w-0 space-y-1">
                  <p
                    className={`text-sm ${
                      autosaveStatus === "error" ? "text-red-600" : "text-gray-600"
                    }`}
                  >
                    {getAutosaveStatusMessage()}
                  </p>
                  {missingClientRequiredFields.length > 0 && (
                    <p id="client-required-fields-warning" className="text-xs text-amber-700">
                      {getClientPendingFieldsLead(missingClientRequiredFields)}
                      {firstMissingClientRequiredField
                        ? ` ${formatPendingFieldLabel(firstMissingClientRequiredField)}`
                        : ""}
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={handleSaveClientQuestions}
                  aria-describedby={
                    missingClientRequiredFields.length > 0
                      ? "client-required-fields-warning"
                      : undefined
                  }
                  disabled={loadingShared || loadingFormDetails || savingClientQuestions || autofillingFormQuestions}
                  title={autofillingFormQuestions ? "Wait for AI autofill to finish" : loadingShared || loadingFormDetails || savingClientQuestions ? "Please wait while processing" : undefined}
                  className="inline-flex items-center justify-center gap-2 rounded-2xl bg-brand-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {savingClientQuestions ? (
                    <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
                  ) : (
                    <CheckCircle2 aria-hidden="true" className="h-4 w-4" />
                  )}
                  Confirm
                </button>
              </div>
            </div>
          </>
        )}

        {step === "attorney_questions" && (
          <>
            <div
              id="wizard-panel-attorney_questions"
              className="shrink-0 border-b border-gray-100 bg-white/70 px-5 py-4"
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 className="text-base font-semibold text-gray-900">
                    Attorney questions
                  </h3>
                  <p className="text-sm text-gray-500">
                    Review attorney preparation one form at a time to keep the context.
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <div className="shrink-0 min-w-[150px]">
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-gray-400">
                        {attorneyCounts.filled}/{attorneyCounts.total || 0} fields
                      </span>
                      <div className="w-20 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-green-500 rounded-full transition-[width]"
                          style={{
                            width: `${attorneyCounts.total > 0 ? Math.round((attorneyCounts.filled / attorneyCounts.total) * 100) : 0}%`
                          }}
                        />
                      </div>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => setStep("client_questions")}
                    className="inline-flex items-center gap-2 rounded-2xl border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:border-gray-300"
                  >
                    <ArrowLeft aria-hidden="true" className="h-4 w-4" />
                    Back to client
                  </button>
                </div>
              </div>
            </div>

            <div className={`min-h-0 flex-1 overflow-y-auto bg-gray-50 p-5 custom-scroll relative${autofillingFormQuestions ? " select-none" : ""}`}>
              {autofillingFormQuestions && (
                <div className="pointer-events-auto absolute inset-0 z-20 bg-white/40" aria-hidden="true" />
              )}
              <div className={`space-y-8${autofillingFormQuestions ? " pointer-events-none opacity-60" : ""}`}>
                {formLoadError ? (
                  <EmptyState
                    icon={AlertCircle}
                    title="Attorney questions could not be loaded."
                    description="Retry the load before continuing to generation."
                    tone="danger"
                    role="alert"
                    className="min-h-[320px] bg-white"
                    action={
                      <button
                        type="button"
                        onClick={() => void loadFormTypesAndQuestions()}
                        className="inline-flex items-center gap-2 rounded-xl border border-red-200 bg-white px-4 py-2 text-sm font-medium text-red-700 hover:border-red-300 hover:bg-red-50"
                      >
                        <RefreshCw aria-hidden="true" className="h-4 w-4" />
                        Retry
                      </button>
                    }
                  />
                ) : loadingFormDetails ? (
                  <div
                    className="animate-pulse space-y-4 rounded-3xl border border-gray-200 bg-white p-5 shadow-sm"
                    role="status"
                    aria-live="polite"
                    aria-busy="true"
                  >
                    <span className="sr-only">Loading attorney questions...</span>
                    <div className="h-5 w-1/3 rounded bg-gray-200"></div>
                    <div className="mt-4 space-y-3">
                      <div className="h-12 rounded-2xl bg-gray-100"></div>
                      <div className="h-12 rounded-2xl bg-gray-100"></div>
                    </div>
                  </div>
                ) : (
                  <section className="space-y-4">
                    <div className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <h4 className="mt-1 text-base font-semibold text-gray-900">
                            Questions by form
                          </h4>
                          <p className="mt-1 text-sm text-gray-500">
                            Switch between forms to complete only the preparation that belongs to each one.
                          </p>
                        </div>
                        {activeAttorneyCounts && (
                          <div className="rounded-2xl bg-gray-50 px-3 py-2 text-sm text-gray-600">
                            {activeAttorneyCounts.filled}/{activeAttorneyCounts.total || 0} fields
                          </div>
                        )}
                      </div>

                      {attorneyFormsWithQuestions.length > 0 ? (
                        <div
                          role="tablist"
                          aria-label="Select attorney form"
                          className="mt-4 flex flex-wrap gap-2"
                        >
                          {attorneyFormsWithQuestions.map((form) => {
                            const isSelected = form.form_type === activeAttorneyForm?.form_type;
                            const counts = attorneyFormCounts[form.form_type] ?? {
                              filled: 0,
                              total: 0,
                            };

                            return (
                              <button
                                key={`attorney-tab-${form.form_type}`}
                                id={`attorney-form-tab-${form.form_type}`}
                                role="tab"
                                type="button"
                                aria-selected={isSelected}
                                aria-controls={`attorney-form-panel-${form.form_type}`}
                                onClick={() => setActiveAttorneyFormType(form.form_type)}
                                className={`inline-flex items-center gap-2 rounded-2xl border px-4 py-2 text-sm font-medium transition ${
                                  isSelected
                                    ? "border-brand-500 bg-brand-50 text-brand-800"
                                    : "border-gray-200 bg-white text-gray-700 hover:border-gray-300"
                                }`}
                              >
                                <span>{form.label}</span>
                                <span
                                  className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                                    isSelected
                                      ? "bg-brand-100 text-brand-800"
                                      : "bg-gray-100 text-gray-700"
                                  }`}
                                >
                                  {counts.filled}/{counts.total || 0}
                                </span>
                              </button>
                            );
                          })}
                        </div>
                      ) : (
                        <p className="mt-4 text-sm text-gray-500">
                          There are no attorney questions for the available forms.
                        </p>
                      )}
                    </div>

                    {activeAttorneyPages && activeAttorneyForm ? (
                      <div
                        id={`attorney-form-panel-${activeAttorneyForm.form_type}`}
                        role="tabpanel"
                        aria-labelledby={`attorney-form-tab-${activeAttorneyForm.form_type}`}
                      >
                        {renderQuestionnairePages(
                          activeAttorneyPages,
                          formAnswers,
                          setFormAnswers,
                          "There are no attorney questions for this form."
                        )}
                      </div>
                    ) : (
                      <EmptyState
                        description="There are no attorney questions to review."
                        className="min-h-[220px] bg-white"
                      />
                    )}
                  </section>
                )}
              </div>
            </div>

            <div className="shrink-0 border-t border-gray-100 bg-white/80 px-5 py-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div role="status" aria-live="polite" className="min-w-0 space-y-1">
                  <p
                    className={`text-sm ${
                      autosaveStatus === "error" ? "text-red-600" : "text-gray-600"
                    }`}
                  >
                    {getAutosaveStatusMessage()}
                  </p>
                  <p className="text-xs text-gray-500">
                    Confirm when you want to move to generation and preview.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={handleSaveAttorneyQuestions}
                      disabled={loadingFormDetails || savingAttorneyQuestions || autofillingFormQuestions}
                      title={autofillingFormQuestions ? "Wait for AI autofill to finish" : loadingFormDetails || savingAttorneyQuestions ? "Please wait while processing" : undefined}
                  className="inline-flex items-center justify-center gap-2 rounded-2xl bg-brand-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {savingAttorneyQuestions ? (
                    <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
                  ) : (
                    <CheckCircle2 aria-hidden="true" className="h-4 w-4" />
                  )}
                  Confirm
                </button>
              </div>
            </div>
          </>
        )}

        {step === "preview" && (
          <div
            id="wizard-panel-preview"
            className="grid min-h-0 flex-1 gap-0 lg:grid-cols-[minmax(0,1fr)_340px]"
          >
            <div className="flex min-h-0 flex-col border-b border-gray-100 lg:border-b-0 lg:border-r">
              <div className="border-b border-gray-100 bg-white/70 px-5 py-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h3 className="text-base font-semibold text-gray-900">
                      Generate & Preview
                    </h3>
                    <p className="text-sm text-gray-500">
                      Generate new PDFs or review the status in the history.
                    </p>
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={handleEditCurrentForm}
                      className="inline-flex items-center gap-2 rounded-2xl border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:border-gray-300"
                    >
                      <ArrowLeft aria-hidden="true" className="h-4 w-4" />
                      Edit answers
                    </button>
                    <button
                      type="button"
                      onClick={handleRegenerate}
                      disabled={!job || job.status === "queued" || job.status === "running" || regeneratingJob}
                      title={!job || job.status === "queued" || job.status === "running" || regeneratingJob ? "Wait for the current process to finish" : undefined}
                      className="inline-flex items-center gap-2 rounded-2xl border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:border-gray-300 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {regeneratingJob ? (
                        <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
                      ) : (
                        <RefreshCw aria-hidden="true" className="h-4 w-4" />
                      )}
                      Regenerate PDF
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        job &&
                        downloadFilledPdf(
                          job.id,
                          `${job.form_type || "form"}_filled.pdf`,
                          getJobPdfCacheKey(job)
                        )
                      }
                      disabled={!job || job.status !== "completed" || !job.filled_pdf_path}
                      title={!job || job.status !== "completed" || !job.filled_pdf_path ? "PDF is not ready for download" : undefined}
                      className="inline-flex items-center gap-2 rounded-2xl bg-brand-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <FileDown aria-hidden="true" className="h-4 w-4" />
                      Download
                    </button>
                  </div>
                </div>

                <div className="mt-4 flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-gray-700">Generate new form:</span>
                  <select
                    className="rounded-lg border-gray-300 text-sm focus:border-brand-500 focus:ring-brand-500"
                    value={selectedArea}
                    onChange={(e) => {
                      setSelectedArea(e.target.value as "Todas" | "Visa T" | "SIJS");
                      setSelectedFormToGenerate("");
                    }}
                  >
                    <option value="Todas">Todas</option>
                    <option value="Visa T">Visa T</option>
                    <option value="SIJS">SIJS</option>
                  </select>
                  
                  <div className="flex items-center gap-2">
                    <select
                      className="rounded-lg border-gray-300 text-sm focus:border-brand-500 focus:ring-brand-500 min-w-[200px]"
                      value={selectedFormToGenerate}
                      onChange={(e) => setSelectedFormToGenerate(e.target.value)}
                    >
                      <option value="" disabled>Seleccione una forma</option>
                      {(selectedArea === "Todas" || selectedArea === "Visa T") && (
                        <optgroup label="Visa T">
                          {formTypes.filter(ft => ["i-192", "i-765", "i-914", "g-28", "g-1145"].includes(ft.form_type.toLowerCase())).map(ft => (
                            <option key={`gen-vt-${ft.form_type}`} value={ft.form_type}>{ft.label}</option>
                          ))}
                        </optgroup>
                      )}
                      {(selectedArea === "Todas" || selectedArea === "SIJS") && (
                        <optgroup label="SIJS">
                          {formTypes.filter(ft => !["i-192", "i-765", "i-914", "g-28", "g-1145"].includes(ft.form_type.toLowerCase())).map(ft => (
                            <option key={`gen-SIJS-${ft.form_type}`} value={ft.form_type}>{ft.label}</option>
                          ))}
                        </optgroup>
                      )}
                    </select>
                    <button
                      type="button"
                      onClick={() => handleGenerate(selectedFormToGenerate)}
                      disabled={!selectedFormToGenerate || Boolean(generatingFormType)}
                      title={generatingFormType ? "A form is currently being generated" : undefined}
                      className="inline-flex items-center gap-2 rounded-xl bg-brand-50 px-3 py-1.5 text-sm font-medium text-brand-800 border border-brand-200 hover:bg-brand-100 disabled:opacity-50 transition"
                    >
                      {generatingFormType ? (
                        <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Plus aria-hidden="true" className="h-3.5 w-3.5" />
                      )}
                      Generate
                    </button>
                  </div>
                </div>

                {job && (
                  <div className="mt-4 rounded-2xl border border-gray-200 bg-white p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="space-y-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="text-lg font-semibold text-gray-900">
                            {job.form_type ? job.form_type.toUpperCase() : "Form"}
                          </p>
                          <span
                            className={`rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide ${
                              job.status === "completed"
                                ? "bg-green-50 text-green-800"
                                : job.status === "needs_review"
                                  ? "bg-amber-50 text-amber-900"
                                : job.status === "failed"
                                  ? "bg-red-50 text-red-800"
                                  : "bg-amber-50 text-amber-900"
                            }`}
                          >
                            {job.status}
                          </span>
                        </div>
                        <p className="text-sm text-gray-600">{getJobPhaseLabel(job)}</p>
                        <p className="text-xs text-gray-500">
                          {getJobTimestampLabel(job)}: {formatDateLabel(getJobDisplayTimestamp(job))}
                        </p>
                      </div>
                      <div className="rounded-2xl bg-gray-50 px-3 py-2 text-sm text-gray-600">
                        {job.progress_pct.toFixed(0)}% complete
                      </div>
                    </div>

                    {(job.status === "queued" || job.status === "running") && (
                      <div className="mt-4">
                        <div
                          className="h-2 overflow-hidden rounded-full bg-gray-100"
                          role="progressbar"
                          aria-label="Active form progress"
                          aria-valuemin={0}
                          aria-valuemax={100}
                          aria-valuenow={Math.round(job.progress_pct)}
                        >
                          <div
                            className="h-2 rounded-full bg-brand-500 transition-all"
                            style={{ width: `${job.progress_pct}%` }}
                          />
                        </div>
                      </div>
                    )}

                    {job.error_message && (
                      <div className="mt-4 flex items-start gap-2 rounded-2xl border border-red-100 bg-red-50 p-3 text-sm text-red-800">
                        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                        <p className="whitespace-pre-wrap">{job.error_message}</p>
                      </div>
                    )}
                  </div>
                )}
              </div>

              <div
                id="form-preview-panel"
                className="min-h-[720px] flex-1 bg-gray-50 p-5 lg:min-h-[780px]"
              >
                {!activeJobId && !loadingJobs && jobsLoadError && (
                  <EmptyState
                    icon={AlertCircle}
                    title="The initial history could not be loaded."
                    description="Retry to recover existing forms or generate a new one."
                    tone="danger"
                    role="alert"
                    className="min-h-[320px] bg-white"
                    action={
                      <button
                        type="button"
                        onClick={() => void loadJobs(true, false)}
                        className="inline-flex items-center gap-2 rounded-xl border border-red-200 bg-white px-4 py-2 text-sm font-medium text-red-700 hover:border-red-300 hover:bg-red-50"
                      >
                        <RefreshCw aria-hidden="true" className="h-4 w-4" />
                        Retry history
                      </button>
                    }
                  />
                )}

                {!activeJobId && !loadingJobs && !jobsLoadError && (
                  <EmptyState
                    icon={FileText}
                    title="There are no forms to display yet."
                    description="Generate one from the wizard or select an item from the history."
                    className="min-h-[320px] bg-white"
                  />
                )}

                {activeJobId && loadingJobDetails && !job && (
                  <div
                    className="h-full min-h-[320px] animate-pulse overflow-hidden rounded-3xl border border-gray-200 bg-gray-50 p-8"
                    role="status"
                    aria-live="polite"
                    aria-busy="true"
                  >
                    <span className="sr-only">Loading form details...</span>
                    <div className="mx-auto h-full max-w-2xl rounded-xl bg-white shadow-sm"></div>
                  </div>
                )}

                {activeJobId && !loadingJobDetails && jobDetailsError && (
                  <EmptyState
                    icon={AlertCircle}
                    title="Form details could not be loaded."
                    description="Retry the request or select another item from the history."
                    tone="danger"
                    role="alert"
                    className="min-h-[320px] bg-white"
                    action={
                      <button
                        type="button"
                        onClick={() => void handleRefreshActiveJob()}
                        className="inline-flex items-center gap-2 rounded-xl border border-red-200 bg-white px-4 py-2 text-sm font-medium text-red-700 hover:border-red-300 hover:bg-red-50"
                      >
                        <RefreshCw aria-hidden="true" className="h-4 w-4" />
                        Retry details
                      </button>
                    }
                  />
                )}

                {job && (
                  <div className="h-full min-h-[680px] overflow-hidden rounded-3xl border border-gray-200 bg-white lg:min-h-[740px]">
                    {pdfPreviewUrl ? (
                      <iframe
                        src={pdfPreviewUrl}
                        title="Generated PDF preview"
                        className="h-full min-h-[680px] w-full border-0 lg:min-h-[740px]"
                      />
                    ) : job.status === "completed" && loadingPdfPreview ? (
                      <div
                        className="flex h-full min-h-[320px] items-center justify-center p-8 text-center"
                        role="status"
                        aria-live="polite"
                      >
                        <div className="space-y-3 text-gray-500">
                          <Loader2
                            aria-hidden="true"
                            className="mx-auto h-8 w-8 animate-spin text-brand-600"
                          />
                          <p className="text-sm">Loading PDF preview...</p>
                        </div>
                      </div>
                    ) : job.status === "completed" && previewLoadError ? (
                      <EmptyState
                        icon={AlertCircle}
                        title="The PDF preview could not be loaded."
                        description="You can retry the load or download the file directly."
                        tone="danger"
                        role="alert"
                        withBorder={false}
                        className="min-h-[320px] bg-transparent p-8"
                        action={
                          <button
                            type="button"
                            onClick={() => setPreviewRetryCount((count) => count + 1)}
                            className="inline-flex items-center gap-2 rounded-xl border border-red-200 bg-white px-4 py-2 text-sm font-medium text-red-700 hover:border-red-300 hover:bg-red-50"
                          >
                            <RefreshCw aria-hidden="true" className="h-4 w-4" />
                            Retry preview
                          </button>
                        }
                      />
                    ) : job.status === "needs_review" ? (
                      <EmptyState
                        icon={AlertCircle}
                        title="Manual review is required before finalizing this PDF."
                        description="Review the blocking issues, correct the form data, and run generation again."
                        withBorder={false}
                        className="min-h-[320px] bg-transparent p-8"
                      />
                    ) : job.status === "failed" ? (
                      <EmptyState
                        icon={AlertCircle}
                        title="Generation did not complete."
                        description="Review the error message and, if needed, correct the answers before generating again."
                        withBorder={false}
                        className="min-h-[320px] bg-transparent p-8"
                      />
                    ) : (
                      <EmptyState
                        icon={FileText}
                        title="The PDF will be available when generation finishes."
                        description='Use "Refresh status" to refresh the process manually.'
                        withBorder={false}
                        className="min-h-[320px] bg-transparent p-8"
                      />
                    )}
                  </div>
                )}
              </div>
            </div>

            <aside className="flex min-h-0 flex-col bg-white/70">
              <div className="border-b border-gray-100 px-5 py-4">
                <h3 className="text-sm font-semibold uppercase tracking-wide text-gray-700">
                  Form history
                </h3>
                <p className="mt-1 text-sm text-gray-500">
                  Select any previous generation to review its status or download it.
                </p>
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto p-4 custom-scroll">
                {loadingJobs ? (
                  <div
                    className="space-y-3"
                    role="status"
                    aria-live="polite"
                    aria-busy="true"
                  >
                    <span className="sr-only">Loading form history...</span>
                    {[1, 2, 3].map((i) => (
                      <div key={i} className="h-24 w-full animate-pulse rounded-2xl border border-gray-200 bg-gray-50"></div>
                    ))}
                  </div>
                ) : jobsLoadError ? (
                  <EmptyState
                    icon={AlertCircle}
                    title="The history could not be loaded."
                    description="Retry to check the generated forms again."
                    tone="danger"
                    role="alert"
                    action={
                      <button
                        type="button"
                        onClick={() => void loadJobs(true, false)}
                        className="inline-flex items-center gap-2 rounded-xl border border-red-200 bg-white px-4 py-2 text-sm font-medium text-red-700 hover:border-red-300 hover:bg-red-50"
                      >
                        <RefreshCw aria-hidden="true" className="h-4 w-4" />
                        Retry
                      </button>
                    }
                  />
                ) : jobs.length === 0 ? (
                  <EmptyState description="There are no forms in the history yet." />
                ) : (
                  <ul className="space-y-3">
                    {jobs.map((historyJob) => (
                      <li
                        key={historyJob.id}
                        className={`rounded-2xl border p-2 transition ${
                          historyJob.id === activeJobId
                            ? "border-brand-500 bg-brand-50"
                            : "border-gray-200 bg-white hover:border-gray-300"
                        }`}
                      >
                        <div className="flex items-start gap-2">
                          <button
                            type="button"
                            aria-controls="form-preview-panel"
                            aria-pressed={historyJob.id === activeJobId}
                            onClick={() => {
                              setActiveJobId(historyJob.id);
                              setStep("preview");
                            }}
                            className="min-w-0 flex-1 rounded-xl p-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-200"
                          >
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <p className="truncate text-sm font-semibold text-gray-900">
                                  {historyJob.form_type
                                    ? historyJob.form_type.toUpperCase()
                                    : "Form"}
                                </p>
                                <p className="mt-1 text-xs text-gray-500">
                                  {getJobTimestampLabel(historyJob)}: {formatDateLabel(getJobDisplayTimestamp(historyJob))}
                                </p>
                              </div>
                              <div className="flex items-center gap-2">
                                {historyJob.status === "completed" && (
                                  <CheckCircle2
                                    aria-hidden="true"
                                    className="h-4 w-4 text-green-600"
                                  />
                                )}
                                {historyJob.status === "failed" && (
                                  <AlertCircle
                                    aria-hidden="true"
                                    className="h-4 w-4 text-red-500"
                                  />
                                )}
                                {historyJob.status === "needs_review" && (
                                  <AlertCircle
                                    aria-hidden="true"
                                    className="h-4 w-4 text-amber-500"
                                  />
                                )}
                                {(historyJob.status === "queued" ||
                                  historyJob.status === "running") && (
                                  <Loader2
                                    aria-hidden="true"
                                    className="h-4 w-4 animate-spin text-amber-500"
                                  />
                                )}
                              </div>
                            </div>

                            <div className="mt-3 flex items-center justify-between text-xs text-gray-500">
                              <span>{getJobPhaseLabel(historyJob)}</span>
                              <span>{historyJob.progress_pct.toFixed(0)}%</span>
                            </div>

                            {(historyJob.status === "queued" ||
                              historyJob.status === "running") && (
                              <div
                                className="mt-2 h-1.5 overflow-hidden rounded-full bg-gray-100"
                                role="progressbar"
                                aria-label={`Progress for ${
                                  historyJob.form_type || "form"
                                }`}
                                aria-valuemin={0}
                                aria-valuemax={100}
                                aria-valuenow={Math.round(historyJob.progress_pct)}
                              >
                                <div
                                  className="h-1.5 rounded-full bg-brand-500"
                                  style={{ width: `${historyJob.progress_pct}%` }}
                                />
                              </div>
                            )}
                          </button>

                          <button
                            type="button"
                            onClick={(event) => handleDeleteJob(historyJob.id, event)}
                            className="mt-2 rounded-lg p-2 text-gray-400 hover:bg-red-50 hover:text-red-500"
                            title="Delete form"
                            aria-label={`Delete ${
                              historyJob.form_type
                                ? historyJob.form_type.toUpperCase()
                                : "form"
                            } from history`}
                          >
                            <X aria-hidden="true" className="h-4 w-4" />
                          </button>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </aside>
          </div>
        )}
      </GlassSurface>
    </div>
  );
}
