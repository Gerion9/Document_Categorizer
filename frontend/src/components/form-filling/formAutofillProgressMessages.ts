export type AutofillFallbackPhase = {
  delay: number;
  pct: number;
  msg: string;
};

const SPANISH_TO_ENGLISH: Record<string, string> = {
  "Preparando documentos...": "Preparing documents...",
  "Leyendo documentos...": "Reading documents...",
  "Preparando busqueda en documentos...": "Preparing evidence search...",
  "Buscando informacion relevante...": "Searching for relevant information...",
  "Completando respuestas...": "Completing answers...",
  "Procesando formularios...": "Processing forms...",
  "Procesando preguntas del abogado...": "Completing attorney answers...",
  "Revisando respuestas sugeridas...": "Reviewing suggested answers...",
  "Finalizando analisis...": "Finalizing analysis...",
  Completado: "Completed",
};

const BASE_MESSAGE_ALIASES: Record<string, string> = {
  "Preparing client documents": "Preparing documents",
  "Preparing attorney documents": "Preparing documents",
  "Searching for client information": "Searching for relevant information",
  "Completing client answers": "Completing answers",
  "Searching for shared attorney information": "Searching for relevant information",
  "Completing shared attorney answers": "Completing answers",
  Completed: "Completed",
  "Analyzing answers": "Analyzing answers",
  "Detecting case context": "Detecting case context",
  "Preparing evidence search": "Preparing evidence search",
  "Reviewing suggested answers": "Reviewing suggested answers",
  "Saving suggested answers": "Saving suggested answers",
  "Finalizing analysis": "Finalizing analysis",
  Queued: "Waiting to start",
  Failed: "Autofill failed",
  "Cancelled by user": "Autofill cancelled",
};

function stripTechnicalPrefix(message: string): string {
  return message.replace(/^(Client|Attorney):\s*/i, "").trim();
}

function normalizeProgressBase(message: string): string {
  const trimmed = message.trim();
  if (!trimmed) {
    return "";
  }

  const withoutPrefix = stripTechnicalPrefix(trimmed);
  if (SPANISH_TO_ENGLISH[withoutPrefix]) {
    return SPANISH_TO_ENGLISH[withoutPrefix];
  }

  const readingMatch = withoutPrefix.match(
    /^Reading documents(?:\.\.\.)? \((\d+)\/(\d+) pages\)\.?$/,
  );
  if (readingMatch) {
    return `Reading documents (${readingMatch[1]}/${readingMatch[2]} pages)...`;
  }

  const countedMatch = withoutPrefix.match(/^(.+?)(?:\.\.\.)?(?: \((\d+)\/(\d+)\))?\.?\.?\.?$/);
  if (countedMatch) {
    const [, rawBase, processed, total] = countedMatch;
    const base = rawBase.replace(/\.\.\.$/, "").trim();
    const mappedBase = BASE_MESSAGE_ALIASES[base] ?? base;
    const countSuffix =
      processed && total ? ` (${processed}/${total})` : "";

    return `${mappedBase}${countSuffix}...`;
  }

  return withoutPrefix.endsWith("...") ? withoutPrefix : `${withoutPrefix}...`;
}

export function formatAutofillProgressMessage(
  rawMessage: string | null | undefined,
): string {
  const normalized = normalizeProgressBase(rawMessage ?? "");
  return normalized || "Processing questions...";
}

const SHARED_POST_OCR_PHASES: AutofillFallbackPhase[] = [
  { delay: 0, pct: 52, msg: "Preparing evidence search..." },
  { delay: 8000, pct: 58, msg: "Searching for relevant information..." },
  { delay: 20000, pct: 65, msg: "Completing answers..." },
  { delay: 120000, pct: 90, msg: "Reviewing suggested answers..." },
  { delay: 180000, pct: 95, msg: "Finalizing analysis..." },
];

export const CLIENT_AUTOFILL_POST_OCR_PHASES: AutofillFallbackPhase[] = [
  ...SHARED_POST_OCR_PHASES.slice(0, 3),
  { delay: 50000, pct: 78, msg: "Processing forms..." },
  ...SHARED_POST_OCR_PHASES.slice(3),
];

export const ATTORNEY_AUTOFILL_POST_OCR_PHASES: AutofillFallbackPhase[] = [
  ...SHARED_POST_OCR_PHASES.slice(0, 3),
  { delay: 50000, pct: 78, msg: "Completing attorney answers..." },
  ...SHARED_POST_OCR_PHASES.slice(3),
];

const SHARED_DEFAULT_PHASES: AutofillFallbackPhase[] = [
  { delay: 0, pct: 5, msg: "Preparing documents..." },
  { delay: 3000, pct: 15, msg: "Reading documents..." },
  { delay: 8000, pct: 30, msg: "Preparing evidence search..." },
  { delay: 20000, pct: 50, msg: "Searching for relevant information..." },
  { delay: 40000, pct: 65, msg: "Completing answers..." },
  { delay: 120000, pct: 90, msg: "Reviewing suggested answers..." },
  { delay: 180000, pct: 95, msg: "Finalizing analysis..." },
];

export const CLIENT_AUTOFILL_DEFAULT_PHASES: AutofillFallbackPhase[] = [
  ...SHARED_DEFAULT_PHASES.slice(0, 5),
  { delay: 70000, pct: 78, msg: "Processing forms..." },
  ...SHARED_DEFAULT_PHASES.slice(5),
];

export const ATTORNEY_AUTOFILL_DEFAULT_PHASES: AutofillFallbackPhase[] = [
  ...SHARED_DEFAULT_PHASES.slice(0, 5),
  { delay: 70000, pct: 78, msg: "Completing attorney answers..." },
  ...SHARED_DEFAULT_PHASES.slice(5),
];
