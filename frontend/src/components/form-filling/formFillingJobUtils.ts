import type { FormFillingJob } from "../../types";
import { formatLongDateTime } from "../../utils/dateFormat";

const API_TIMESTAMP_HAS_TIMEZONE_RE = /(?:Z|[+-]\d{2}:\d{2})$/i;

export function getJobPhaseLabel(job: FormFillingJob | null): string {
  if (!job) {
    return "";
  }

  if (job.status === "completed") {
    return "PDF generated";
  }
  if (job.status === "needs_review") {
    return "Manual review required";
  }
  if (job.status === "failed") {
    return "Generation failed";
  }

  switch (job.phase) {
    case "queued":
      return "Queued";
    case "detecting_fields":
      return "Preparing PDF fields";
    case "matching_form":
      return "Matching questions to the template";
    case "writing_pdf":
      return "Writing the PDF";
    case "regenerating_pdf":
      return "Regenerating the PDF";
    default:
      return "Processing";
  }
}

export function parseApiDate(value: string | null | undefined): Date | null {
  if (!value) {
    return null;
  }
  const normalizedValue = API_TIMESTAMP_HAS_TIMEZONE_RE.test(value)
    ? value
    : `${value}Z`;
  const parsed = new Date(normalizedValue);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function getJobDisplayTimestamp(job: FormFillingJob | null): string | null {
  if (!job) {
    return null;
  }
  return (
    job.completed_at ??
    job.updated_at ??
    job.created_at ??
    null
  );
}

export function getJobTimestampLabel(job: FormFillingJob | null): string {
  if (!job) {
    return "Updated";
  }
  if (job.completed_at) {
    return "Completed";
  }
  if (job.updated_at) {
    return "Updated";
  }
  return "Created";
}

export function getJobSortTime(job: FormFillingJob | null): number {
  return parseApiDate(getJobDisplayTimestamp(job))?.getTime() ?? 0;
}

export function formatJobTimestamp(value: string | null | undefined): string {
  const date = parseApiDate(value);
  if (!date) {
    return "Unknown";
  }
  return formatLongDateTime(date);
}
