import { useEffect, useState } from "react";
import { Clock } from "lucide-react";
import type { AuditEntry } from "../types";
import { getAuditLog } from "../api/client";
import { GlassSurface } from "./glass/GlassSurface";

interface Props {
  caseId: string;
  refreshKey: number;
}

const ACTION_LABELS: Record<string, string> = {
  created: "Creado",
  updated: "Actualizado",
  deleted: "Eliminado",
  uploaded: "Cargado",
  classified: "Clasificado",
  unclassified: "Des-clasificado",
  exported_pdf: "PDF exportado",
  exported_report: "Reporte exportado",
};

const ENTITY_LABELS: Record<string, string> = {
  case: "Expediente",
  document_type: "Tipo doc.",
  section: "Seccion",
  page: "Pagina",
  checklist: "Checklist",
  checklist_item: "Item checklist",
};

export default function AuditLogView({ caseId, refreshKey }: Props) {
  const [logs, setLogs] = useState<AuditEntry[]>([]);

  useEffect(() => {
    getAuditLog(caseId).then(setLogs);
  }, [caseId, refreshKey]);

  return (
    <GlassSurface filterId="glass-panel" className="rounded-2xl p-6">
      <h3 className="text-sm font-bold text-gray-700 uppercase tracking-wider mb-3 flex items-center gap-1.5">
        <Clock className="w-4 h-4" /> Historial de Actividad
      </h3>
      {logs.length === 0 ? (
        <p className="text-xs text-gray-400 italic">Sin actividad registrada.</p>
      ) : (
        <div className="max-h-60 overflow-y-auto custom-scroll divide-y divide-gray-200/50">
          {logs.map((log) => (
            <div key={log.id} className="py-2 flex items-start gap-2 text-xs">
              <span className="text-gray-500 font-medium whitespace-nowrap shrink-0">
                {new Date(log.created_at).toLocaleString("es-MX", {
                  dateStyle: "short",
                  timeStyle: "short",
                })}
              </span>
              <span className="text-gray-700">
                <span className="font-medium">
                  {ACTION_LABELS[log.action] ?? log.action}
                </span>{" "}
                {ENTITY_LABELS[log.entity_type] ?? log.entity_type}
                {log.details &&
                  Object.keys(log.details).length > 0 &&
                  ` (${Object.values(log.details).join(", ")})`}
              </span>
            </div>
          ))}
        </div>
      )}
    </GlassSurface>
  );
}

