import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import {
  DndContext,
  DragOverlay,
  DragEndEvent,
  DragStartEvent,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  ArrowLeft,
  LayoutGrid,
  Upload,
  X,
  Tag,
  Loader2,
  CheckCircle2,
  AlertCircle,
  FileText,
  Copy,
  FolderOpen,
  Sparkles,
  RefreshCw,
  Search,
  Send,
} from "lucide-react";
import toast from "react-hot-toast";
import { motion, AnimatePresence } from "framer-motion";
import { Tooltip } from "../components/ui/Tooltip";
import { EmptyState } from "../components/ui/EmptyState";

import type {
  Case,
  DocumentType,
  Page,
  RagMatch,
  Section,
} from "../types";
import {
  getCase,
  getDocumentTypes,
  getPages,
  classifyPage,
  unclassifyPage,
  markExtra,
  addPageSectionLink,
  removePageSectionLink,
  getExtractionStatus,
  reindexPage,
  reindexCase,
  ragQuery,
  deletePage,
  downloadExportPdf,
} from "../api/client";

import FileUpload from "../components/FileUpload";
import PageThumbnail from "../components/PageThumbnail";
import DocumentTree from "../components/DocumentTree";
import SectionDropZone from "../components/SectionDropZone";
import QCBuilderPanel from "../components/checklist/QCBuilderPanel";
import { GlassSurface } from "../components/glass/GlassSurface";
import { useAuth } from "../contexts/AuthContext";
import { AnimatedPDF } from "../components/ui/AnimatedPDF";

import FormFillingPanel from "../components/form-filling/FormFillingPanel";
import { getApiErrorMessage } from "../utils/apiErrors";
import { flattenSections } from "../utils/sections";
import { runSemanticSearch } from "../utils/semanticSearch";

type Tab = "pages" | "organize" | "qc" | "forms";

const TAB_PERMISSIONS: Record<Tab, string> = {
  pages: "tab.pages",
  organize: "tab.organize",
  qc: "tab.qc_checklist",
  forms: "tab.export", // Fallback mapping for forms tab
};

const DND_REQUEST_CONCURRENCY = 8;

