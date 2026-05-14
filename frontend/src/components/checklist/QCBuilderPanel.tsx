import { memo, useEffect, useMemo, useState } from "react";
import {
  Plus,
  Trash2,
  ChevronDown,
  ChevronRight,
  FolderOpen,
  ClipboardList,
  Check,
  X as XIcon,
  HelpCircle,
  FileSearch,
  Download,
  Sparkles,
  Loader2,
  Bot,
  MapPin,
  Link2,
  Search,
  Send,
  Library,
  Save,
  FilePlus,
  Bookmark,
  MoreVertical,
} from "lucide-react";
import toast from "react-hot-toast";
import { motion, AnimatePresence } from "framer-motion";
import { Tooltip } from "../ui/Tooltip";
import { EmptyState } from "../ui/EmptyState";
import { AnimatedAIBot } from "../ui/AnimatedAIBot";
import CaseDocumentScopePicker from "../document-scopes/CaseDocumentScopePicker";
import { GlassSurface } from "../glass/GlassSurface";
import type {
  Case,
  QCChecklist,
  QCPart,
  QCQuestion,
  QCLinkPreset,
  DocumentType,
  Page,
} from "../../types";
import {
  getCaseQCChecklists,
  getQCTemplates,
  createQCChecklist,
  deleteQCChecklist,
  applyQCTemplate,
  createQCPart,
  deleteQCPart,
  createQCQuestion,
  updateQCQuestion,
  deleteQCQuestion,
  seedAllQCTemplates,
  getExtractionStatus,
  saveQCAsTemplate,
  saveLinkPreset,
  getLinkPresets,
  applyLinkPreset,
  autoLinkQCSections,
  deleteLinkPreset,
  qcSemanticQuery,
  downloadExportSingleQCReport,
  updateCase,
} from "../../api/client";
import type { RagMatch } from "../../types";
import {
  buildScopeUpdatePayload,
  listSelectableCaseDocuments,
  resolveSelectedSourceDocumentIds,
} from "../../utils/caseDocumentScopes";
import { getApiErrorMessage } from "../../utils/apiErrors";
import { flattenSections } from "../../utils/sections";
import { runSemanticSearch } from "../../utils/semanticSearch";
import { autopilotPhaseSummary, nextCode } from "./qcBuilderUtils";
import { useQcAutopilot } from "./useQcAutopilot";

interface Props {
  caseId: string;
  caseData: Case | null;
  pages: Page[];
  onCaseUpdated?: (updatedCase: Case) => void;
  onRefresh: () => void;
  docTypes?: DocumentType[];
}

const ANSWER_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  unanswered: { bg: "bg-gray-100", text: "text-gray-500", label: "—" },
  yes: { bg: "bg-green-100", text: "text-green-700", label: "Sí" },
  no: { bg: "bg-red-100", text: "text-red-700", label: "No" },
  na: { bg: "bg-gray-200", text: "text-gray-600", label: "N/A" },
  insufficient: { bg: "bg-amber-100", text: "text-amber-700", label: "Ins." },
};

