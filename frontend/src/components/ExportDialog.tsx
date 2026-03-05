import { motion } from "framer-motion";
import { exportPdf, exportQCReport } from "../api/client";
import { AnimatedPDF } from "./ui/AnimatedPDF";
import { AnimatedReport } from "./ui/AnimatedReport";
import { GlassSurface } from "./glass/GlassSurface";

interface Props {
  caseId: string;
  caseName: string;
}

export default function ExportDialog({ caseId, caseName }: Props) {
  return (
    <GlassSurface filterId="glass-panel" className="rounded-2xl p-6 mb-6">
      <h3 className="text-lg font-bold text-gray-800 mb-4">
        Exportar &mdash; {caseName}
      </h3>

      <div className="grid gap-4 sm:grid-cols-2">
        {/* Consolidated PDF */}
        <motion.a
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          href={exportPdf(caseId)}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-3 p-4 rounded-xl border border-white/40 bg-white/30 hover:bg-white/50 shadow-sm hover:shadow-md transition-all group"
        >
          <div className="p-2 rounded-lg bg-red-50 group-hover:bg-red-100 transition">
            <AnimatedPDF className="w-10 h-10" />
          </div>
          <div>
            <p className="font-semibold text-sm text-gray-800">PDF Consolidado</p>
            <p className="text-xs text-gray-500">
              Documento completo con indice jerarquico y marcadores navegables
            </p>
          </div>
        </motion.a>

        {/* QC Compliance Report */}
        <motion.a
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          href={exportQCReport(caseId)}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-3 p-4 rounded-xl border border-white/40 bg-white/30 hover:bg-white/50 shadow-sm hover:shadow-md transition-all group"
        >
          <div className="p-2 rounded-lg bg-emerald-50 group-hover:bg-emerald-100 transition">
            <AnimatedReport className="w-10 h-10" />
          </div>
          <div>
            <p className="font-semibold text-sm text-gray-800">Reporte QC Checklist</p>
            <p className="text-xs text-gray-500">
              Reporte de cumplimiento por Parte con resultados de AI, evidencia y correcciones
            </p>
          </div>
        </motion.a>
      </div>
    </GlassSurface>
  );
}
