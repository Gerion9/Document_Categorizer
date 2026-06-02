import type {
  FieldVerification,
  QuestionnaireAnswerMap,
  QuestionnairePage,
  VerificationMap,
} from "../../types";

export type FieldOrigin = "manual" | "autofill";
export type FieldOriginsMap = Record<string, Record<string, FieldOrigin>>;

export const SCALAR_FIELD_ORIGIN_KEY = "_value";

export type SanitizedAutofillValue = {
  value: string;
  shouldApply: boolean;
};

export type MergeAutofillOptions = {
  protectedKeys?: Set<string>;
  fieldOrigins: FieldOriginsMap;
  sanitizeSuggestion?: (
    questionId: string,
    fieldId: string | undefined,
    rawValue: unknown
  ) => SanitizedAutofillValue;
};

export type MergeAutofillResult = {
  answers: QuestionnaireAnswerMap;
  appliedCount: number;
  skippedManualCount: number;
  skippedProtectedCount: number;
};

type RepeatableRow = Record<string, unknown>;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function toText(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  return String(value);
}

function hasText(value: string): boolean {
  return value.trim().length > 0;
}

export function makeFieldOriginKey(
  questionId: string,
  fieldId?: string,
  rowIndex?: number
): string {
  if (fieldId === undefined && rowIndex === undefined) {
    return questionId;
  }
  if (fieldId !== undefined && rowIndex !== undefined) {
    return `${questionId}[${rowIndex}].${fieldId}`;
  }
  if (fieldId !== undefined) {
    return `${questionId}.${fieldId}`;
  }
  return `${questionId}[${rowIndex}]`;
}

export function isProtectedAutofillField(
  questionId: string,
  fieldId: string | undefined,
  protectedKeys: Set<string>
): boolean {
  if (fieldId) {
    return protectedKeys.has(`${questionId}.${fieldId}`);
  }
  return protectedKeys.has(questionId);
}

export function getFieldOrigin(
  fieldOrigins: FieldOriginsMap,
  questionId: string,
  fieldId?: string,
  rowIndex?: number
): FieldOrigin | undefined {
  const bucket = fieldOrigins[questionId];
  if (!bucket) {
    return undefined;
  }
  if (fieldId === undefined && rowIndex === undefined) {
    return bucket[SCALAR_FIELD_ORIGIN_KEY];
  }
  if (fieldId !== undefined && rowIndex !== undefined) {
    return bucket[`${rowIndex}.${fieldId}`] ?? bucket[fieldId];
  }
  if (fieldId !== undefined) {
    return bucket[fieldId];
  }
  return undefined;
}

export function setFieldOrigin(
  fieldOrigins: FieldOriginsMap,
  questionId: string,
  origin: FieldOrigin,
  fieldId?: string,
  rowIndex?: number
): void {
  const bucket = { ...(fieldOrigins[questionId] ?? {}) };
  if (fieldId === undefined && rowIndex === undefined) {
    bucket[SCALAR_FIELD_ORIGIN_KEY] = origin;
  } else if (fieldId !== undefined && rowIndex !== undefined) {
    bucket[`${rowIndex}.${fieldId}`] = origin;
  } else if (fieldId !== undefined) {
    bucket[fieldId] = origin;
  }
  fieldOrigins[questionId] = bucket;
}

function hasMeaningfulFieldValue(value: unknown): boolean {
  return hasText(toText(value).trim());
}

function canAutofillOverwrite(
  fieldOrigins: FieldOriginsMap,
  protectedKeys: Set<string>,
  questionId: string,
  fieldId?: string,
  rowIndex?: number
): { allowed: boolean; reason?: "manual" | "protected" } {
  if (isProtectedAutofillField(questionId, fieldId, protectedKeys)) {
    return { allowed: false, reason: "protected" };
  }
  const origin = getFieldOrigin(fieldOrigins, questionId, fieldId, rowIndex);
  if (origin === "manual") {
    return { allowed: false, reason: "manual" };
  }
  return { allowed: true };
}

export function markFieldManual(
  fieldOrigins: FieldOriginsMap,
  questionId: string,
  fieldId?: string,
  rowIndex?: number
): void {
  setFieldOrigin(fieldOrigins, questionId, "manual", fieldId, rowIndex);
}