export default function CaseWorkspace() {
  const { caseId } = useParams<{ caseId: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();

  const [caseData, setCaseData] = useState<Case | null>(null);
  const [docTypes, setDocTypes] = useState<DocumentType[]>([]);
  const [pages, setPages] = useState<Page[]>([]);
  const [tab, setTab] = useState<Tab>("pages");
  const [selectedSectionId, setSelectedSectionId] = useState<string | null>(null);
  const [selectedDocTypeId, setSelectedDocTypeId] = useState<string | null>(null);
  const [selectedPage, setSelectedPage] = useState<Page | null>(null);
  const [previewPage, setPreviewPage] = useState<Page | null>(null);
  const [selectedPageIds, setSelectedPageIds] = useState<Set<string>>(new Set());
  const [refreshKey, setRefreshKey] = useState(0);
  const [indexingConfigured, setIndexingConfigured] = useState(false);
  const [showOcrText, setShowOcrText] = useState(false);
  const [reindexing, setReindexing] = useState(false);

  // RAG query state
  const [ragQuestion, setRagQuestion] = useState("");
  const [ragResults, setRagResults] = useState<RagMatch[]>([]);
  const [ragSearching, setRagSearching] = useState(false);
  const [showRagPanel, setShowRagPanel] = useState(false);

  const [pagesLoading, setPagesLoading] = useState(false);

  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);

  // ── Data loading ─────────────────────────────────────────────────────
  useEffect(() => {
    if (!caseId) return;
    getCase(caseId).then(setCaseData).catch(() => navigate("/"));
  }, [caseId, refreshKey, navigate]);

  useEffect(() => {
    if (!caseId) return;
    getDocumentTypes(caseId).then(setDocTypes);
  }, [caseId, refreshKey]);

  useEffect(() => {
    if (!caseId) return;
    setPagesLoading(true);
    getPages(caseId)
      .then((data) => {
        setPages(data);
        setPagesLoading(false);
      })
      .catch(() => setPagesLoading(false));
  }, [caseId, refreshKey]);

  // Old checklist loading removed – QC Checklist is the primary system now

  useEffect(() => {
    getExtractionStatus()
      .then((r) => {
        setIndexingConfigured(r.indexing_configured ?? false);
      })
      .catch(() => {
        setIndexingConfigured(false);
      });
  }, []);

  useEffect(() => {
    const perms = user?.permissions ?? [];
    const allowedKeys = (["pages", "organize", "forms", "qc"] as const).filter(
      (key) => perms.includes(TAB_PERMISSIONS[key])
    );
    if (allowedKeys.length > 0 && !allowedKeys.includes(tab)) {
      setTab(allowedKeys[0]);
    }
  }, [user?.permissions, tab]);

  // ── Multi-select handlers ────────────────────────────────────────────
  const handleToggleSelectPage = (pageId: string, selected: boolean) => {
    setSelectedPageIds((prev) => {
      const next = new Set(prev);
      if (selected) next.add(pageId);
      else next.delete(pageId);
      return next;
    });
  };

  const handleToggleSelectAll = (pageIds: string[], selected: boolean) => {
    setSelectedPageIds((prev) => {
      const next = new Set(prev);
      pageIds.forEach((id) => {
        if (selected) next.add(id);
        else next.delete(id);
      });
      return next;
    });
  };

  // ── Derived data ─────────────────────────────────────────────────────
  const unclassifiedPages = useMemo(
    () => pages.filter((p) => p.status === "unclassified"),
    [pages]
  );
  const extraPages = useMemo(
    () => pages.filter((p) => p.status === "extra"),
    [pages]
  );
  const classifiedPages = useMemo(
    () => pages.filter((p) => p.status === "classified"),
    [pages]
  );
  const getRagMatchPageLabel = (match: RagMatch) => {
    const metadataFilename =
      typeof match.metadata.original_filename === "string"
        ? match.metadata.original_filename.trim()
        : "";
    const metadataPageNumberValue =
      match.metadata.page_number ?? match.metadata.original_page_number;
    const metadataPageNumber =
      typeof metadataPageNumberValue === "number"
        ? metadataPageNumberValue
        : typeof metadataPageNumberValue === "string" &&
            metadataPageNumberValue.trim() !== "" &&
            !Number.isNaN(Number(metadataPageNumberValue))
          ? Number(metadataPageNumberValue)
          : null;

    if (metadataFilename && metadataPageNumber !== null) {
      return `${metadataFilename} · pág. ${metadataPageNumber}`;
    }

    const pageId = typeof match.metadata.page_id === "string" ? match.metadata.page_id : "";
    if (!pageId) {
      return metadataFilename || (metadataPageNumber !== null ? `Pág. ${metadataPageNumber}` : null);
    }

    const matchedPage = pages.find((page) => page.id === pageId);
    if (!matchedPage) {
      return metadataFilename || (metadataPageNumber !== null ? `Pág. ${metadataPageNumber}` : null);
    }

    return `${matchedPage.original_filename} · pág. ${matchedPage.original_page_number}`;
  };

  const sectionPages = (sectionId: string) => {
    // Include pages linked to this section via section_links (covers both primary and secondary)
    return pages
      .filter((p) => {
        // Legacy fallback: check page.section_id
        if (p.section_id === sectionId) return true;
        // Multi-link: check section_links array
        return p.section_links?.some((lk) => lk.section_id === sectionId) ?? false;
      })
      .sort((a, b) => {
        // Sort by order from the link for this specific section
        const aLink = a.section_links?.find((lk) => lk.section_id === sectionId);
        const bLink = b.section_links?.find((lk) => lk.section_id === sectionId);
        return (aLink?.order_in_section ?? a.order_in_section ?? 0) - (bLink?.order_in_section ?? b.order_in_section ?? 0);
      });
  };

  const allSectionsFlat = useMemo(
    () => docTypes.flatMap((dt) => flattenSections(dt.sections)),
    [docTypes]
  );

  const buildOptimisticSectionLink = (
    pageId: string,
    sectionId: string,
    isPrimary: boolean,
    orderInSection: number
  ) => {
    const section = allSectionsFlat.find((item) => item.id === sectionId);
    const docType = section
      ? docTypes.find((item) => item.id === section.document_type_id)
      : undefined;

    return {
      id: `optimistic-${pageId}-${sectionId}`,
      page_id: pageId,
      section_id: sectionId,
      is_primary: isPrimary,
      order_in_section: orderInSection,
      created_at: new Date().toISOString(),
      section_path_code: section?.path_code ?? "",
      section_name: section?.name ?? "",
      document_type_code: docType?.code ?? "",
      document_type_name: docType?.name ?? "",
    };
  };

  const applyOptimisticDrop = (
    pageIds: string[],
    overId: string,
    targetSectionId: string | null,
    targetDocTypeId: string | null
  ) => {
    if (pageIds.length === 0) return;

    const pageIdSet = new Set(pageIds);

    setPages((currentPages) => {
      const nextOrderBySection = new Map<string, number>();

      const getNextOrder = (sectionId: string) => {
        if (!nextOrderBySection.has(sectionId)) {
          const currentMax = currentPages.reduce((maxOrder, page) => {
            const linkedOrder =
              page.section_links.find((link) => link.section_id === sectionId)
                ?.order_in_section ?? 0;
            const legacyOrder =
              page.section_id === sectionId ? page.order_in_section ?? 0 : 0;

            return Math.max(maxOrder, linkedOrder, legacyOrder);
          }, 0);

          nextOrderBySection.set(sectionId, currentMax);
        }

        const nextOrder = (nextOrderBySection.get(sectionId) ?? 0) + 1;
        nextOrderBySection.set(sectionId, nextOrder);
        return nextOrder;
      };

      return currentPages.map((page) => {
        if (!pageIdSet.has(page.id)) return page;

        if (overId === "unclassified-zone") {
          return {
            ...page,
            document_type_id: null,
            section_id: null,
            subindex: null,
            order_in_section: null,
            status: "unclassified",
            section_links: [],
            link_count: 0,
          };
        }

        if (overId === "extra-zone") {
          return {
            ...page,
            document_type_id: null,
            section_id: null,
            subindex: null,
            order_in_section: null,
            status: "extra",
            section_links: [],
            link_count: 0,
          };
        }

        if (!targetSectionId || !targetDocTypeId) return page;

        if (page.section_links.some((link) => link.section_id === targetSectionId)) {
          return page;
        }

        const nextOrder = getNextOrder(targetSectionId);

        if (page.status === "classified") {
          const secondaryLink = buildOptimisticSectionLink(
            page.id,
            targetSectionId,
            false,
            nextOrder
          );

          return {
            ...page,
            section_links: [...page.section_links, secondaryLink],
            link_count: page.section_links.length + 1,
          };
        }

        const targetSection = allSectionsFlat.find(
          (section) => section.id === targetSectionId
        );
        const targetDocType = docTypes.find(
          (docType) => docType.id === targetDocTypeId
        );
        const optimisticPrimaryLink = buildOptimisticSectionLink(
          page.id,
          targetSectionId,
          true,
          nextOrder
        );
        const preservedSecondaryLinks = page.section_links.filter(
          (link) => !link.is_primary && link.section_id !== targetSectionId
        );

        return {
          ...page,
          document_type_id: targetDocTypeId,
          section_id: targetSectionId,
          subindex:
            targetSection && targetDocType
              ? `${targetDocType.code}${targetSection.code}`
              : page.subindex,
          order_in_section: nextOrder,
          status: "classified",
          section_links: [optimisticPrimaryLink, ...preservedSecondaryLinks],
          link_count: preservedSecondaryLinks.length + 1,
        };
      });
    });
  };

  const runChunkedSettled = async (
    tasks: Array<() => Promise<unknown>>,
    chunkSize = DND_REQUEST_CONCURRENCY
  ) => {
    const results: PromiseSettledResult<unknown>[] = [];

    for (let index = 0; index < tasks.length; index += chunkSize) {
      const chunk = tasks.slice(index, index + chunkSize);
      const chunkResults = await Promise.allSettled(chunk.map((task) => task()));
      results.push(...chunkResults);
    }

    return results;
  };

  // ── DnD ──────────────────────────────────────────────────────────────
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } })
  );

  const [draggedId, setDraggedId] = useState<string | null>(null);
  const draggedPage = (() => {
    if (!draggedId) return null;
    const realId = draggedId.includes("::") ? draggedId.split("::")[0] : draggedId;
    return pages.find((p) => p.id === realId) ?? null;
  })();

  const handleDragStart = (event: DragStartEvent) => {
    setDraggedId(event.active.id as string);
  };

  const handleDragEnd = async (event: DragEndEvent) => {
    setDraggedId(null);
    const { active, over } = event;
    if (!over) return;

    // Parse compound IDs: "pageId::sectionId" → extract real pageId
    const rawActiveId = active.id as string;
    const activePageId = rawActiveId.includes("::") ? rawActiveId.split("::")[0] : rawActiveId;
    
    // Determine all pages being dragged
    const dragPageIds = selectedPageIds.has(activePageId) 
      ? Array.from(selectedPageIds) 
      : [activePageId];

    const rawOverId = over.id as string;
    const overParts = rawOverId.split("::");
    const overRealId = overParts[0];
    // For sortable thumbnails, the second token is the containing drop-zone/section id.
    let overId = overParts.length > 1 ? overParts[1] : rawOverId;

    // Check if dropped on a section
    let targetSectionId: string | null = null;
    let targetDocTypeId: string | null = null;

    // Check if overId is a section (search flat list which includes nested children)
    const matchedSec = allSectionsFlat.find((s) => s.id === overId);
    if (matchedSec) {
      targetSectionId = matchedSec.id;
      targetDocTypeId = matchedSec.document_type_id;
    } else {
      // Fallback for non-compound ids: infer by over-page status/legacy primary fields.
      const overPage = pages.find((p) => p.id === overRealId);
      if (overPage) {
        if (overPage.status === "unclassified") {
          overId = "unclassified-zone";
        } else if (overPage.status === "extra") {
          overId = "extra-zone";
        } else if (overPage.section_id && overPage.document_type_id) {
          targetSectionId = overPage.section_id;
          targetDocTypeId = overPage.document_type_id;
        }
      }
    }

    const isValidDropTarget =
      overId === "unclassified-zone" ||
      overId === "extra-zone" ||
      Boolean(targetSectionId && targetDocTypeId);

    if (!isValidDropTarget) return;

    const pageIdsToProcess =
      overId === "unclassified-zone"
        ? dragPageIds.filter((pageId) => {
            const dragPage = pages.find((page) => page.id === pageId);
            return dragPage?.status !== "unclassified";
          })
        : overId === "extra-zone"
          ? dragPageIds.filter((pageId) => {
              const dragPage = pages.find((page) => page.id === pageId);
              return dragPage?.status !== "extra";
            })
          : dragPageIds.filter((pageId) => {
              const dragPage = pages.find((page) => page.id === pageId);
              return !dragPage?.section_links?.some(
                (link) => link.section_id === targetSectionId
              );
            });

    setSelectedPageIds(new Set());

    if (pageIdsToProcess.length === 0) {
      toast("Las páginas seleccionadas ya están en esa sección");
      return;
    }

    applyOptimisticDrop(
      pageIdsToProcess,
      overId,
      targetSectionId,
      targetDocTypeId
    );

    const tasks = pageIdsToProcess.map((pageId) => () => {
      if (overId === "unclassified-zone") {
        return unclassifyPage(pageId);
      }

      if (overId === "extra-zone") {
        return markExtra(pageId);
      }

      const dragPage = pages.find((page) => page.id === pageId);
      const isAlreadyClassified = dragPage?.status === "classified";

      if (targetSectionId && targetDocTypeId) {
        if (isAlreadyClassified) {
          return addPageSectionLink(pageId, {
            section_id: targetSectionId,
            is_primary: false,
          });
        }

        return classifyPage(pageId, {
          document_type_id: targetDocTypeId,
          section_id: targetSectionId,
        });
      }

      return Promise.resolve(null);
    });

    const results = await runChunkedSettled(tasks);
    const successCount = results.filter(
      (result) => result.status === "fulfilled"
    ).length;
    const failureCount = results.length - successCount;

    if (successCount > 0) {
      if (overId === "unclassified-zone") {
        toast.success(
          successCount === 1
            ? "Página desclasificada"
            : `${successCount} páginas desclasificadas`
        );
      } else if (overId === "extra-zone") {
        toast.success(
          successCount === 1
            ? "Página movida a extras"
            : `${successCount} páginas movidas a extras`
        );
      } else if (pageIdsToProcess.length === 1) {
        const movedPage = pages.find((page) => page.id === pageIdsToProcess[0]);
        toast.success(
          movedPage?.status === "classified"
            ? "Página vinculada como referencia"
            : "Página clasificada"
        );
      } else {
        toast.success(`${successCount} páginas movidas`);
      }
    }

    if (failureCount > 0) {
      toast.error(
        failureCount === 1
          ? "1 página no se pudo mover"
          : `${failureCount} páginas no se pudieron mover`
      );
    }

    refresh();
  };

  // ── Reindex handlers ─────────────────────────────────────────────────
  const handleReindexPage = async (page: Page) => {
    try {
      await reindexPage(page.id);
      toast.success("Pagina en cola de re-indexacion");
      setTimeout(() => refresh(), 4000);
    } catch (error: unknown) {
      toast.error(getApiErrorMessage(error, "Error al reindexar pagina"));
    }
  };

  const handleReindexCase = async () => {
    if (!caseId) return;
    setReindexing(true);
    try {
      const result = await reindexCase(caseId);
      toast.success(`${result.queued} paginas en cola de re-indexacion`);
      setTimeout(() => refresh(), 5000);
      setTimeout(() => refresh(), 15000);
    } catch (error: unknown) {
      toast.error(getApiErrorMessage(error, "Error al reindexar caso"));
    }
    setReindexing(false);
  };

  // ── RAG query handler ──────────────────────────────────────────────
  const handleRagSearch = async () => {
    if (!caseId) return;
    await runSemanticSearch({
      query: ragQuestion,
      search: (question) => ragQuery(caseId, question),
      setSearching: setRagSearching,
      setResults: setRagResults,
      fallbackError: "Error en consulta semantica",
    });
  };

  const handleDeletePage = async (page: Page) => {
    const ok = window.confirm(
      `¿Eliminar definitivamente la página ${page.original_page_number} de "${page.original_filename}"?`
    );
    if (!ok) return;
    try {
      await deletePage(page.id);
      if (previewPage?.id === page.id) {
        setPreviewPage(null);
        setShowOcrText(false);
      }
      if (selectedPage?.id === page.id) {
        setSelectedPage(null);
      }
      toast.success("Página eliminada");
      refresh();
    } catch (error: unknown) {
      toast.error(getApiErrorMessage(error, "Error al eliminar pagina"));
    }
  };

  if (!caseId || !caseData) {
    return (
      <div className="flex items-center justify-center h-96 text-gray-400">
        Cargando…
      </div>
    );
  }

  // ── Tab content renderers ────────────────────────────────────────────

  const renderPagesTab = () => (
    <div className="flex flex-col gap-6">
      <FileUpload caseId={caseId} onUploaded={refresh} />

      {/* Stats bar */}
      <div className="flex items-center gap-6 text-sm text-gray-500 flex-wrap">
        <span>{pages.length} paginas totales</span>
        <span className="text-green-600">{classifiedPages.length} clasificadas</span>
        <span className="text-gray-400">{unclassifiedPages.length} sin clasificar</span>
        <span className="text-amber-500">{extraPages.length} extras</span>

        {/* Service status pills */}
        <div className="ml-auto flex items-center gap-2">
          {indexingConfigured && pages.some((p) => p.extraction_status === "done") && (
            <Tooltip content="Re-indexar todas las paginas extraidas en Pinecone">
              <button
                type="button"
                onClick={handleReindexCase}
                disabled={reindexing}
                className="inline-flex items-center gap-1.5 rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs font-medium text-gray-700 transition hover:border-gray-300 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${reindexing ? "animate-spin" : ""}`} />
                Reindexar caso
              </button>
            </Tooltip>
          )}

          {indexingConfigured && (
            <Tooltip content="Busqueda semantica en el contenido del caso">
              <button
                type="button"
                onClick={() => setShowRagPanel(!showRagPanel)}
                className={`inline-flex items-center gap-1.5 rounded-xl border px-3 py-2 text-xs font-medium transition ${
                  showRagPanel
                    ? "border-purple-600 bg-purple-600 text-white"
                    : "border-gray-200 bg-white text-gray-700 hover:border-purple-200 hover:bg-purple-50 hover:text-purple-700"
                }`}
              >
                <Search className="h-3.5 w-3.5" />
                Buscar en documentos
              </button>
            </Tooltip>
          )}
        </div>
      </div>

      {/* RAG Semantic Search Panel */}
      <AnimatePresence>
        {showRagPanel && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <GlassSurface filterId="glass-panel" className="rounded-xl p-4">
              <div className="flex items-center gap-2 mb-3">
                <Search className="w-4 h-4 text-purple-500" />
                <h4 className="text-sm font-semibold text-gray-700">Búsqueda</h4>
              </div>
              <div className="flex gap-2 mb-3">
                <input
                  className="flex-1 text-sm border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-purple-300 focus:border-purple-400 outline-none"
                  placeholder="Escribe tu pregunta sobre los documentos del caso…"
                  value={ragQuestion}
                  onChange={(e) => setRagQuestion(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleRagSearch()}
                />
                <button
                  onClick={handleRagSearch}
                  disabled={ragSearching || !ragQuestion.trim()}
                  className="flex items-center gap-1 px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition disabled:opacity-50 text-sm"
                >
                  {ragSearching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                  Buscar
                </button>
              </div>

              {ragResults.length > 0 && (
                <div className="flex flex-col gap-2 max-h-80 overflow-y-auto custom-scroll">
                  {ragResults.map((match, i) => {
                    const ragPageLabel = getRagMatchPageLabel(match);

                    return (
                      <div key={match.id} className="p-3 bg-white/60 rounded-lg border border-gray-200 text-xs">
                        <div className="flex items-center justify-between mb-1">
                          <span className="font-semibold text-gray-700">#{i + 1}</span>
                        </div>
                        {!!match.metadata.text && (
                          <p className="text-gray-600 whitespace-pre-wrap line-clamp-4 mb-1">
                            {String(match.metadata.text)}
                          </p>
                        )}
                        <div className="flex flex-wrap gap-1 mt-1">
                          {!!match.metadata.section_path_code && (
                            <span className="text-[9px] bg-indigo-50 text-indigo-600 rounded px-1.5 py-0.5">
                              {String(match.metadata.section_path_code)}
                            </span>
                          )}
                          {ragPageLabel && (
                            <span
                              className="inline-flex max-w-[240px] items-center rounded bg-gray-100 px-1.5 py-0.5 text-[9px] text-gray-500"
                              title={ragPageLabel}
                            >
                              <span className="truncate">{ragPageLabel}</span>
                            </span>
                          )}
                          {match.metadata.chunk_index != null && (
                            <span className="text-[9px] bg-gray-100 text-gray-500 rounded px-1.5 py-0.5">
                              chunk #{String(match.metadata.chunk_index)}
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </GlassSurface>
          </motion.div>
        )}
      </AnimatePresence>

      {/* All pages grid */}
      <motion.div layout className="flex flex-wrap gap-3 relative min-h-[200px]">
        {pagesLoading && (
          <div className="absolute inset-0 z-10 bg-white/50 backdrop-blur-[1px] flex items-center justify-center rounded-xl">
            <div className="flex flex-col items-center gap-2 bg-white p-4 rounded-xl shadow-lg border border-gray-100">
              <Loader2 className="w-8 h-8 animate-spin text-brand-600" />
              <p className="text-sm font-medium text-gray-600">Cargando páginas…</p>
            </div>
          </div>
        )}
        <AnimatePresence>
          {pages.map((page) => (
            <PageThumbnail
              key={page.id}
              page={page}
              selected={selectedPage?.id === page.id}
              onRemove={() => handleDeletePage(page)}
              removeTooltip="Eliminar página definitivamente"
              onClick={() => {
                setSelectedPage(page);
                setPreviewPage(page);
              }}
              showIndexStatus={indexingConfigured}
            />
          ))}
        </AnimatePresence>
        {pages.length === 0 && !pagesLoading && (
          <div className="w-full flex justify-center py-12">
            <EmptyState
              icon="documents"
              title="Sin documentos"
              description="Sube o arrastra tus archivos PDF o imágenes aquí para comenzar a organizar tu caso."
            />
          </div>
        )}
      </motion.div>
    </div>
  );

  // ── Recursive helpers for organize tab ──────────────────────────────
  /** Recursively find a section by id across the whole tree */
  const findSectionInTree = (
    sectionId: string,
    sections: Section[]
  ): Section | undefined => {
    for (const sec of sections) {
      if (sec.id === sectionId) return sec;
      if (sec.children?.length) {
        const found = findSectionInTree(sectionId, sec.children);
        if (found) return found;
      }
    }
    return undefined;
  };

  /** Render drop zones for a section and its children recursively */
  const renderSectionZones = (
    sec: Section,
    dt: DocumentType,
    depth: number
  ): React.ReactNode => {
    const sp = sectionPages(sec.id);
    const hasChildren = sec.children && sec.children.length > 0;
    return (
      <div key={sec.id} className="flex flex-col gap-2">
        <SectionDropZone
          sectionId={sec.id}
          label={sec.name}
          pathCode={sec.path_code || `${dt.code}.${sec.code}`}
          depth={depth}
          pages={sp}
          onRemovePage={(pid) => {
            const pg = pages.find((p) => p.id === pid);
            const linkCount = pg?.link_count ?? pg?.section_links?.length ?? 0;
            if (linkCount > 1) {
              // Page is in multiple sections — only remove THIS section's link
              removePageSectionLink(pid, sec.id)
                .then(() => { toast.success("Vínculo de sección removido"); refresh(); })
                .catch(() => toast.error("Error al desvincular"));
            } else {
              // Page is only in this one section — fully unclassify
              unclassifyPage(pid).then(refresh).catch(() => toast.error("Error al desclasificar"));
            }
          }}
          onClickPage={(p) => {
            setSelectedPage(p);
            setPreviewPage(p);
          }}
          selectedPageId={selectedPage?.id}
          multiSelectedIds={selectedPageIds}
          onToggleSelectPage={handleToggleSelectPage}
          onToggleSelectAll={handleToggleSelectAll}
        />
        {/* Render children indented */}
        {hasChildren &&
          sec.children
            .slice()
            .sort((a, b) => a.order - b.order)
            .map((child) => renderSectionZones(child, dt, depth + 1))}
      </div>
    );
  };

  const renderOrganizeTab = () => (
    <DndContext
      sensors={sensors}
      onDragStart={handleDragStart}
      onDragCancel={() => setDraggedId(null)}
      onDragEnd={handleDragEnd}
    >
      <div className="grid grid-cols-12 gap-5 h-[calc(100vh-200px)]">
        {/* Left: Document tree */}
        <div className="col-span-3 flex flex-col gap-4">
          <GlassSurface filterId="glass-panel" className="rounded-2xl p-4 flex-1 overflow-y-auto custom-scroll">
            <DocumentTree
              caseId={caseId}
              docTypes={docTypes}
              selectedSectionId={selectedSectionId}
              onSelectSection={(secId, dtId) => {
                setSelectedSectionId(secId);
                setSelectedDocTypeId(dtId);
              }}
              onRefresh={refresh}
            />
          </GlassSurface>

          {/* PDF Download Button */}
          <motion.button
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            onClick={() => downloadExportPdf(caseId)}
            className="flex items-center gap-3 p-3 rounded-2xl border border-white/40 bg-white/30 hover:bg-white/50 shadow-sm hover:shadow-md transition-[background-color,box-shadow] group text-left"
          >
            <div className="p-2 rounded-lg bg-red-50 group-hover:bg-red-100 transition shrink-0">
              <AnimatedPDF className="w-6 h-6" />
            </div>
            <div>
              <p className="font-semibold text-xs text-gray-800">Descargar PDF</p>
              <p className="text-[10px] text-gray-500 leading-tight mt-0.5">
                Consolidado con marcadores navegables
              </p>
            </div>
          </motion.button>
        </div>

        {/* Center: Section content / Drop zones — hierarchical */}
        <div className="col-span-6 flex flex-col gap-5 overflow-y-auto custom-scroll pr-2">
          {/* ─── When a specific section is selected ─── */}
          {selectedSectionId && selectedDocTypeId && (() => {
            const dt = docTypes.find((d) => d.id === selectedDocTypeId);
            if (!dt) return null;
            const sec = findSectionInTree(selectedSectionId, dt.sections);
            if (!sec) return null;

            return (
              <div className="flex flex-col gap-2">
                {/* Breadcrumb header */}
                <div className="flex items-center gap-1.5 text-xs text-gray-400 mb-1">
                  <FolderOpen className="w-3.5 h-3.5 text-amber-500" />
                  <span className="font-medium text-gray-600">{dt.code} – {dt.name}</span>
                  <span>›</span>
                  <span className="font-semibold text-gray-700">{sec.path_code || `${dt.code}.${sec.code}`} – {sec.name}</span>
                </div>
                {renderSectionZones(sec, dt, 0)}
              </div>
            );
          })()}

          {/* ─── When nothing selected → show full hierarchy ─── */}
          {!selectedSectionId &&
            docTypes
              .slice()
              .sort((a, b) => a.order - b.order)
              .map((dt) => (
                <div key={dt.id} className="flex flex-col gap-2">
                  {/* Document Type header card */}
                  <div className="flex items-center gap-2 px-3 py-2 bg-gradient-to-r from-gray-50 to-white rounded-lg border border-gray-200 shadow-sm sticky top-0 z-10">
                    <FolderOpen className="w-4 h-4 text-amber-500 shrink-0" />
                    <span className="text-sm font-bold text-gray-800 truncate">
                      {dt.code} – {dt.name}
                    </span>
                    <span className="ml-auto text-[10px] text-gray-400">
                      {dt.sections.length} {dt.sections.length === 1 ? "sección" : "secciones"}
                    </span>
                  </div>

                  {/* Sections tree */}
                  {dt.sections
                    .slice()
                    .sort((a, b) => a.order - b.order)
                    .map((sec) => renderSectionZones(sec, dt, 0))}

                  {dt.sections.length === 0 && (
                    <p className="text-xs text-gray-400 italic text-center py-3">
                      Sin secciones — agrega desde el panel izquierdo
                    </p>
                  )}
                </div>
              ))}

          {/* Extra pages zone */}
          <SectionDropZone
            sectionId="extra-zone"
            label="Páginas Extra"
            pages={extraPages}
            isSpecialZone
            onRemovePage={(pid) => {
              unclassifyPage(pid).then(refresh);
            }}
            onClickPage={(p) => {
              setSelectedPage(p);
              setPreviewPage(p);
            }}
            selectedPageId={selectedPage?.id}
            multiSelectedIds={selectedPageIds}
            onToggleSelectPage={handleToggleSelectPage}
            onToggleSelectAll={handleToggleSelectAll}
          />

          {docTypes.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 h-full">
              <EmptyState
                icon="organize"
                title="Sin estructura"
                description="Crea tipos de documento o aplica una plantilla desde el panel izquierdo para comenzar a clasificar."
              />
            </div>
          )}
        </div>

        {/* Right: Unclassified pages */}
        <div className="col-span-3 flex flex-col h-full min-h-0 overflow-hidden">
          <GlassSurface filterId="glass-panel" className="rounded-2xl p-4 flex-1 overflow-y-auto custom-scroll flex flex-col min-h-0 h-full w-full max-w-full">
            <div className="flex items-center justify-between mb-3 shrink-0">
              <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider">
                Sin Clasificar ({unclassifiedPages.length})
              </h3>
              {unclassifiedPages.length > 0 && (() => {
                const allSelected = unclassifiedPages.every(p => selectedPageIds.has(p.id));
                return (
                  <button
                    onClick={() => handleToggleSelectAll(unclassifiedPages.map(p => p.id), !allSelected)}
                    className="text-brand-500 hover:text-brand-600 transition-colors p-1 rounded-full hover:bg-brand-50"
                    title={allSelected ? "Deseleccionar todos" : "Seleccionar todos"}
                  >
                    {allSelected ? <CheckCircle2 className="w-4 h-4 fill-brand-100" /> : <div className="w-4 h-4 rounded-full border-2 border-brand-300" />}
                  </button>
                );
              })()}
            </div>
            <div className="flex-1 min-h-0">
              <SectionDropZone
                sectionId="unclassified-zone"
                label=""
                pages={unclassifiedPages}
                isSpecialZone
                onClickPage={(p) => {
                  setSelectedPage(p);
                  setPreviewPage(p);
                }}
                selectedPageId={selectedPage?.id}
                multiSelectedIds={selectedPageIds}
                onToggleSelectPage={handleToggleSelectPage}
              />
            </div>
          </GlassSurface>
        </div>
      </div>
      {/* Drag ghost that follows cursor across the whole workspace */}
      <DragOverlay zIndex={1200}>
        {draggedPage ? (() => {
          const isMultiDrag = selectedPageIds.has(draggedPage.id) && selectedPageIds.size > 1;
          const dragCount = isMultiDrag ? selectedPageIds.size : 1;
          return (
            <div className="relative">
              {isMultiDrag && (
                <div className="absolute -top-2 -right-2 bg-brand-600 text-white text-xs font-bold w-6 h-6 rounded-full flex items-center justify-center z-10 shadow-lg border-2 border-white">
                  {dragCount}
                </div>
              )}
              {isMultiDrag && (
                <div className="absolute inset-0 bg-white border border-brand-300 rounded-lg shadow-2xl rotate-3 transform translate-x-1 translate-y-1" />
              )}
              {isMultiDrag && (
                <div className="absolute inset-0 bg-white border border-brand-300 rounded-lg shadow-2xl rotate-6 transform translate-x-2 translate-y-2" />
              )}
              <div className="relative pointer-events-none w-28 rounded-lg border border-brand-300 bg-white shadow-2xl overflow-hidden z-0">
                <img
                  src={draggedPage.thumbnail_url}
                  alt={`${draggedPage.original_filename} p${draggedPage.original_page_number}`}
                  className="w-full h-36 object-cover"
                  draggable={false}
                />
                <div className="px-1.5 py-1 bg-white">
                  <p className="text-[10px] text-gray-500 truncate" title={draggedPage.original_filename}>
                    {draggedPage.original_filename}
                  </p>
                  <div className="flex items-center justify-between text-[10px] text-gray-400">
                    <span>p. {draggedPage.original_page_number}</span>
                    {draggedPage.subindex && <span className="font-semibold text-brand-600">{draggedPage.subindex}</span>}
                  </div>
                </div>
              </div>
            </div>
          );
        })() : null}
      </DragOverlay>
    </DndContext>
  );

  // ── Tabs definition ──────────────────────────────────────────────────
  const allTabs: { key: Tab; label: string; icon: React.ReactNode }[] = [
    { key: "pages", label: "Paginas", icon: <Upload className="w-4 h-4" /> },
    { key: "forms", label: "Formularios", icon: <FileText className="w-4 h-4" /> },
    { key: "organize", label: "Organizar", icon: <LayoutGrid className="w-4 h-4" /> },
    { key: "qc", label: "QC Checklist", icon: <CheckCircle2 className="w-4 h-4" /> },
  ];

  const userPermissions = user?.permissions ?? [];
  const tabs = allTabs.filter((t) =>
    userPermissions.includes(TAB_PERMISSIONS[t.key])
  );

  return (
    <div className="max-w-screen-2xl mx-auto px-4 py-4">
      {/* ── Header ────────────────────────────────────────────────── */}
      <div className="flex items-center gap-3 mb-4">
        <Link
          to="/"
          className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500"
        >
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div className="flex-1">
          <h1 className="text-xl font-bold text-gray-900">{caseData.name}</h1>
          {caseData.description && (
            <p className="text-xs text-gray-400">{caseData.description}</p>
          )}
        </div>
      </div>

      {/* ── Tab bar ───────────────────────────────────────────────── */}
      <div className="mb-8 flex justify-center">
        <GlassSurface
          filterId="glass-tabs"
          className="rounded-2xl p-2 w-full max-w-3xl"
          contentClassName="relative z-10 h-full w-full flex flex-wrap sm:flex-nowrap items-center justify-center gap-1.5"
        >
          {tabs.map((t) => {
            const isActive = tab === t.key;
            return (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={`relative inline-flex items-center justify-center gap-2 px-5 py-2.5 min-w-[150px] text-sm font-medium transition-colors rounded-xl ${
                  isActive ? "text-brand-800" : "text-gray-600 hover:text-gray-900"
                }`}
              >
                {isActive && (
                  <motion.div
                    layoutId="active-tab"
                    className="absolute inset-0 bg-white/65 shadow-sm border border-white/60 rounded-xl"
                    transition={{ type: "spring", stiffness: 360, damping: 32, mass: 0.8 }}
                    style={{ zIndex: -1 }}
                  />
                )}
                <span className="relative z-10">{t.icon}</span>
                <span className="relative z-10">{t.label}</span>
              </button>
            );
          })}
        </GlassSurface>
      </div>

      {/* ── Tab content ───────────────────────────────────────────── */}
      {tab === "pages" && renderPagesTab()}
      {tab === "organize" && renderOrganizeTab()}
      {tab === "qc" && (
        <div className="grid grid-cols-12 gap-4">
          <div className="col-span-12">
            <QCBuilderPanel
              caseId={caseId}
              caseData={caseData}
              pages={pages}
              onCaseUpdated={setCaseData}
              onRefresh={refresh}
              docTypes={docTypes}
            />
          </div>
        </div>
      )}
      {tab === "forms" && (
        <FormFillingPanel
          caseId={caseId}
          caseData={caseData}
          pages={pages}
          onCaseUpdated={setCaseData}
          onPagesUpdated={refresh}
        />
      )}

      {/* ── Full-size page preview modal ──────────────────────────── */}
      <AnimatePresence>
        {previewPage && (() => {
          return (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4 backdrop-blur-sm"
              onClick={() => { setPreviewPage(null); setShowOcrText(false); }}
            >
              <motion.div
                initial={{ scale: 0.95, opacity: 0, y: 10 }}
                animate={{ scale: 1, opacity: 1, y: 0 }}
                exit={{ scale: 0.95, opacity: 0, y: 10 }}
                transition={{ type: "spring", stiffness: 300, damping: 25 }}
                onClick={(e: React.MouseEvent) => e.stopPropagation()}
              >
                <GlassSurface
                  filterId="glass-panel"
                  className={`relative rounded-3xl shadow-2xl flex flex-col
                    ${showOcrText && previewPage.ocr_text ? "max-w-6xl w-full" : "max-w-3xl"} max-h-[92vh]`}
                >
                {/* Close button */}
                <Tooltip content="Cerrar vista previa">
                  <button
                    onClick={() => { setPreviewPage(null); setShowOcrText(false); }}
                    className="absolute top-3 right-3 z-10 bg-white/80 rounded-full p-1.5 hover:bg-gray-200 transition-colors"
                  >
                    <X className="w-5 h-5" />
                  </button>
                </Tooltip>

              {/* Content area */}
              <div className={`flex flex-1 overflow-hidden ${showOcrText && previewPage.ocr_text ? "flex-row" : ""}`}>
                {/* Image */}
                <div className={`overflow-auto ${showOcrText && previewPage.ocr_text ? "w-1/2 border-r" : "w-full"}`}>
                  <img
                    src={previewPage.file_url}
                    alt="Preview"
                    className="max-h-[80vh] w-auto mx-auto"
                  />
                </div>

                {/* OCR Text panel */}
                {showOcrText && previewPage.ocr_text && (
                  <div className="w-1/2 flex flex-col overflow-hidden">
                    <div className="px-3 py-2 bg-gray-50 border-b flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <FileText className="w-4 h-4 text-brand-600" />
                        <span className="text-xs font-semibold text-gray-700">
                          Texto Extraído
                        </span>
                        {previewPage.extraction_method && (
                          <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                            previewPage.extraction_method === "gemini_tables"
                              ? "bg-purple-100 text-purple-700"
                              : "bg-blue-100 text-blue-700"
                          }`}>
                            {previewPage.extraction_method === "gemini_tables"
                              ? "Tablas (Gemini)"
                              : "OCR (Gemini)"}
                          </span>
                        )}
                      </div>
                      <button
                        onClick={() => {
                          navigator.clipboard.writeText(previewPage.ocr_text || "");
                          toast.success("Texto copiado");
                        }}
                        className="p-1 rounded hover:bg-gray-200 text-gray-500"
                        title="Copiar texto"
                      >
                        <Copy className="w-3.5 h-3.5" />
                      </button>
                    </div>
                    <div className="flex-1 overflow-y-auto p-4 custom-scroll">
                      <pre className="text-xs text-gray-700 whitespace-pre-wrap font-mono leading-relaxed">
                        {previewPage.ocr_text}
                      </pre>
                    </div>
                  </div>
                )}
              </div>

              {/* Footer bar */}
              <div className="px-4 py-3 bg-gray-50 border-t flex items-center justify-between text-sm">
                <span className="text-gray-600 font-medium">
                  {previewPage.original_filename} &mdash; Pagina{" "}
                  {previewPage.original_page_number}
                </span>

                <div className="flex items-center gap-2">
                  {/* Extraction status & controls */}
                  {previewPage.extraction_status === "done" && previewPage.ocr_text && (
                    <button
                      onClick={() => setShowOcrText(!showOcrText)}
                      className={`flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg transition ${
                        showOcrText
                          ? "bg-brand-600 text-white"
                          : "bg-brand-50 text-brand-700 hover:bg-brand-100"
                      }`}
                    >
                      <FileText className="w-3.5 h-3.5" />
                      {showOcrText ? "Ocultar texto" : "Ver texto"}
                    </button>
                  )}

                  {previewPage.extraction_status === "error" && (
                    <span className="flex items-center gap-1 text-xs text-red-600">
                      <AlertCircle className="w-3.5 h-3.5" />
                      Error en extracción
                    </span>
                  )}

                  {previewPage.extraction_status === "processing" ? (
                    <span className="flex items-center gap-1 text-xs text-amber-600">
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      Extrayendo desde AI Autopilot…
                    </span>
                  ) : null}

                  {/* Search readiness status */}
                  {indexingConfigured && previewPage.extraction_status === "done" && (
                    <>
                      <div className="h-4 w-px bg-gray-300" />
                      {previewPage.index_status === "done" ? (
                        <span className="flex items-center gap-1 text-xs text-purple-600">
                          <Sparkles className="w-3.5 h-3.5" />
                          Lista para búsqueda
                        </span>
                      ) : previewPage.index_status === "processing" ? (
                        <span className="flex items-center gap-1 text-xs text-amber-600">
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          Preparando búsqueda…
                        </span>
                      ) : previewPage.index_status === "error" ? (
                        <span className="flex items-center gap-1 text-xs text-red-500">
                          <AlertCircle className="w-3.5 h-3.5" />
                          Error al preparar búsqueda
                        </span>
                      ) : null}
                      <button
                        onClick={() => handleReindexPage(previewPage)}
                        className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-md bg-indigo-50 text-indigo-600 hover:bg-indigo-100 transition"
                        title="Volver a preparar esta página para búsqueda"
                      >
                        <RefreshCw className="w-3 h-3" />
                        Reindexar
                      </button>
                    </>
                  )}

                  {/* Divider */}
                  <div className="h-4 w-px bg-gray-300" />

                  {previewPage.subindex && (
                    <span className="flex items-center gap-1 text-brand-600 font-semibold">
                      <Tag className="w-3.5 h-3.5" /> {previewPage.subindex}
                    </span>
                  )}
                  <span
                    className={`text-xs px-2 py-0.5 rounded-full ${
                      previewPage.status === "classified"
                        ? "bg-green-100 text-green-700"
                        : previewPage.status === "extra"
                          ? "bg-amber-100 text-amber-700"
                          : "bg-gray-100 text-gray-500"
                    }`}
                  >
                    {previewPage.status}
                  </span>
                </div>
              </div>
                </GlassSurface>
              </motion.div>
          </motion.div>
        );
      })()}
    </AnimatePresence>
    </div>
  );
}

