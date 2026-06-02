import { memo, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  Plus,
  Trash2,
  ChevronDown,
  ChevronRight,
  ChevronUp,
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
  Link2,
  Search,
  Send,
  Save,
  FilePlus,
  Bookmark,
  MoreVertical,
  Library,
} from "lucide-react";
import toast from "react-hot-toast";
import { motion, AnimatePresence } from "framer-motion";
import { Tooltip } from "../ui/Tooltip";
import { EmptyState } from "../ui/EmptyState";
import { AnimatedAIBot } from "../ui/AnimatedAIBot";
import CaseDocumentScopePicker from "../document-scopes/CaseDocumentScopePicker";
import { SolidCard } from "../ui/SolidCard";
import { NovaBreathingLogo } from "../ui/NovaBreathingLogo";
import { GlassButton } from "../glass/GlassButton";
import { LoadingButton } from "../ui/LoadingButton";
import { useBusyActions } from "../../hooks/useBusyActions";
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
import { groupQcTemplates } from "../../utils/qcTemplateGroups";

interface Props {
  caseId: string;
  caseData: Case | null;
  pages: Page[];
  onCaseUpdated?: (updatedCase: Case) => void;
  onRefresh: () => void;
  docTypes?: DocumentType[];
}

const ANSWER_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  unanswered: { bg: "bg-brand-50", text: "text-brand-500", label: "—" },
  yes: { bg: "bg-green-100", text: "text-green-700", label: "Yes" },
  no: { bg: "bg-red-100", text: "text-red-700", label: "No" },
  na: { bg: "bg-brand-100", text: "text-brand-700", label: "N/A" },
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
  const [expandedClId, setExpandedClId] = useState<string | null>(null);
  const [geminiOk, setGeminiOk] = useState(false);

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
  const [templatesCollapsed, setTemplatesCollapsed] = useState(false);
  const { isBusy, run } = useBusyActions();

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

  useEffect(() => {
    if (checklists.length === 0) {
      setExpandedClId(null);
      return;
    }
    setExpandedClId((current) => {
      if (current && checklists.some((cl) => cl.id === current)) {
        return current;
      }
      return checklists[0].id;
    });
  }, [checklists]);

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
      toast.error("Could not save QC document scope");
    } finally {
      setSavingDocumentScope(false);
    }
  };

  const togglePart = (id: string) => setExpandedParts((p) => ({ ...p, [id]: !p[id] }));
  const toggleCl = (id: string) => {
    setExpandedClId((current) => (current === id ? null : id));
  };
  const appliedTemplateIds = useMemo(
    () =>
      new Set(
        checklists
          .map((cl) => cl.source_template_id)
          .filter((id): id is string => Boolean(id))
      ),
    [checklists]
  );
  const groupedTemplates = useMemo(
    () => groupQcTemplates(templates),
    [templates]
  );
  const appliedTemplateCount = appliedTemplateIds.size;
  const canCollapseTemplates = !loading && templates.length > 0;
  const isTemplatesContentCollapsed = canCollapseTemplates && templatesCollapsed;

  const handleCreateChecklist = () =>
    run("create-qc-checklist", async () => {
      if (!clName.trim()) return;
      await createQCChecklist({ name: clName.trim() }, caseId);
      setClName("");
      setAddingCl(false);
      await reload();
      onRefresh();
    });

  const closeCreateChecklistModal = () => {
    setAddingCl(false);
    setClName("");
  };

  const createChecklistModalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!addingCl) return;

    const scrollY = window.scrollY;
    const { style } = document.body;
    const previous = {
      overflow: style.overflow,
      position: style.position,
      top: style.top,
      width: style.width,
    };
    style.overflow = "hidden";
    style.position = "fixed";
    style.top = `-${scrollY}px`;
    style.width = "100%";

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeCreateChecklistModal();
    };
    document.addEventListener("keydown", onKeyDown);

    const focusFrame = requestAnimationFrame(() => {
      createChecklistModalRef.current
        ?.querySelector<HTMLInputElement>("input")
        ?.focus({ preventScroll: true });
    });

    return () => {
      cancelAnimationFrame(focusFrame);
      document.removeEventListener("keydown", onKeyDown);
      style.overflow = previous.overflow;
      style.position = previous.position;
      style.top = previous.top;
      style.width = previous.width;
      window.scrollTo(0, scrollY);
    };
  }, [addingCl]);

  const handleApplyTemplate = (tplId: string) => {
    if (appliedTemplateIds.has(tplId)) {
      toast("This QC template has already been applied to this case.");
      return;
    }
    run(`apply-qc-template:${tplId}`, async () => {
      const promise = applyQCTemplate(caseId, tplId).then(async () => {
        await reload();
        onRefresh();
      });
      await toast.promise(promise, {
        loading: "Applying template…",
        success: "QC template applied",
        error: (error: unknown) => getApiErrorMessage(error, "Failed to apply template"),
      });
    });
  };

  const handleSeedAll = () =>
    run("seed-all-templates", async () => {
      const promise = seedAllQCTemplates().then(reload);
      await toast.promise(promise, {
        loading: "Reloading all templates…",
        success: "Templates reloaded",
        error: "Failed to reload templates",
      });
    });

  const handleAddPart = (clId: string, parentPartId?: string) =>
    run(parentPartId ? `add-subpart:${parentPartId}` : `add-part:${clId}`, async () => {
      if (!newName.trim()) return;
      try {
        await createQCPart(clId, { name: newName.trim(), code: newCode, parent_part_id: parentPartId });
        setNewName(""); setNewCode(""); setAddingPartFor(null); setAddingSubpartFor(null);
        await reload();
      } catch { toast.error("Failed to create part"); }
    });

  const handleAddQuestion = (partId: string) =>
    run(`add-question:${partId}`, async () => {
      if (!newDesc.trim()) return;
      try {
        await createQCQuestion(partId, { code: newCode, description: newDesc.trim(), where_to_verify: newVerify });
        setNewDesc(""); setNewCode(""); setNewVerify(""); setAddingQuestionFor(null);
        await reload();
      } catch { toast.error("Failed to create question"); }
    });

  const handleSetAnswer = async (q: QCQuestion, answer: string) => {
    const next = q.answer === answer ? "unanswered" : answer;
    try {
      await updateQCQuestion(q.id, { answer: next });
      await reload();
    } catch { toast.error("Failed to update answer"); }
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
      fallbackError: "Search failed",
    });
  };

  // ── Link preset handlers ──
  const handleSaveLinkPreset = (clId: string, clName: string) =>
    run(`save-link-preset:${clId}`, async () => {
      try {
        await saveLinkPreset(clId, { name: `Preset - ${clName}` });
        toast.success("Link preset saved");
        await reload();
      } catch { toast.error("Failed to save preset"); }
    });

  const handleApplyLinkPreset = (clId: string, presetId: string) =>
    run(`apply-link-preset:${presetId}`, async () => {
      try {
        await applyLinkPreset(caseId, clId, presetId);
        toast.success("Link preset applied");
        setShowPresetMenuFor(null);
        await reload();
      } catch { toast.error("Failed to apply preset"); }
    });

  const handleAutoLinkSections = (clId: string) =>
    run(`auto-link:${clId}`, async () => {
      try {
        await autoLinkQCSections(caseId, clId);
        toast.success("Auto-link completed");
        await reload();
      } catch (error: unknown) {
        toast.error(getApiErrorMessage(error, "Failed to auto-link sections"));
      }
    });

  const handleDeleteLinkPreset = (presetId: string) =>
    run(`delete-link-preset:${presetId}`, async () => {
      try {
        await deleteLinkPreset(presetId);
        toast.success("Preset deleted");
        setLinkPresets((prev) => prev.filter((p) => p.id !== presetId));
      } catch { toast.error("Failed to delete preset"); }
    });

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

  const [expandedAI, setExpandedAI] = useState<Record<string, boolean>>({});

  // Render a question row
  const renderQuestion = (q: QCQuestion) => {
    const hasAI = !!q.ai_answer;
    const aiExpanded = expandedAI[q.id];
    return (
      <div key={q.id} className="border-l-2 border-transparent hover:border-brand-300 transition rounded-xl">
        {/* Main row */}
        <div className="group flex items-start gap-2 rounded-xl px-2 py-2 text-xs transition-colors hover:bg-brand-50/70">
          {/* Delete Action (Left side) */}
          <Tooltip content="Delete question">
            <GlassButton
              type="button"
              variant="ghost"
              size="xs"
              iconOnly
              onClick={() => deleteQCQuestion(q.id).then(reload)}
              aria-label="Delete question"
              className="mt-0.5 opacity-40 group-hover:opacity-100 !border-transparent !bg-transparent !shadow-none hover:!bg-red-50 hover:!text-red-500 focus:opacity-100"
            >
              <Trash2 className="w-3 h-3" aria-hidden="true" />
            </GlassButton>
          </Tooltip>

          {/* Code */}
          <span className="mt-1 w-6 shrink-0 text-right font-mono text-xs text-brand-400">{q.code}</span>

          {/* Description + metadata */}
          <div className="flex-1 min-w-0 mt-0.5">
            <p className="text-sm leading-snug text-brand-800">{q.description}</p>
            {q.where_to_verify && (
              <p className="mt-1 flex items-center gap-0.5 text-xs text-brand-500">
                <FileSearch className="w-3 h-3 shrink-0" />
                {q.where_to_verify}
              </p>
            )}
            {q.correction && (
              <p className="text-xs text-amber-600 mt-0.5 italic">Correction: {q.correction}</p>
            )}
            {/* Read-only section targets */}
            {q.target_section_ids && q.target_section_ids.length > 0 && (
              <div className="mt-1 flex flex-wrap items-center gap-1">
                <span className="text-xs font-medium text-brand-500">Sections to verify:</span>
                {q.target_section_ids.map((sid) => {
                  const sec = allSections.find((s) => s.id === sid);
                  return sec ? (
                    <span key={sid} className="rounded bg-brand-50 px-1 py-0.5 text-xs text-brand-700">
                      {sec.path_code || sec.name}
                    </span>
                  ) : null;
                })}
              </div>
            )}
            {hasAI && (
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <button
                  onClick={() => setExpandedAI((p) => ({ ...p, [q.id]: !p[q.id] }))}
                  className={`inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full font-semibold transition ${
                    q.ai_answer === "yes" ? "bg-green-100 text-green-700" :
                    q.ai_answer === "no" ? "bg-red-100 text-red-700" :
                    q.ai_answer === "insufficient" ? "bg-amber-100 text-amber-700" :
                    "bg-brand-50 text-brand-500"
                  } hover:ring-1 hover:ring-accent-300`}
                  title="View AI result"
                >
                  <Bot className="w-3 h-3" />
                  AI {String(q.ai_answer).toUpperCase()} · {q.ai_confidence === "high" ? "High" : q.ai_confidence === "medium" ? "Medium" : "Low"}
                </button>
              </div>
            )}
          </div>

          {/* Segmented Control for manual answering */}
          <div className="mt-0.5 flex shrink-0 items-center rounded-xl border border-brand-100 bg-brand-50 p-0.5">
            {(["yes", "no", "na", "insufficient"] as const).map((ansKey) => {
              const isSelected = q.answer === ansKey;
              const style = ANSWER_STYLES[ansKey];
              return (
                <button
                  key={ansKey}
                  onClick={() => handleSetAnswer(q, ansKey)}
                  aria-label={isSelected ? "Clear selection" : `Mark as ${style.label}`}
                  className={`w-9 sm:w-10 py-2 rounded-md text-xs font-semibold transition-[background-color,border-color,color,box-shadow] ${
                    isSelected
                      ? `${style.bg} ${style.text} shadow-sm border border-black/5`
                      : "border border-transparent text-brand-500 hover:bg-brand-100"
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
                "border border-brand-100 bg-brand-50"
              }`}>
                <div className="flex items-center gap-1 mb-1 font-semibold">
                  <Bot className="w-3 h-3" />
                  AI result: <span className="uppercase">{q.ai_answer}</span>
                  <span className="ml-1 font-normal text-brand-400">(confidence: {q.ai_confidence || "?"})</span>
                </div>
                {q.ai_notes && <p className="text-brand-700">{q.ai_notes}</p>}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

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
    const pctColor = pct === 100 ? "bg-brand-600" : pct > 50 ? "bg-brand-500" : pct > 0 ? "bg-accent-500" : "bg-brand-200";

    return (
      <div key={part.id} className="mt-1">
        {/* Part header */}
        <div
          className="group flex cursor-pointer items-center gap-1.5 rounded-xl border border-transparent px-3 py-1.5 transition hover:border-brand-100 hover:bg-brand-50/70"
          style={{ marginLeft: `${indent * 16}px` }}
          onClick={() => togglePart(part.id)}
        >
          {isExpanded ? <ChevronDown className="w-3.5 h-3.5 text-brand-400 shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 text-brand-400 shrink-0" />}
          <FolderOpen className="w-4 h-4 text-amber-500 shrink-0" />
          <span className="flex-1 truncate text-sm font-medium text-brand-800">
            {part.code} &ndash; {part.name}
          </span>

          {/* Progress pill */}
          {stats.total > 0 && (
            <div className="flex items-center gap-1.5 shrink-0">
              <div className="h-1.5 w-16 overflow-hidden rounded-full bg-brand-100">
                <div className={`h-full rounded-full transition-[width,background-color] ${pctColor}`} style={{ width: `${pct}%` }} />
              </div>
              <span className="w-12 text-right font-mono text-xs text-brand-500">{stats.answered}/{stats.total}</span>
            </div>
          )}

          {/* Secondary actions */}
          <div className="flex items-center gap-0.5 opacity-40 group-hover:opacity-100 focus-within:opacity-100 transition shrink-0">
            <Tooltip content="Add subpart">
              <GlassButton
                type="button"
                variant="ghost"
                size="xs"
                iconOnly
                aria-label="Add subpart"
                onClick={(e) => {
                  e.stopPropagation();
                  const sib = part.children || [];
                  setNewCode(nextCode(sib));
                  setNewName("");
                  setAddingSubpartFor(part.id);
                  setAddingPartFor(clId);
                }}
                className="!border-transparent !bg-transparent !shadow-none text-brand-400 hover:!bg-brand-50 hover:!text-brand-600"
              >
                <Plus className="w-3.5 h-3.5" aria-hidden="true" />
              </GlassButton>
            </Tooltip>
            <Tooltip content="Add question">
              <GlassButton
                type="button"
                variant="ghost"
                size="xs"
                iconOnly
                aria-label="Add question"
                onClick={(e) => {
                  e.stopPropagation();
                  const sib = part.questions || [];
                  setNewCode(nextCode(sib));
                  setNewDesc("");
                  setNewVerify("");
                  setAddingQuestionFor(part.id);
                }}
                className="!border-transparent !bg-transparent !shadow-none text-brand-400 hover:!bg-brand-50 hover:!text-accent-600"
              >
                <HelpCircle className="w-3.5 h-3.5" aria-hidden="true" />
              </GlassButton>
            </Tooltip>
            <Tooltip content="Delete part">
              <GlassButton
                type="button"
                variant="ghost"
                size="xs"
                iconOnly
                aria-label="Delete part"
                onClick={(e) => {
                  e.stopPropagation();
                  deleteQCPart(part.id).then(reload);
                }}
                className="!border-transparent !bg-transparent !shadow-none text-brand-400 hover:!bg-red-50 hover:!text-red-500"
              >
                <Trash2 className="w-3.5 h-3.5" aria-hidden="true" />
              </GlassButton>
            </Tooltip>
          </div>
        </div>

        {isExpanded && (
          <div className="ml-2">
            {/* Questions */}
            {part.questions.map(renderQuestion)}

            {/* Add question form */}
            {addingQuestionFor === part.id && (
              <div className="mx-2 mt-1 flex flex-col gap-2 rounded-xl border border-brand-100 bg-brand-50/80 p-3" style={{ marginLeft: `${indent * 16}px` }}>
                <div className="flex gap-2">
                  <input className="input-glass w-16 px-2 py-1.5 text-center font-mono text-xs" value={newCode} onChange={(e) => setNewCode(e.target.value)} placeholder="Code" />
                  <input className="input-glass flex-1 px-3 py-1.5 text-xs" value={newDesc} onChange={(e) => setNewDesc(e.target.value)} placeholder="Exact question" autoFocus />
                </div>
                <input className="input-glass px-3 py-1.5 text-xs" value={newVerify} onChange={(e) => setNewVerify(e.target.value)} placeholder="Where to verify? (e.g. Intake; Bio Call; Declaration)" />
                <div className="flex gap-2">
                  <LoadingButton onClick={() => handleAddQuestion(part.id)} disabled={!newDesc.trim()} loading={isBusy(`add-question:${part.id}`)} spinnerClassName="h-3 w-3" className="cta-primary inline-flex flex-1 items-center justify-center gap-1 px-4 py-2 text-xs font-semibold disabled:opacity-40">Create question</LoadingButton>
                  <button onClick={() => setAddingQuestionFor(null)} className="flex-1 rounded-full border border-brand-100 bg-nova-snow px-4 py-2 text-xs font-semibold text-brand-700 transition hover:border-brand-200 hover:bg-brand-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300">Cancel</button>
                </div>
              </div>
            )}

            {/* Add subpart form */}
            {addingSubpartFor === part.id && (
              <div className="mx-2 mt-1 flex flex-col gap-2 rounded-xl border border-brand-100 bg-brand-50/80 p-3" style={{ marginLeft: `${indent * 16}px` }}>
                <div className="flex gap-2">
                  <input className="input-glass w-16 px-2 py-1.5 text-center font-mono text-xs" value={newCode} onChange={(e) => setNewCode(e.target.value)} placeholder="Code" />
                  <input className="input-glass flex-1 px-3 py-1.5 text-xs" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Subpart name" autoFocus />
                </div>
                <div className="flex gap-2">
                  <LoadingButton onClick={() => handleAddPart(clId, part.id)} disabled={!newName.trim()} loading={isBusy(`add-subpart:${part.id}`)} spinnerClassName="h-3 w-3" className="cta-primary inline-flex flex-1 items-center justify-center gap-1 px-4 py-2 text-xs font-semibold disabled:opacity-40">Create subpart</LoadingButton>
                  <button onClick={() => { setAddingSubpartFor(null); setNewName(""); }} className="flex-1 rounded-full border border-brand-100 bg-nova-snow px-4 py-2 text-xs font-semibold text-brand-700 transition hover:border-brand-200 hover:bg-brand-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300">Cancel</button>
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
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div className="mb-1 flex items-center justify-between">
        <h3 className="label-caps mb-0 flex items-center gap-1.5">
          <ClipboardList className="w-4 h-4" /> QC Checklists
        </h3>
        <Tooltip content="Create new QC checklist">
          <GlassButton
            type="button"
            variant="secondary"
            size="sm"
            iconOnly
            aria-label="Create new QC checklist"
            onClick={() => setAddingCl(true)}
          >
            <Plus className="w-4 h-4" aria-hidden="true" />
          </GlassButton>
        </Tooltip>
      </div>

      {/* Templates — grouped, collapsible */}
      <SolidCard className="section-panel-accent p-5">
        <div className={`flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between ${isTemplatesContentCollapsed ? "" : ""}`}>
          <div className="flex items-start gap-3">
            <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-brand-100 text-brand-600">
              <Library className="h-4 w-4" />
            </div>
            <div>
              <p className="text-base font-semibold text-brand-900">Templates</p>
              <p className="mt-0.5 max-w-xl text-sm text-brand-600">
                Apply preloaded templates to this case checklist.
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3 self-start sm:self-auto">
            {!loading && templates.length > 0 && (
              <span
                className={`rounded-full px-3 py-1 text-xs font-semibold tracking-wide ${
                  appliedTemplateCount > 0
                    ? "bg-emerald-100 text-emerald-700"
                    : "bg-amber-100 text-amber-700"
                }`}
              >
                {appliedTemplateCount}/{templates.length} applied
              </span>
            )}
            {canCollapseTemplates && (
              <button
                type="button"
                aria-expanded={!isTemplatesContentCollapsed}
                aria-controls="qc-templates-details"
                onClick={() => setTemplatesCollapsed((current) => !current)}
                className="inline-flex items-center gap-1.5 rounded-full border border-brand-100 bg-nova-snow px-4 py-2 text-xs font-semibold text-brand-700 shadow-sm transition hover:border-brand-200 hover:bg-brand-50 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-1"
              >
                {isTemplatesContentCollapsed ? (
                  <>
                    <ChevronDown className="h-3.5 w-3.5" />
                    <span>Show templates</span>
                  </>
                ) : (
                  <>
                    <ChevronUp className="h-3.5 w-3.5" />
                    <span>Hide templates</span>
                  </>
                )}
              </button>
            )}
            <LoadingButton
              onClick={handleSeedAll}
              loading={isBusy("seed-all-templates")}
              spinnerClassName="h-3.5 w-3.5"
              className="inline-flex items-center justify-center gap-2 rounded-full border border-brand-100 bg-nova-snow px-4 py-2 text-xs font-semibold text-brand-700 shadow-sm transition hover:border-brand-200 hover:bg-brand-50 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-1 disabled:opacity-50"
            >
              Reload templates
            </LoadingButton>
          </div>
        </div>
        {!isTemplatesContentCollapsed && (
          <div id="qc-templates-details" className="mt-4 flex flex-col gap-4">
            {loading ? (
              <div className="flex justify-center py-3">
                <Loader2 className="h-5 w-5 animate-spin text-brand-400" />
              </div>
            ) : groupedTemplates.length === 0 ? (
              <p className="text-xs italic text-brand-500">No templates available.</p>
            ) : (
              <div className="max-h-72 overflow-y-auto rounded-2xl border border-brand-100/80 bg-white/60 p-1.5 shadow-inner custom-scroll">
                <div className="grid grid-cols-1 gap-4 pr-1 lg:grid-cols-3">
                  {groupedTemplates.map((group) => (
                    <section
                      key={group.id}
                      aria-labelledby={`qc-template-group-${group.id}`}
                      className={group.id === "visa-t" ? "lg:col-span-2" : "lg:col-span-1"}
                    >
                      <h4
                        id={`qc-template-group-${group.id}`}
                        className="sticky top-0 z-10 mb-2 bg-white/95 py-1 text-xs font-semibold uppercase tracking-wide text-brand-700 backdrop-blur-sm"
                      >
                        {group.label}
                      </h4>
                      <div
                        className={`grid gap-2 ${
                          group.id === "visa-t" ? "grid-cols-1 sm:grid-cols-2" : "grid-cols-1"
                        }`}
                      >
                        {group.templates.map((tpl) => {
                          const isApplied = appliedTemplateIds.has(tpl.id);
                          return (
                            <LoadingButton
                              key={tpl.id}
                              onClick={() => handleApplyTemplate(tpl.id)}
                              disabled={isApplied}
                              loading={isBusy(`apply-qc-template:${tpl.id}`)}
                              spinnerClassName="h-4 w-4"
                              title={tpl.name}
                              className={`inline-flex w-full min-w-0 items-center gap-2 rounded-xl border p-3 text-left text-xs transition disabled:opacity-50 ${
                                isApplied
                                  ? "cursor-not-allowed border-brand-100 bg-white/70 text-brand-400"
                                  : "border-transparent hover:border-brand-200 hover:bg-brand-50/70"
                              }`}
                            >
                              {isApplied ? (
                                <Check className="h-4 w-4 shrink-0 text-green-500" />
                              ) : (
                                <FilePlus className="h-4 w-4 shrink-0 text-accent-500" />
                              )}
                              <div className="min-w-0 flex-1">
                                <span
                                  className={`block truncate font-medium ${
                                    isApplied ? "text-brand-500" : "text-brand-800"
                                  }`}
                                >
                                  {tpl.name}
                                </span>
                                <span className="mt-0.5 block text-brand-400">
                                  {tpl.total_questions} questions
                                </span>
                              </div>
                              {isApplied && (
                                <span className="shrink-0 rounded-full bg-green-100 px-2 py-0.5 text-[10px] font-semibold text-green-700">
                                  Applied
                                </span>
                              )}
                            </LoadingButton>
                          );
                        })}
                      </div>
                    </section>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </SolidCard>

      <CaseDocumentScopePicker
        title="Documents for automatic QC"
        description="Select which case documents AI Autopilot and automatic QC verification can use."
        documents={qcScopeDocuments}
        selectedIds={selectedQcSourceDocumentIds}
        saving={savingDocumentScope}
        collapsible
        defaultCollapsed
        listMaxHeightClassName="max-h-40"
        onChange={handleQcScopeChange}
      />

      {createPortal(
        addingCl ? (
          <div
            className="fixed inset-0 z-[80] flex items-center justify-center bg-nova-slate/60 p-4 sm:p-8"
            role="dialog"
            aria-modal="true"
            aria-labelledby="new-qc-checklist-title"
            onClick={closeCreateChecklistModal}
          >
            <div
              ref={createChecklistModalRef}
              className="relative max-h-[calc(100vh-2rem)] w-full max-w-lg overflow-y-auto rounded-2xl border border-brand-100 bg-white p-6 shadow-2xl"
              onClick={(event) => event.stopPropagation()}
            >
              <h2
                id="new-qc-checklist-title"
                className="mb-4 font-heading text-lg font-bold text-brand-900"
              >
                Create QC Checklist
              </h2>
              <div>
                <label className="label-caps" htmlFor="new-qc-checklist-name">
                  Name
                </label>
                <input
                  id="new-qc-checklist-name"
                  className="input-glass"
                  placeholder="QC Checklist name"
                  value={clName}
                  onChange={(event) => setClName(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") void handleCreateChecklist();
                  }}
                />
              </div>
              <div className="mt-6 flex gap-3">
                <GlassButton
                  variant="primary"
                  onClick={() => void handleCreateChecklist()}
                  disabled={!clName.trim()}
                  loading={isBusy("create-qc-checklist")}
                  loadingLabel="Creating…"
                >
                  Create checklist
                </GlassButton>
                <GlassButton variant="ghost" onClick={closeCreateChecklistModal} disabled={isBusy("create-qc-checklist")}>
                  Cancel
                </GlassButton>
              </div>
            </div>
          </div>
        ) : null,
        document.body
      )}

      {/* Checklist list */}
      {checklists.map((cl) => {
        const isExp = expandedClId === cl.id;
        const pct = cl.total_questions > 0 ? Math.round((cl.answered_questions / cl.total_questions) * 100) : 0;
        const activeJob = verifyingCl === cl.id && autopilotJob?.checklist_id === cl.id ? autopilotJob : null;
        const activeProgress = Math.round(activeJob?.overall_progress_pct ?? 0);
        const activePhase = autopilotPhaseSummary(activeJob);
        return (
          <SolidCard key={cl.id} className="mb-3 overflow-hidden rounded-2xl">
            {/* Checklist header */}
            <div
              className="flex cursor-pointer items-center gap-2 px-4 py-3 transition-colors hover:bg-brand-50/60"
              role="button"
              tabIndex={0}
              aria-expanded={isExp}
              onClick={() => toggleCl(cl.id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  toggleCl(cl.id);
                }
              }}
            >
              {isExp ? <ChevronDown className="w-3.5 h-3.5 text-brand-400" /> : <ChevronRight className="w-3.5 h-3.5 text-brand-400" />}
              <span className="flex-1 font-heading text-sm font-semibold text-brand-900">{cl.name}</span>
              <div className="shrink-0 min-w-[150px]">
                {activeJob ? (
                  <div className="flex flex-col items-end gap-1">
                    <span className="text-xs text-accent-600">{activePhase.detail}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-brand-500">{activeProgress}%</span>
                      <div className="ai-progress-track w-24">
                        <div
                          className="ai-progress-bar"
                          style={{ width: `${activeProgress}%` }}
                        />
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-brand-500">{cl.answered_questions}/{cl.total_questions} ({pct}%)</span>
                    <div className="h-1.5 w-20 overflow-hidden rounded-full bg-brand-100">
                      <div className="h-full rounded-full bg-brand-500 transition-[width]" style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                )}
              </div>
              
              {/* AI Verify Checklist — PREMIUM BUTTON */}
              {cl.total_questions > 0 && (
                <button
                  onClick={(e) => { e.stopPropagation(); geminiOk ? handleAIVerifyChecklist(cl.id) : toast.error("Set GEMINI_API_KEY in the project .env file"); }}
                  disabled={verifyingCl === cl.id || !canRunQcAutopilot}
                  className={`flex items-center gap-2 px-4 py-2 rounded-full text-xs font-bold transition-[background-color,border-color,color,box-shadow,opacity] disabled:opacity-50 shrink-0 border relative overflow-hidden group/ai ${
                    geminiOk
                      ? "ai-cta-button"
                      : "border-brand-100 bg-brand-50 text-brand-400 hover:bg-brand-100"
                  }`}
                >
                  {verifyingCl === cl.id || activeJob ? (
                    <NovaBreathingLogo size="sm" label="Verifying checklist with AI" className="relative z-10" />
                  ) : (
                    <AnimatedAIBot className={`w-4 h-4 ${geminiOk ? "text-nova-snow" : "text-brand-400"}`} />
                  )}
                  <span className="tracking-wide">
                    {activeJob
                      ? activePhase.title
                      : verifyingCl === cl.id
                        ? "STARTING…"
                        : "AI AUTOPILOT"}
                  </span>
                </button>
              )}

              {/* Actions Dropdown */}
              <div className="relative group/menu" onClick={(e) => e.stopPropagation()}>
                <GlassButton
                  type="button"
                  variant="ghost"
                  size="xs"
                  iconOnly
                  aria-label="Checklist actions"
                  className="!border-transparent !bg-transparent !shadow-none text-brand-400 hover:!bg-brand-50 hover:!text-brand-700"
                >
                  <MoreVertical className="w-4 h-4" aria-hidden="true" />
                </GlassButton>
                {/* Invisible bridge to keep hover active */}
                <div className="absolute right-0 top-full w-full h-2"></div>
                <div className="invisible absolute right-0 top-full z-50 mt-1 flex w-60 origin-top-right -translate-y-2 scale-95 flex-col rounded-2xl border border-brand-100 bg-white/95 py-1 opacity-0 shadow-glass-lg backdrop-blur-md transition-[opacity,transform] duration-200 ease-out group-hover/menu:visible group-hover/menu:translate-y-0 group-hover/menu:scale-100 group-hover/menu:opacity-100">
                  <button
                    onClick={() => downloadExportSingleQCReport(caseId, cl.id)}
                    className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-brand-700 transition-colors hover:bg-emerald-50 hover:text-emerald-700"
                  >
                    <Download className="w-3.5 h-3.5" />
                    Download PDF report
                  </button>

                  {indexingOk && !cl.is_template && cl.case_id && (
                    <button
                      onClick={() => {
                        setSemanticClId(semanticClId === cl.id ? null : cl.id);
                        setSemanticResults([]);
                        setSemanticQ("");
                      }}
                      className="flex items-center gap-2 px-3 py-2 text-left text-xs text-brand-700 transition-colors hover:bg-accent-50 hover:text-accent-700"
                    >
                      <Search className="w-3.5 h-3.5" />
                      Search answers
                    </button>
                  )}

                  <button
                    onClick={() => {
                      run(`save-as-template:${cl.id}`, async () => {
                        try {
                          await saveQCAsTemplate(cl.id);
                          toast.success("Saved as template");
                          await reload();
                        } catch {
                          toast.error("Error");
                        }
                      });
                    }}
                    disabled={isBusy(`save-as-template:${cl.id}`)}
                    aria-busy={isBusy(`save-as-template:${cl.id}`) || undefined}
                    className="flex items-center gap-2 px-3 py-2 text-left text-xs text-brand-700 transition-colors hover:bg-accent-50 hover:text-accent-700 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <Save className="w-3.5 h-3.5" />
                    Save as template
                  </button>

                  <button
                    onClick={() => handleSaveLinkPreset(cl.id, cl.name)}
                    disabled={isBusy(`save-link-preset:${cl.id}`)}
                    aria-busy={isBusy(`save-link-preset:${cl.id}`) || undefined}
                    className="flex items-center gap-2 px-3 py-2 text-left text-xs text-brand-700 transition-colors hover:bg-teal-50 hover:text-teal-700 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <Bookmark className="w-3.5 h-3.5" />
                    Save link preset
                  </button>

                  <button
                    onClick={() => handleShowPresets(cl.id, cl.source_template_id)}
                    className="flex items-center gap-2 px-3 py-2 text-left text-xs text-brand-700 transition-colors hover:bg-teal-50 hover:text-teal-700"
                  >
                    <Link2 className="w-3.5 h-3.5" />
                    Apply link preset
                  </button>

                  <button
                    onClick={() => handleAutoLinkSections(cl.id)}
                    disabled={isBusy(`auto-link:${cl.id}`)}
                    aria-busy={isBusy(`auto-link:${cl.id}`) || undefined}
                    className="flex items-center gap-2 px-3 py-2 text-left text-xs text-brand-700 transition-colors hover:bg-amber-50 hover:text-amber-700 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <Sparkles className="w-3.5 h-3.5" />
                    Auto-link sections
                  </button>

                  <div className="my-1 h-px bg-brand-100"></div>

                  <button
                    onClick={() => { const sib = cl.parts || []; setNewCode(nextCode(sib)); setNewName(""); setAddingPartFor(cl.id); setAddingSubpartFor(null); }}
                    className="flex items-center gap-2 px-3 py-2 text-left text-xs text-brand-700 transition-colors hover:bg-brand-50 hover:text-brand-800"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    Add root part
                  </button>

                  <button
                    onClick={() => {
                      if (confirm("Delete this QC checklist?")) {
                        run(`delete-qc-checklist:${cl.id}`, async () => {
                          await deleteQCChecklist(cl.id);
                          await reload();
                        });
                      }
                    }}
                    disabled={isBusy(`delete-qc-checklist:${cl.id}`)}
                    aria-busy={isBusy(`delete-qc-checklist:${cl.id}`) || undefined}
                    className="flex items-center gap-2 px-3 py-2 text-xs text-red-600 hover:bg-red-50 transition-colors text-left disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    Delete checklist
                  </button>
                </div>
              </div>
            </div>

            {/* Preset picker */}
            {showPresetMenuFor === cl.id && (
              <div className="border-t border-teal-200 bg-teal-50/80 px-4 py-3">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-semibold text-teal-700 uppercase">Link presets</span>
                  <Tooltip content="Close presets">
                    <GlassButton
                      type="button"
                      variant="ghost"
                      size="xs"
                      iconOnly
                      aria-label="Close presets"
                      onClick={() => setShowPresetMenuFor(null)}
                      className="!border-transparent !bg-transparent !shadow-none text-brand-400 hover:!text-brand-600"
                    >
                      <XIcon className="w-3 h-3" aria-hidden="true" />
                    </GlassButton>
                  </Tooltip>
                </div>
                {linkPresets.length === 0 ? (
                  <p className="text-xs italic text-brand-500">No saved presets for this QC template.</p>
                ) : (
                  <div className="flex flex-col gap-1">
                    {linkPresets.map((preset) => (
                      <div key={preset.id} className="flex items-center gap-1.5 rounded-xl px-2 py-1 text-xs transition hover:bg-teal-100">
                        <LoadingButton onClick={() => handleApplyLinkPreset(cl.id, preset.id)} loading={isBusy(`apply-link-preset:${preset.id}`)} spinnerClassName="h-3 w-3" className="inline-flex flex-1 items-center gap-1.5 text-left disabled:opacity-50">
                          <Link2 className="w-3 h-3 text-teal-500 shrink-0" />
                          <span className="font-medium text-brand-800">{preset.name}</span>
                          <span className="ml-auto text-xs text-brand-400">{preset.mapping_count} mappings</span>
                        </LoadingButton>
                        <Tooltip content="Delete preset">
                          <GlassButton
                            type="button"
                            variant="ghost"
                            size="xs"
                            iconOnly
                            aria-label="Delete preset"
                            onClick={() => handleDeleteLinkPreset(preset.id)}
                            loading={isBusy(`delete-link-preset:${preset.id}`)}
                            className="!border-transparent !bg-transparent !shadow-none text-brand-400 hover:!text-red-500 hover:!bg-red-50"
                          >
                            <Trash2 className="w-3 h-3" aria-hidden="true" />
                          </GlassButton>
                        </Tooltip>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Semantic query panel */}
            {semanticClId === cl.id && (
              <div className="border-t border-brand-100 bg-brand-50 px-4 py-3">
                <div className="flex items-center gap-2 mb-2">
                  <Search className="w-3.5 h-3.5 text-brand-600" />
                  <span className="text-xs font-semibold text-brand-700 uppercase">Search answers</span>
                  <Tooltip content="Close search">
                    <GlassButton
                      type="button"
                      variant="ghost"
                      size="xs"
                      iconOnly
                      aria-label="Close search"
                      onClick={() => {
                        setSemanticClId(null);
                        setSemanticResults([]);
                      }}
                      className="ml-auto !border-transparent !bg-transparent !shadow-none text-brand-400 hover:!text-brand-600"
                    >
                      <XIcon className="w-3 h-3" aria-hidden="true" />
                    </GlassButton>
                  </Tooltip>
                </div>
                <div className="flex gap-1.5 mb-2">
                  <input
                    className="input-glass flex-1 px-3 py-1.5 text-xs"
                    placeholder="Ask about QC answers…"
                    value={semanticQ}
                    onChange={(e) => setSemanticQ(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleSemanticSearch(cl.id)}
                  />
                  <Tooltip content="Search">
                    <GlassButton
                      type="button"
                      variant="primary"
                      size="xs"
                      iconOnly
                      aria-label="Search"
                      onClick={() => handleSemanticSearch(cl.id)}
                      disabled={!semanticQ.trim()}
                      loading={semanticSearching}
                    >
                      <Send className="w-3 h-3" aria-hidden="true" />
                    </GlassButton>
                  </Tooltip>
                </div>
                {semanticResults.length > 0 && (
                  <div className="flex flex-col gap-1.5 max-h-48 overflow-y-auto custom-scroll">
                    {semanticResults.map((match, i) => (
                      <div key={match.id} className="ai-result-row">
                        <div className="flex items-center justify-between mb-0.5">
                          <span className="font-semibold text-brand-800">#{i + 1}</span>
                          <span className="text-brand-600 font-mono tabular-nums">score: {match.score.toFixed(3)}</span>
                        </div>
                        {!!match.metadata.text && (
                          <p className="text-brand-600 whitespace-pre-wrap line-clamp-3">{String(match.metadata.text)}</p>
                        )}
                        {!!match.metadata.question_code && (
                          <span className="inline-block mt-0.5 text-xs bg-brand-50 text-brand-700 rounded px-1 py-0.5">
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
                  <div className="mx-2 mt-1 flex flex-col gap-2 rounded-xl border border-brand-100 bg-brand-50/80 p-3">
                    <div className="flex gap-2">
                      <input className="input-glass w-16 px-2 py-1.5 text-center font-mono text-xs" value={newCode} onChange={(e) => setNewCode(e.target.value)} placeholder="Code" />
                      <input className="input-glass flex-1 px-3 py-1.5 text-xs" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Part name (e.g. Part 1)" autoFocus />
                    </div>
                    <div className="flex gap-2">
                      <LoadingButton onClick={() => handleAddPart(cl.id)} disabled={!newName.trim()} loading={isBusy(`add-part:${cl.id}`)} spinnerClassName="h-3 w-3" className="cta-primary inline-flex flex-1 items-center justify-center gap-1 px-4 py-2 text-xs font-semibold disabled:opacity-40">Create part</LoadingButton>
                      <button onClick={() => { setAddingPartFor(null); setNewName(""); }} className="flex-1 rounded-full border border-brand-100 bg-nova-snow px-4 py-2 text-xs font-semibold text-brand-700 transition hover:border-brand-200 hover:bg-brand-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300">Cancel</button>
                    </div>
                  </div>
                )}

                {cl.parts.length === 0 && !addingPartFor && (
                  <p className="py-3 text-center text-xs italic text-brand-400">Add parts using the + button in the header menu</p>
                )}
              </div>
            )}
          </SolidCard>
        );
      })}

      {checklists.length === 0 && !addingCl && !loading && (
        <EmptyState icon="checklists" title="No QC Checklists" description="Create one manually or apply the preloaded I-914 template." />
      )}
    </div>
  );
}

export default memo(QCBuilderPanel);