export function markFieldAutofill(
  fieldOrigins: FieldOriginsMap,
  questionId: string,
  fieldId?: string,
  rowIndex?: number
): void {
  setFieldOrigin(fieldOrigins, questionId, "autofill", fieldId, rowIndex);
}

export function cloneFieldOriginsMap(source: FieldOriginsMap): FieldOriginsMap {
  const next: FieldOriginsMap = {};
  for (const [questionId, bucket] of Object.entries(source)) {
    next[questionId] = { ...bucket };
  }
  return next;
}

function verificationCoversField(
  verification: FieldVerification | undefined,
  fieldId?: string
): boolean {
  if (!verification) {
    return false;
  }
  if (!fieldId) {
    return hasText(verification.status);
  }
  const fields = (verification as FieldVerification & { fields?: Record<string, FieldVerification> })
    .fields;
  if (fields && fields[fieldId]) {
    return hasText(fields[fieldId].status);
  }
  return hasText(verification.status);
}

export function seedFieldOriginsOnLoad(
  pages: QuestionnairePage[],
  answers: QuestionnaireAnswerMap,
  persistedOrigins: FieldOriginsMap,
  verificationMap: VerificationMap
): FieldOriginsMap {
  const next = cloneFieldOriginsMap(persistedOrigins);

  for (const page of pages) {
    for (const item of page.items) {
      const questionId = item.id;
      const verification = verificationMap[questionId];
      const bucket = { ...(next[questionId] ?? {}) };

      if (item.fields?.length) {
        const groupValue = answers[questionId];
        for (const field of item.fields) {
          if (bucket[field.id]) {
            continue;
          }
          let hasValue = false;
          if (Array.isArray(groupValue)) {
            for (let rowIndex = 0; rowIndex < groupValue.length; rowIndex += 1) {
              const row = groupValue[rowIndex];
              if (isPlainObject(row) && hasMeaningfulFieldValue(row[field.id])) {
                hasValue = true;
                const rowKey = `${rowIndex}.${field.id}`;
                if (!bucket[rowKey]) {
                  bucket[rowKey] = verificationCoversField(verification, field.id)
                    ? "autofill"
                    : "manual";
                }
              }
            }
          } else if (isPlainObject(groupValue) && hasMeaningfulFieldValue(groupValue[field.id])) {
            hasValue = true;
            bucket[field.id] = verificationCoversField(verification, field.id)
              ? "autofill"
              : "manual";
          }
          if (!hasValue) {
            continue;
          }
        }
      } else {
        const scalarValue = answers[questionId];
        if (!bucket[SCALAR_FIELD_ORIGIN_KEY] && hasMeaningfulFieldValue(scalarValue)) {
          bucket[SCALAR_FIELD_ORIGIN_KEY] = verificationCoversField(verification)
            ? "autofill"
            : "manual";
        }
      }

      if (Object.keys(bucket).length > 0) {
        next[questionId] = bucket;
      }
    }
  }

  return next;
}