function QCBuilderPanel({
  caseId,
  caseData,
  pages,
  onCaseUpdated,
  onRefresh,
  docTypes = [],
}: Props) {
  const [checklists, setChecklists] = useState<QCChecklist[]>([]);
  const [templates, setTemplates] = useState<QCChecklist[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedParts, setExpandedParts] = useState<Record<string, boolean>>({});
  const [expandedCl, setExpandedCl] = useState<Record<string, boolean>>({});
  const [showTemplates, setShowTemplates] = useState(false);
  const [geminiOk, setGeminiOk] = useState(false);
  const [mappingQ, setMappingQ] = useState<string | null>(null);

  const allSections = useMemo(
    () => docTypes.flatMap((dt) => flattenSections(dt.sections)),
    [docTypes]
  );

  useEffect(() => { getExtractionStatus().then((r) => setGeminiOk(r.configured)).catch(() => {}); }, []);

  // Inline creation state
  const [addingPartFor, setAddingPartFor] = useState<string | null>(null);
  const [addingSubpartFor, setAddingSubpartFor] = useState<string | null>(null);
  const [addingQuestionFor, setAddingQuestionFor] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [newCode, setNewCode] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [newVerify, setNewVerify] = useState("");
  const [addingCl, setAddingCl] = useState(false);
  const [clName, setClName] = useState("");

  // Link presets state
  const [linkPresets, setLinkPresets] = useState<QCLinkPreset[]>([]);
  const [showPresetMenuFor, setShowPresetMenuFor] = useState<string | null>(null);
  const [savingDocumentScope, setSavingDocumentScope] = useState(false);

  const reload = async () => {
    setLoading(true);
    try {
      const [cls, tpls] = await Promise.all([
        getCaseQCChecklists(caseId),
        getQCTemplates(),
      ]);
      setChecklists(cls);
      setTemplates(tpls);
    } catch { /* ignore */ }
    setLoading(false);
  };

  useEffect(() => { reload(); }, [caseId]);

  const qcScopeDocuments = listSelectableCaseDocuments(pages);
  const selectedQcSourceDocumentIds = resolveSelectedSourceDocumentIds(
    caseData,
    "qc_checklist_source_document_ids",
    qcScopeDocuments
  );
  const canRunQcAutopilot =
    pages.length > 0 &&
    (qcScopeDocuments.length === 0 || selectedQcSourceDocumentIds.length > 0);

  const handleQcScopeChange = async (nextSelectedIds: string[]) => {
    setSavingDocumentScope(true);
    try {
      const updatedCase = await updateCase(
        caseId,
        buildScopeUpdatePayload(
          "qc_checklist_source_document_ids",
          nextSelectedIds,
          qcScopeDocuments
        )
      );
      onCaseUpdated?.(updatedCase);
    } catch {
      toast.error("No se pudo guardar el alcance de documentos para QC");
    } finally {
      setSavingDocumentScope(false);
    }
  };

  const togglePart = (id: string) => setExpandedParts((p) => ({ ...p, [id]: !p[id] }));
  const toggleCl = (id: string) => setExpandedCl((p) => ({ ...p, [id]: !p[id] }));
  const appliedTemplateIds = useMemo(
    () =>
      new Set(
        checklists
          .map((cl) => cl.source_template_id)
          .filter((id): id is string => Boolean(id))
      ),
    [checklists]
  );

  const handleCreateChecklist = async () => {
    if (!clName.trim()) return;
    await createQCChecklist({ name: clName.trim() }, caseId);
    setClName(""); setAddingCl(false);
    await reload(); onRefresh();
  };

  const handleApplyTemplate = async (tplId: string) => {
    if (appliedTemplateIds.has(tplId)) {
      toast("Esta plantilla QC ya fue aplicada a este caso.");
      return;
    }
    const promise = applyQCTemplate(caseId, tplId).then(async () => {
      setShowTemplates(false);
      await reload();
      onRefresh();
    });
    toast.promise(promise, {
      loading: "Aplicando plantilla…",
      success: "Plantilla QC aplicada",
      error: (error: unknown) => getApiErrorMessage(error, "Error al aplicar plantilla")
    });
  };

  const handleSeedAll = async () => {
    const promise = seedAllQCTemplates().then(reload);
    toast.promise(promise, {
      loading: "Precargando todas las plantillas…",
      success: "Plantillas QC precargadas",
      error: "Error al precargar plantillas"
    });
  };

  const handleAddPart = async (clId: string, parentPartId?: string) => {
    if (!newName.trim()) return;
    try {
      await createQCPart(clId, { name: newName.trim(), code: newCode, parent_part_id: parentPartId });
      setNewName(""); setNewCode(""); setAddingPartFor(null); setAddingSubpartFor(null);
      await reload();
    } catch { toast.error("Error al crear parte"); }
  };

  const handleAddQuestion = async (partId: string) => {
    if (!newDesc.trim()) return;
    try {
      await createQCQuestion(partId, { code: newCode, description: newDesc.trim(), where_to_verify: newVerify });
      setNewDesc(""); setNewCode(""); setNewVerify(""); setAddingQuestionFor(null);
      await reload();
    } catch { toast.error("Error al crear pregunta"); }
  };

  const handleSetAnswer = async (q: QCQuestion, answer: string) => {
    const next = q.answer === answer ? "unanswered" : answer;
    try {
      await updateQCQuestion(q.id, { answer: next });
      await reload();
    } catch { toast.error("Error al actualizar respuesta"); }
  };

  const { autopilotJob, verifyingCl, handleAIVerifyChecklist } = useQcAutopilot({
    caseId,
    reload,
  });

  // ── QC Semantic Query state ──
  const [semanticClId, setSemanticClId] = useState<string | null>(null);
  const [semanticQ, setSemanticQ] = useState("");
  const [semanticResults, setSemanticResults] = useState<RagMatch[]>([]);
  const [semanticSearching, setSemanticSearching] = useState(false);
  const [indexingOk, setIndexingOk] = useState(false);

  useEffect(() => {
    getExtractionStatus()
      .then((r) => setIndexingOk(r.indexing_configured ?? false))
      .catch(() => {});
  }, []);

  const handleSemanticSearch = async (clId: string) => {
    await runSemanticSearch({
      query: semanticQ,
      search: (question) => qcSemanticQuery(clId, question),
      setSearching: setSemanticSearching,
      setResults: setSemanticResults,
      fallbackError: "Error en consulta semantica",
    });
  };

  const handleToggleSectionTarget = async (qId: string, sectionId: string, current: string[]) => {
    const next = current.includes(sectionId)
      ? current.filter((id) => id !== sectionId)
      : [...current, sectionId];
    try {
      await updateQCQuestion(qId, { target_section_ids: next });
      await reload();
    } catch { toast.error("Error al actualizar secciones"); }
  };

  // ── Link preset handlers ──
  const handleSaveLinkPreset = async (clId: string, clName: string) => {
    try {
      await saveLinkPreset(clId, { name: `Preset - ${clName}` });
      toast.success("Preset de vinculación guardado");
      await reload();
    } catch { toast.error("Error al guardar preset"); }
  };

  const handleShowPresets = async (clId: string, sourceTemplateId: string | null) => {
    if (showPresetMenuFor === clId) {
      setShowPresetMenuFor(null);
      return;
    }
    try {
      const presets = await getLinkPresets(sourceTemplateId || undefined);
      setLinkPresets(presets);
    } catch { setLinkPresets([]); }
    setShowPresetMenuFor(clId);
  };

  const handleApplyLinkPreset = async (clId: string, presetId: string) => {
    try {
      await applyLinkPreset(caseId, clId, presetId);
      toast.success("Preset de vinculación aplicado");
      setShowPresetMenuFor(null);
      await reload();
    } catch { toast.error("Error al aplicar preset"); }
  };

  const handleAutoLinkSections = async (clId: string) => {
    try {
      await autoLinkQCSections(caseId, clId);
      toast.success("Auto-mapeo ejecutado");
      await reload();
    } catch (error: unknown) {
      toast.error(getApiErrorMessage(error, "Error al auto-mapear secciones"));
    }
  };

  const handleDeleteLinkPreset = async (presetId: string) => {
    try {
      await deleteLinkPreset(presetId);
      toast.success("Preset eliminado");
      setLinkPresets((prev) => prev.filter((p) => p.id !== presetId));
    } catch { toast.error("Error al eliminar preset"); }
  };

  const [expandedAI, setExpandedAI] = useState<Record<string, boolean>>({});

  // Render a question row
  const renderQuestion = (q: QCQuestion) => {
    const hasAI = !!q.ai_answer;
    const aiExpanded = expandedAI[q.id];
    const mappedCount = q.target_section_ids?.length || 0;
    return (
      <div key={q.id} className="border-l-2 border-transparent hover:border-brand-300 transition rounded-md">
        {/* Main row */}
        <div className="group flex items-start gap-2 py-2 px-2 hover:bg-gray-50 transition-colors text-xs">
          {/* Delete Action (Left side) */}
          <Tooltip content="Eliminar pregunta">
            <button
              onClick={() => deleteQCQuestion(q.id).then(reload)}
              aria-label="Eliminar pregunta"
              className="shrink-0 p-1.5 mt-0.5 rounded-md text-gray-400 hover:bg-red-50 hover:text-red-500 transition-colors opacity-40 group-hover:opacity-100 focus:opacity-100 focus-visible:ring-2 focus-visible:ring-red-300 outline-none"
            >
              <Trash2 className="w-3 h-3" />
            </button>
          </Tooltip>

          {/* Code */}
          <span className="shrink-0 font-mono text-xs text-gray-400 w-6 text-right mt-1">{q.code}</span>

          {/* Description + metadata */}
          <div className="flex-1 min-w-0 mt-0.5">
            <p className="text-sm text-gray-800 leading-snug">{q.description}</p>
            {q.where_to_verify && (
              <p className="text-xs text-indigo-500 mt-1 flex items-center gap-0.5">
                <FileSearch className="w-3 h-3 shrink-0" />
                {q.where_to_verify}
              </p>
            )}
            {q.correction && (
              <p className="text-xs text-amber-600 mt-0.5 italic">Corrección: {q.correction}</p>
            )}
            {/* Section target chips */}
            {q.target_section_ids && q.target_section_ids.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-1">
                {q.target_section_ids.map((sid) => {
                  const sec = allSections.find((s) => s.id === sid);
                  return sec ? (
                    <span key={sid} className="text-xs bg-indigo-50 text-indigo-600 rounded px-1 py-0.5">
                      {sec.path_code || sec.name}
                    </span>
                  ) : null;
                })}
              </div>
            )}
            {/* Priority action bar */}
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <Tooltip content="Mapear a secciones del documento">
                <button
                  onClick={() => setMappingQ(mappingQ === q.id ? null : q.id)}
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold border transition ${
                    mappingQ === q.id
                      ? "bg-indigo-100 text-indigo-700 border-indigo-300 shadow-sm"
                      : "bg-white text-indigo-600 border-indigo-200 hover:bg-indigo-50"
                  }`}
                >
                  <MapPin className="w-3.5 h-3.5" />
                  {mappingQ === q.id ? "EDITANDO MAPEO" : "MAPEAR SECCIONES"}
                  <span className="px-1 py-0.5 rounded bg-indigo-200/70 text-xs font-mono">
                    {mappedCount}
                  </span>
                </button>
              </Tooltip>

              {hasAI && (
                <button
                  onClick={() => setExpandedAI((p) => ({ ...p, [q.id]: !p[q.id] }))}
                  className={`inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full font-semibold transition ${
                    q.ai_answer === "yes" ? "bg-green-100 text-green-700" :
                    q.ai_answer === "no" ? "bg-red-100 text-red-700" :
                    q.ai_answer === "insufficient" ? "bg-amber-100 text-amber-700" :
                    "bg-gray-100 text-gray-500"
                  } hover:ring-1 hover:ring-purple-300`}
                  title="Ver resultado AI"
                >
                  <Bot className="w-3 h-3" />
                  AI {String(q.ai_answer).toUpperCase()} · {q.ai_confidence === "high" ? "Alta" : q.ai_confidence === "medium" ? "Media" : "Baja"}
                </button>
              )}
            </div>
          </div>

          {/* Segmented Control for manual answering */}
          <div className="shrink-0 flex items-center bg-gray-100 p-0.5 rounded-lg border border-gray-200 mt-0.5">
            {(["yes", "no", "na", "insufficient"] as const).map((ansKey) => {
              const isSelected = q.answer === ansKey;
              const style = ANSWER_STYLES[ansKey];
              return (
                <button
                  key={ansKey}
                  onClick={() => handleSetAnswer(q, ansKey)}
                  aria-label={isSelected ? "Quitar selección" : `Marcar como ${style.label}`}
                  className={`w-9 sm:w-10 py-2 rounded-md text-xs font-semibold transition-[background-color,border-color,color,box-shadow] ${
                    isSelected
                      ? `${style.bg} ${style.text} shadow-sm border border-black/5`
                      : "text-gray-500 hover:bg-gray-200 border border-transparent"
                  }`}
                >
                  {style.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* AI notes panel (expandible) */}
        <AnimatePresence>
          {hasAI && aiExpanded && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="mx-2 mb-1 overflow-hidden"
            >
              <div className={`p-2 rounded-lg text-xs leading-relaxed ${
                q.ai_answer === "yes" ? "bg-green-50 border border-green-200" :
                q.ai_answer === "no" ? "bg-red-50 border border-red-200" :
                q.ai_answer === "insufficient" ? "bg-amber-50 border border-amber-200" :
                "bg-gray-50 border border-gray-200"
              }`}>
                <div className="flex items-center gap-1 mb-1 font-semibold">
                  <Bot className="w-3 h-3" />
                  Resultado AI: <span className="uppercase">{q.ai_answer}</span>
                  <span className="text-gray-400 font-normal ml-1">(confianza: {q.ai_confidence || "?"})</span>
                </div>
                {q.ai_notes && <p className="text-gray-700">{q.ai_notes}</p>}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Section mapping picker */}
        {mappingQ === q.id && (
          <div className="mx-2 mb-1 p-2 bg-indigo-50 rounded-lg border border-indigo-200 max-h-36 overflow-y-auto custom-scroll">
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-semibold text-indigo-700 uppercase">Secciones donde verificar</span>
              <button aria-label="Cerrar mapeo" onClick={() => setMappingQ(null)} className="text-gray-400 hover:text-gray-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 rounded"><XIcon className="w-3 h-3" /></button>
            </div>
            {allSections.length === 0 ? (
              <p className="text-xs text-gray-400 italic">Crea secciones de documento primero</p>
            ) : (
              <div className="flex flex-col gap-0.5">
                {allSections.map((sec) => {
                  const dt = docTypes.find((d) => d.id === sec.document_type_id);
                  const label = sec.path_code || `${dt?.code || ""}.${sec.code}`;
                  const isTarget = (q.target_section_ids || []).includes(sec.id);
                  return (
                    <label key={sec.id} className={`flex items-center gap-1.5 text-xs px-1.5 py-0.5 rounded cursor-pointer transition ${isTarget ? "bg-indigo-100 text-indigo-800" : "hover:bg-indigo-100/50 text-gray-600"}`} style={{ paddingLeft: `${4 + (sec.depth || 0) * 12}px` }}>
                      <input type="checkbox" checked={isTarget} onChange={() => handleToggleSectionTarget(q.id, sec.id, q.target_section_ids || [])} className="rounded border-indigo-300 text-indigo-600 w-3 h-3" />
                      <span className="font-mono">{label}</span>
                      <span className="text-gray-400">{sec.name}</span>
                    </label>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  // Count all questions recursively in a part and its children
  const countPartQuestions = (part: QCPart, allParts: QCPart[]): { total: number; answered: number; aiVerified: number } => {
    let total = part.questions.length;
    let answered = part.questions.filter((q) => q.answer !== "unanswered").length;
    let aiVerified = part.questions.filter((q) => !!q.ai_answer).length;
    const children = allParts.filter((p) => p.parent_part_id === part.id);
    for (const child of children) {
      const sub = countPartQuestions(child, allParts);
      total += sub.total;
      answered += sub.answered;
      aiVerified += sub.aiVerified;
    }
    return { total, answered, aiVerified };
  };

  // Render a part (recursive)
  const renderPart = (part: QCPart, clId: string, indent: number, allParts: QCPart[] = []) => {
    const isExpanded = expandedParts[part.id] !== false;
    const hasChildren = part.children && part.children.length > 0;
    const stats = countPartQuestions(part, allParts);
    const pct = stats.total > 0 ? Math.round((stats.answered / stats.total) * 100) : 0;
    const pctColor = pct === 100 ? "bg-green-500" : pct > 50 ? "bg-blue-500" : pct > 0 ? "bg-amber-500" : "bg-gray-300";

    return (
      <div key={part.id} className="mt-1">
        {/* Part header */}
        <div
          className="flex items-center gap-1.5 py-1.5 px-3 rounded-lg hover:bg-gray-50 cursor-pointer group border border-transparent hover:border-gray-200 transition"
          style={{ marginLeft: `${indent * 16}px` }}
          onClick={() => togglePart(part.id)}
        >
          {isExpanded ? <ChevronDown className="w-3.5 h-3.5 text-gray-400 shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 text-gray-400 shrink-0" />}
          <FolderOpen className="w-4 h-4 text-amber-500 shrink-0" />
          <span className="font-medium text-gray-800 flex-1 truncate text-sm">
            {part.code} &ndash; {part.name}
          </span>

          {/* Progress pill */}
          {stats.total > 0 && (
            <div className="flex items-center gap-1.5 shrink-0">
              <div className="w-16 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                <div className={`h-full rounded-full transition-[width,background-color] ${pctColor}`} style={{ width: `${pct}%` }} />
              </div>
              <span className="text-xs text-gray-500 font-mono w-12 text-right">{stats.answered}/{stats.total}</span>
            </div>
          )}

          {/* Secondary actions */}
          <div className="flex items-center gap-0.5 opacity-40 group-hover:opacity-100 focus-within:opacity-100 transition shrink-0">
            <Tooltip content="Agregar subparte">
              <button aria-label="Agregar subparte" onClick={(e) => { e.stopPropagation(); const sib = part.children || []; setNewCode(nextCode(sib)); setNewName(""); setAddingSubpartFor(part.id); setAddingPartFor(clId); }} className="p-1.5 text-gray-400 hover:text-brand-600 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 rounded">
                <Plus className="w-3.5 h-3.5" />
              </button>
            </Tooltip>
            <Tooltip content="Agregar pregunta">
              <button aria-label="Agregar pregunta" onClick={(e) => { e.stopPropagation(); const sib = part.questions || []; setNewCode(nextCode(sib)); setNewDesc(""); setNewVerify(""); setAddingQuestionFor(part.id); }} className="p-1.5 text-gray-400 hover:text-indigo-600 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 rounded">
                <HelpCircle className="w-3.5 h-3.5" />
              </button>
            </Tooltip>
            <Tooltip content="Eliminar parte">
              <button aria-label="Eliminar parte" onClick={(e) => { e.stopPropagation(); deleteQCPart(part.id).then(reload); }} className="p-1.5 text-gray-400 hover:text-red-500 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-red-300 rounded">
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </Tooltip>
          </div>
        </div>

        {isExpanded && (
          <div className="ml-2">
            {/* Questions */}
            {part.questions.map(renderQuestion)}

            {/* Add question form */}
            {addingQuestionFor === part.id && (
              <div className="flex flex-col gap-1 p-2 bg-indigo-50 rounded-lg border border-indigo-200 mt-1 mx-2" style={{ marginLeft: `${indent * 16}px` }}>
                <div className="flex gap-1">
                  <input className="w-14 text-xs font-mono border rounded px-1.5 py-0.5 text-center focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300" value={newCode} onChange={(e) => setNewCode(e.target.value)} placeholder="Código" />
                  <input className="flex-1 text-xs border rounded px-2 py-0.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300" value={newDesc} onChange={(e) => setNewDesc(e.target.value)} placeholder="Pregunta exacta" autoFocus />
                </div>
                <input className="text-xs border rounded px-2 py-0.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300" value={newVerify} onChange={(e) => setNewVerify(e.target.value)} placeholder="¿Dónde verificar? (ej. Intake; Bio Call; Declaration)" />
                <div className="flex gap-1">
                  <button onClick={() => handleAddQuestion(part.id)} disabled={!newDesc.trim()} className="flex-1 text-xs bg-indigo-600 text-white rounded py-0.5 hover:bg-indigo-700 disabled:opacity-40 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300">Crear pregunta</button>
                  <button onClick={() => setAddingQuestionFor(null)} className="flex-1 text-xs bg-gray-200 rounded py-0.5 hover:bg-gray-300 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-400">Cancelar</button>
                </div>
              </div>
            )}

            {/* Add subpart form */}
            {addingSubpartFor === part.id && (
              <div className="flex flex-col gap-1 p-2 bg-blue-50 rounded-lg border border-blue-200 mt-1 mx-2" style={{ marginLeft: `${indent * 16}px` }}>
                <div className="flex gap-1">
                  <input className="w-14 text-xs font-mono border rounded px-1.5 py-0.5 text-center focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300" value={newCode} onChange={(e) => setNewCode(e.target.value)} placeholder="Código" />
                  <input className="flex-1 text-xs border rounded px-2 py-0.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Nombre de la subparte" autoFocus />
                </div>
                <div className="flex gap-1">
                  <button onClick={() => handleAddPart(clId, part.id)} disabled={!newName.trim()} className="flex-1 text-xs bg-brand-600 text-white rounded py-0.5 hover:bg-brand-700 disabled:opacity-40 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300">Crear subparte</button>
                  <button onClick={() => { setAddingSubpartFor(null); setNewName(""); }} className="flex-1 text-xs bg-gray-200 rounded py-0.5 hover:bg-gray-300 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-400">Cancelar</button>
                </div>
              </div>
            )}

            {/* Child parts */}
            {hasChildren && part.children.sort((a, b) => a.order - b.order).map((child) => renderPart(child, clId, indent + 1, allParts))}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-bold text-gray-700 uppercase tracking-wider flex items-center gap-1.5">
          <ClipboardList className="w-4 h-4" /> QC Checklists
        </h3>
        <div className="flex gap-2 items-center">
          <div className="flex gap-1">
            <Tooltip content="Plantillas QC disponibles">
              <button aria-label="Plantillas QC disponibles" onClick={() => setShowTemplates(!showTemplates)} className={`p-1.5 rounded transition focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-300 ${showTemplates ? "bg-purple-100 text-purple-600" : "text-gray-500 hover:bg-gray-200"}`}>
                <Library className="w-4 h-4" />
              </button>
            </Tooltip>
            <Tooltip content="Crear QC checklist nuevo">
              <button aria-label="Crear QC checklist nuevo" onClick={() => setAddingCl(true)} className="p-1.5 rounded hover:bg-gray-200 text-brand-600 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300">
                <Plus className="w-4 h-4" />
              </button>
            </Tooltip>
          </div>
        </div>
      </div>

      <CaseDocumentScopePicker
        title="Documentos para QC automatico"
        description="Selecciona que documentos del caso puede usar el AI Autopilot y la verificacion automatica del QC."
        documents={qcScopeDocuments}
        selectedIds={selectedQcSourceDocumentIds}
        saving={savingDocumentScope}
        onChange={handleQcScopeChange}
      />

      {/* Template selector */}
      {showTemplates && (
        <div className="p-2 bg-purple-50 rounded-lg border border-purple-200">
          <div className="flex justify-between items-center mb-1">
            <p className="text-xs font-semibold text-purple-700 uppercase">Plantillas QC</p>
            <button onClick={handleSeedAll} className="text-[10px] bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded hover:bg-purple-200 transition font-medium border border-purple-200">
              Recargar plantillas
            </button>
          </div>
          {loading ? (
            <div className="flex justify-center p-3">
              <Loader2 className="w-5 h-5 animate-spin text-purple-400" />
            </div>
          ) : templates.length === 0 ? (
            <div className="flex flex-col gap-2">
              <p className="text-xs text-gray-400 italic">No hay plantillas disponibles.</p>
            </div>
          ) : (
            <div className="flex flex-col gap-1">
              {templates.map((tpl) => {
                const isApplied = appliedTemplateIds.has(tpl.id);
                return (
                  <button
                    key={tpl.id}
                    onClick={() => handleApplyTemplate(tpl.id)}
                    disabled={isApplied}
                    className={`flex items-center gap-1.5 text-xs text-left px-2 py-1.5 rounded transition ${
                      isApplied
                        ? "bg-white/70 text-gray-400 cursor-not-allowed"
                        : "hover:bg-purple-100"
                    }`}
                  >
                    {isApplied ? (
                      <Check className="w-3.5 h-3.5 text-green-500 shrink-0" />
                    ) : (
                      <FilePlus className="w-3.5 h-3.5 text-purple-500 shrink-0" />
                    )}
                    <div className="flex-1 min-w-0">
                      <span className={`font-medium ${isApplied ? "text-gray-500" : "text-gray-800"}`}>
                        {tpl.name}
                      </span>
                      <span className="text-xs text-gray-400 ml-1">{tpl.total_questions} preguntas</span>
                    </div>
                    {isApplied && (
                      <span className="shrink-0 rounded-full bg-green-100 px-2 py-0.5 text-[10px] font-semibold text-green-700">
                        Aplicada
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* New checklist form */}
      {addingCl && (
        <div className="flex gap-1">
          <input className="flex-1 text-xs border rounded px-2 py-1 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300" placeholder="Nombre del QC Checklist" value={clName} onChange={(e) => setClName(e.target.value)} autoFocus onKeyDown={(e) => e.key === "Enter" && handleCreateChecklist()} />
          <button onClick={handleCreateChecklist} className="text-xs bg-brand-600 text-white rounded px-2 hover:bg-brand-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300">OK</button>
          <button onClick={() => setAddingCl(false)} className="text-xs bg-gray-200 rounded px-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-400">X</button>
        </div>
      )}

      {/* Checklist list */}
      {checklists.map((cl) => {
        const isExp = expandedCl[cl.id] !== false;
        const pct = cl.total_questions > 0 ? Math.round((cl.answered_questions / cl.total_questions) * 100) : 0;
        const activeJob = verifyingCl === cl.id && autopilotJob?.checklist_id === cl.id ? autopilotJob : null;
        const activeProgress = Math.round(activeJob?.overall_progress_pct ?? 0);
        const activePhase = autopilotPhaseSummary(activeJob);
        return (
          <GlassSurface filterId="glass-panel" key={cl.id} className="rounded-xl overflow-hidden mb-3">
            {/* Checklist header */}
            <div className="flex items-center gap-2 px-4 py-3 cursor-pointer hover:bg-white/40 transition-colors" onClick={() => toggleCl(cl.id)}>
              {isExp ? <ChevronDown className="w-3.5 h-3.5 text-gray-400" /> : <ChevronRight className="w-3.5 h-3.5 text-gray-400" />}
              <span className="text-sm font-semibold flex-1">{cl.name}</span>
              <div className="shrink-0 min-w-[150px]">
                {activeJob ? (
                  <div className="flex flex-col items-end gap-1">
                    <span className="text-xs text-purple-600">{activePhase.detail}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-gray-400">{activeProgress}%</span>
                      <div className="w-24 h-1.5 bg-purple-100 rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full bg-gradient-to-r from-purple-500 to-blue-500 transition-[width]"
                          style={{ width: `${activeProgress}%` }}
                        />
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-gray-400">{cl.answered_questions}/{cl.total_questions} ({pct}%)</span>
                    <div className="w-20 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                      <div className="h-full bg-green-500 rounded-full transition-[width]" style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                )}
              </div>
              
              {/* AI Verify Checklist — PREMIUM BUTTON */}
              {cl.total_questions > 0 && (
                <button
                  onClick={(e) => { e.stopPropagation(); geminiOk ? handleAIVerifyChecklist(cl.id) : toast.error("Configura GEMINI_API_KEY en el archivo .env del proyecto"); }}
                  disabled={verifyingCl === cl.id || !canRunQcAutopilot}
                  className={`flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-bold transition-[background-color,border-color,color,box-shadow,opacity] disabled:opacity-50 shrink-0 border relative overflow-hidden group/ai ${
                    geminiOk
                      ? "bg-[#0B0F19] text-white border-gray-700 shadow-lg hover:shadow-purple-500/25 hover:border-purple-500/50"
                      : "bg-gray-100 text-gray-400 hover:bg-gray-200"
                  }`}
                >
                  {geminiOk && (
                    <div className="absolute inset-0 bg-gradient-to-r from-transparent via-purple-500/20 to-transparent translate-x-[-100%] group-hover/ai:animate-[shimmer_1.5s_infinite]" />
                  )}
                  
                  {verifyingCl === cl.id ? (
                    <Loader2 className="w-4 h-4 animate-spin text-purple-400" />
                  ) : (
                    <AnimatedAIBot className={`w-4 h-4 ${geminiOk ? "text-purple-400" : "text-gray-400"}`} />
                  )}
                  <span className={`tracking-wide ${geminiOk ? "text-transparent bg-clip-text bg-gradient-to-r from-purple-400 to-blue-400" : ""}`}>
                    {activeJob
                      ? activePhase.title
                      : verifyingCl === cl.id
                        ? "INICIANDO…"
                        : "AI AUTOPILOT"}
                  </span>
                </button>
              )}

              {/* Actions Dropdown */}
              <div className="relative group/menu" onClick={(e) => e.stopPropagation()}>
                <button className="p-1.5 text-gray-400 hover:text-gray-600 transition rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-300">
                  <MoreVertical className="w-4 h-4" />
                </button>
                {/* Invisible bridge to keep hover active */}
                <div className="absolute right-0 top-full w-full h-2"></div>
                <div className="absolute right-0 top-full mt-1 w-56 bg-white rounded-lg shadow-xl border border-gray-100 opacity-0 invisible -translate-y-2 scale-95 group-hover/menu:opacity-100 group-hover/menu:visible group-hover/menu:translate-y-0 group-hover/menu:scale-100 transition-[opacity,transform] duration-200 ease-out origin-top-right z-50 flex flex-col py-1">
                  <button
                    onClick={() => downloadExportSingleQCReport(caseId, cl.id)}
                    className="flex items-center gap-2 px-3 py-2 text-xs text-gray-600 hover:bg-emerald-50 hover:text-emerald-700 transition-colors w-full text-left"
                  >
                    <Download className="w-3.5 h-3.5" />
                    Descargar reporte PDF
                  </button>

                  {indexingOk && !cl.is_template && cl.case_id && (
                    <button
                      onClick={() => {
                        setSemanticClId(semanticClId === cl.id ? null : cl.id);
                        setSemanticResults([]);
                        setSemanticQ("");
                      }}
                      className="flex items-center gap-2 px-3 py-2 text-xs text-gray-600 hover:bg-purple-50 hover:text-purple-700 transition-colors text-left"
                    >
                      <Search className="w-3.5 h-3.5" />
                      Búsqueda semántica
                    </button>
                  )}

                  <button
                    onClick={async () => { try { await saveQCAsTemplate(cl.id); toast.success("Guardado como plantilla"); await reload(); } catch { toast.error("Error"); } }}
                    className="flex items-center gap-2 px-3 py-2 text-xs text-gray-600 hover:bg-purple-50 hover:text-purple-700 transition-colors text-left"
                  >
                    <Save className="w-3.5 h-3.5" />
                    Guardar como plantilla
                  </button>

                  <button
                    onClick={() => handleSaveLinkPreset(cl.id, cl.name)}
                    className="flex items-center gap-2 px-3 py-2 text-xs text-gray-600 hover:bg-teal-50 hover:text-teal-700 transition-colors text-left"
                  >
                    <Bookmark className="w-3.5 h-3.5" />
                    Guardar preset de vinculación
                  </button>

                  <button
                    onClick={() => handleShowPresets(cl.id, cl.source_template_id)}
                    className="flex items-center gap-2 px-3 py-2 text-xs text-gray-600 hover:bg-teal-50 hover:text-teal-700 transition-colors text-left"
                  >
                    <Link2 className="w-3.5 h-3.5" />
                    Aplicar preset de vinculación
                  </button>

                  <button
                    onClick={() => handleAutoLinkSections(cl.id)}
                    className="flex items-center gap-2 px-3 py-2 text-xs text-gray-600 hover:bg-amber-50 hover:text-amber-700 transition-colors text-left"
                  >
                    <Sparkles className="w-3.5 h-3.5" />
                    Auto-mapear secciones
                  </button>

                  <div className="h-px bg-gray-100 my-1"></div>

                  <button
                    onClick={() => { const sib = cl.parts || []; setNewCode(nextCode(sib)); setNewName(""); setAddingPartFor(cl.id); setAddingSubpartFor(null); }}
                    className="flex items-center gap-2 px-3 py-2 text-xs text-gray-600 hover:bg-brand-50 hover:text-brand-700 transition-colors text-left"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    Agregar parte raíz
                  </button>

                  <button
                    onClick={() => { if (confirm("Eliminar QC checklist?")) deleteQCChecklist(cl.id).then(reload); }}
                    className="flex items-center gap-2 px-3 py-2 text-xs text-red-600 hover:bg-red-50 transition-colors text-left"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    Eliminar checklist
                  </button>
                </div>
              </div>
            </div>

            {/* Preset picker */}
            {showPresetMenuFor === cl.id && (
              <div className="px-4 py-2 bg-teal-50 border-t border-teal-200">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-semibold text-teal-700 uppercase">Presets de vinculación</span>
                  <button aria-label="Cerrar presets" onClick={() => setShowPresetMenuFor(null)} className="text-gray-400 hover:text-gray-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-300 rounded"><XIcon className="w-3 h-3" /></button>
                </div>
                {linkPresets.length === 0 ? (
                  <p className="text-xs text-gray-400 italic">No hay presets guardados para esta plantilla QC.</p>
                ) : (
                  <div className="flex flex-col gap-1">
                    {linkPresets.map((preset) => (
                      <div key={preset.id} className="flex items-center gap-1.5 text-xs px-2 py-1 rounded hover:bg-teal-100 transition">
                        <button onClick={() => handleApplyLinkPreset(cl.id, preset.id)} className="flex-1 text-left flex items-center gap-1.5">
                          <Link2 className="w-3 h-3 text-teal-500 shrink-0" />
                          <span className="font-medium text-gray-800">{preset.name}</span>
                          <span className="text-xs text-gray-400 ml-auto">{preset.mapping_count} mapeos</span>
                        </button>
                        <Tooltip content="Eliminar preset">
                          <button aria-label="Eliminar preset" onClick={() => handleDeleteLinkPreset(preset.id)} className="p-1.5 text-gray-400 hover:text-red-500 transition shrink-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-300 rounded">
                            <Trash2 className="w-3 h-3" />
                          </button>
                        </Tooltip>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Semantic query panel */}
            {semanticClId === cl.id && (
              <div className="px-4 py-3 bg-purple-50 border-t border-purple-200">
                <div className="flex items-center gap-2 mb-2">
                  <Search className="w-3.5 h-3.5 text-purple-500" />
                  <span className="text-xs font-semibold text-purple-700 uppercase">Busqueda Semantica QC</span>
                  <button aria-label="Cerrar búsqueda semántica" onClick={() => { setSemanticClId(null); setSemanticResults([]); }} className="ml-auto text-gray-400 hover:text-gray-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-300 rounded">
                    <XIcon className="w-3 h-3" />
                  </button>
                </div>
                <div className="flex gap-1.5 mb-2">
                  <input
                    className="flex-1 text-xs border border-purple-200 rounded-lg px-2.5 py-1.5 focus:ring-1 focus:ring-purple-300 outline-none"
                    placeholder="Pregunta sobre las respuestas del QC…"
                    value={semanticQ}
                    onChange={(e) => setSemanticQ(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleSemanticSearch(cl.id)}
                  />
                  <button
                    onClick={() => handleSemanticSearch(cl.id)}
                    disabled={semanticSearching || !semanticQ.trim()}
                    className="flex items-center gap-1 px-3 py-1.5 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition disabled:opacity-50 text-xs font-semibold"
                  >
                    {semanticSearching ? <Loader2 className="w-3 h-3 animate-spin" /> : <Send className="w-3 h-3" />}
                    Buscar
                  </button>
                </div>
                {semanticResults.length > 0 && (
                  <div className="flex flex-col gap-1.5 max-h-48 overflow-y-auto custom-scroll">
                    {semanticResults.map((match, i) => (
                      <div key={match.id} className="p-2 bg-white/70 rounded-lg border border-purple-100 text-xs">
                        <div className="flex items-center justify-between mb-0.5">
                          <span className="font-semibold text-gray-700">#{i + 1}</span>
                          <span className="text-purple-600 font-mono">score: {match.score.toFixed(3)}</span>
                        </div>
                        {!!match.metadata.text && (
                          <p className="text-gray-600 whitespace-pre-wrap line-clamp-3">{String(match.metadata.text)}</p>
                        )}
                        {!!match.metadata.question_code && (
                          <span className="inline-block mt-0.5 text-xs bg-indigo-50 text-indigo-600 rounded px-1 py-0.5">
                            {String(match.metadata.question_code)}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Content */}
            {isExp && (
              <div className="px-2 pb-2">
                {cl.parts.filter((p) => !p.parent_part_id).sort((a, b) => a.order - b.order).map((part) => renderPart(part, cl.id, 0, cl.parts))}

                {/* Add root part form */}
                {addingPartFor === cl.id && !addingSubpartFor && (
                  <div className="flex flex-col gap-1 p-2 bg-blue-50 rounded-lg border border-blue-200 mt-1 mx-2">
                    <div className="flex gap-1">
                      <input className="w-14 text-xs font-mono border rounded px-1.5 py-0.5 text-center focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300" value={newCode} onChange={(e) => setNewCode(e.target.value)} placeholder="Código" />
                      <input className="flex-1 text-xs border rounded px-2 py-0.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Nombre de la parte (ej. Part 1)" autoFocus />
                    </div>
                    <div className="flex gap-1">
                      <button onClick={() => handleAddPart(cl.id)} disabled={!newName.trim()} className="flex-1 text-xs bg-brand-600 text-white rounded py-0.5 hover:bg-brand-700 disabled:opacity-40 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300">Crear parte</button>
                      <button onClick={() => { setAddingPartFor(null); setNewName(""); }} className="flex-1 text-xs bg-gray-200 rounded py-0.5 hover:bg-gray-300 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-400">Cancelar</button>
                    </div>
                  </div>
                )}

                {cl.parts.length === 0 && !addingPartFor && (
                  <p className="text-xs text-gray-400 italic text-center py-3">Agrega partes con el botón + del encabezado</p>
                )}
              </div>
            )}
          </GlassSurface>
        );
      })}

      {checklists.length === 0 && !addingCl && !loading && (
        <EmptyState icon="checklists" title="Sin QC Checklists" description="Crea uno manualmente o aplica la plantilla I-914 precargada." />
      )}
    </div>
  );
}

export default memo(QCBuilderPanel);