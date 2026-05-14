import type { AutopilotJob } from "../../types";

export function nextCode(siblings: { code: string }[]): string {
  if (siblings.length === 0) return "1";
  const sorted = [...siblings].sort((a, b) =>
    a.code.localeCompare(b.code, undefined, { numeric: true })
  );
  const last = sorted[sorted.length - 1].code;
  if (/^\d+$/.test(last)) return String(Number(last) + 1);
  const isUpper = last === last.toUpperCase();
  const c = last.toLowerCase().charCodeAt(last.length - 1);
  const next = c >= 122 ? "aa" : String.fromCharCode(c + 1);
  return isUpper ? next.toUpperCase() : next;
}

export function autopilotPhaseSummary(
  job: AutopilotJob | null
): { title: string; detail: string } {
  if (!job) return { title: "AI AUTOPILOT", detail: "" };

  if (job.phase === "extracting_document") {
    const processed = (job.ocr_processed_pages || 0) + (job.ocr_error_pages || 0);
    return {
      title: `OCR ${processed}/${job.ocr_total_pages || 0}`,
      detail: `Extrayendo OCR ${processed}/${job.ocr_total_pages || 0} páginas`,
    };
  }
  if (job.phase === "writing_json") {
    return {
      title: "JSON",
      detail: "Escribiendo archivos JSON del documento",
    };
  }
  if (job.phase === "indexing_document") {
    const processed = (job.index_processed_chunks || 0) + (job.index_error_chunks || 0);
    return {
      title: `INDEX ${processed}/${job.index_total_chunks || 0}`,
      detail: `Indexando ${processed}/${job.index_total_chunks || 0} chunks`,
    };
  }
  if (job.phase === "gathering_evidence") {
    return {
      title: `EVID ${job.evidence_processed_questions || 0}/${job.evidence_total_questions || 0}`,
      detail: `Reuniendo evidencia ${job.evidence_processed_questions || 0}/${job.evidence_total_questions || 0} preguntas`,
    };
  }
  if (job.phase === "verifying_questions") {
    return {
      title: `QC ${job.processed_questions || 0}/${job.total_questions || 0}`,
      detail: `Verificando ${job.processed_questions || 0}/${job.total_questions || 0} preguntas`,
    };
  }
  if (job.phase === "loading_results") {
    return {
      title: "CARGANDO...",
      detail: "Actualizando resultados en pantalla...",
    };
  }
  if (job.phase === "completed") {
    return {
      title: "COMPLETADO",
      detail: "AI Autopilot completado",
    };
  }
  return { title: "PREPARANDO", detail: "Preparando AI Autopilot" };
}