export function mergeAutofillAnswers(
  currentAnswers: QuestionnaireAnswerMap,
  suggestedAnswers: QuestionnaireAnswerMap,
  options: MergeAutofillOptions
): MergeAutofillResult {
  const protectedKeys = options.protectedKeys ?? new Set<string>();
  const fieldOrigins = options.fieldOrigins;
  const sanitize = options.sanitizeSuggestion ?? ((_, __, raw) => ({
    value: toText(raw).trim(),
    shouldApply: hasText(toText(raw).trim()),
  }));
  const next: QuestionnaireAnswerMap = { ...currentAnswers };
  let appliedCount = 0;
  let skippedManualCount = 0;
  let skippedProtectedCount = 0;

  const recordSkip = (reason: "manual" | "protected" | undefined) => {
    if (reason === "manual") {
      skippedManualCount += 1;
    } else if (reason === "protected") {
      skippedProtectedCount += 1;
    }
  };

  for (const [questionId, rawSuggestedValue] of Object.entries(suggestedAnswers)) {
    if (Array.isArray(rawSuggestedValue)) {
      const existingRows = Array.isArray(next[questionId])
        ? [...(next[questionId] as RepeatableRow[])]
        : [];
      let changed = false;

      rawSuggestedValue.forEach((rawRow, rowIndex) => {
        if (!isPlainObject(rawRow)) {
          return;
        }
        const targetRow: RepeatableRow = {
          ...(isPlainObject(existingRows[rowIndex])
            ? { ...(existingRows[rowIndex] as RepeatableRow) }
            : {}),
        };

        for (const [fieldId, fieldValue] of Object.entries(rawRow)) {
          const gate = canAutofillOverwrite(
            fieldOrigins,
            protectedKeys,
            questionId,
            fieldId,
            rowIndex
          );
          if (!gate.allowed) {
            recordSkip(gate.reason);
            continue;
          }
          const sanitized = sanitize(questionId, fieldId, fieldValue);
          if (!sanitized.shouldApply) {
            continue;
          }
          if (toText(targetRow[fieldId]) !== sanitized.value) {
            targetRow[fieldId] = sanitized.value;
            markFieldAutofill(fieldOrigins, questionId, fieldId, rowIndex);
            appliedCount += 1;
            changed = true;
          }
        }

        if (Object.keys(targetRow).some((key) => hasMeaningfulFieldValue(targetRow[key]))) {
          existingRows[rowIndex] = targetRow;
        }
      });

      if (changed) {
        next[questionId] = existingRows;
      }
      continue;
    }

    if (isPlainObject(rawSuggestedValue)) {
      const existingValue = isPlainObject(next[questionId])
        ? { ...(next[questionId] as Record<string, unknown>) }
        : {};
      let changed = false;

      for (const [fieldId, rawFieldValue] of Object.entries(rawSuggestedValue)) {
        const gate = canAutofillOverwrite(fieldOrigins, protectedKeys, questionId, fieldId);
        if (!gate.allowed) {
          recordSkip(gate.reason);
          continue;
        }
        const sanitized = sanitize(questionId, fieldId, rawFieldValue);
        if (!sanitized.shouldApply) {
          continue;
        }
        if (toText(existingValue[fieldId]) !== sanitized.value) {
          existingValue[fieldId] = sanitized.value;
          markFieldAutofill(fieldOrigins, questionId, fieldId);
          appliedCount += 1;
          changed = true;
        }
      }

      if (changed) {
        next[questionId] = existingValue;
      }
      continue;
    }

    const gate = canAutofillOverwrite(fieldOrigins, protectedKeys, questionId);
    if (!gate.allowed) {
      recordSkip(gate.reason);
      continue;
    }
    const sanitized = sanitize(questionId, undefined, rawSuggestedValue);
    if (!sanitized.shouldApply) {
      continue;
    }
    if (toText(next[questionId]) !== sanitized.value) {
      next[questionId] = sanitized.value;
      markFieldAutofill(fieldOrigins, questionId);
      appliedCount += 1;
    }
  }

  return {
    answers: next,
    appliedCount,
    skippedManualCount,
    skippedProtectedCount,
  };
}

export function buildAutofillResultMessage(parts: {
  appliedCount: number;
  skippedManualCount: number;
  skippedProtectedCount: number;
  skippedLowConfidence?: number;
  leaUnitCleared?: boolean;
}): string[] {
  const messages: string[] = [];
  if (parts.appliedCount > 0) {
    messages.push(
      `${parts.appliedCount} campo${parts.appliedCount === 1 ? "" : "s"} actualizado${parts.appliedCount === 1 ? "" : "s"} por IA.`
    );
  }
  if (parts.skippedManualCount > 0) {
    messages.push(
      `${parts.skippedManualCount} campo${parts.skippedManualCount === 1 ? "" : "s"} conservado${parts.skippedManualCount === 1 ? "" : "s"} porque ${parts.skippedManualCount === 1 ? "fue editado" : "fueron editados"} manualmente.`
    );
  }
  if (parts.skippedProtectedCount > 0) {
    messages.push(
      `${parts.skippedProtectedCount} valor${parts.skippedProtectedCount === 1 ? "" : "es"} predeterminado${parts.skippedProtectedCount === 1 ? "" : "s"} sin modificar.`
    );
  }
  if (parts.leaUnitCleared) {
    messages.push(
      "Part 3.5 Number se dejó en blanco porque debe completarse manualmente."
    );
  }
  if ((parts.skippedLowConfidence ?? 0) > 0) {
    messages.push(
      `${parts.skippedLowConfidence} sugerencia${parts.skippedLowConfidence === 1 ? "" : "s"} omitida${parts.skippedLowConfidence === 1 ? "" : "s"} por baja confianza.`
    );
  }
  return messages;
}

export const MANUAL_FIELD_TITLE =
  "Editado manualmente. AI Autofill no sobrescribirá este campo.";
