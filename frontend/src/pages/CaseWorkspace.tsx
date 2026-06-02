import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
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
  FileStack,
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
  Search,
  Send,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
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
  ragQuery,
  deletePage,
  downloadExportPdf,
} from "../api/client";

import FileUpload from "../components/FileUpload";
import PageThumbnail from "../components/PageThumbnail";
import DocumentTree from "../components/DocumentTree";
import SectionDropZone from "../components/SectionDropZone";
import QCBuilderPanel from "../components/checklist/QCBuilderPanel";
import { GlassButton } from "../components/glass/GlassButton";
import { SolidCard } from "../components/ui/SolidCard";
import { useAuth } from "../contexts/AuthContext";
import { AnimatedPDF } from "../components/ui/AnimatedPDF";

import FormFillingPanel from "../components/form-filling/FormFillingPanel";
import { getApiErrorMessage } from "../utils/apiErrors";
import { flattenSections } from "../utils/sections";
import { runSemanticSearch } from "../utils/semanticSearch";
import { extractSnippet, highlightTerms } from "../utils/ragSearchDisplay";

type Tab = "pages" | "organize" | "qc" | "forms";

const TAB_PERMISSIONS: Record<Tab, string> = {
  pages: "tab.pages",
  organize: "tab.organize",
  qc: "tab.qc_checklist",
  forms: "tab.export", // Fallback mapping for forms tab
};

const DND_REQUEST_CONCURRENCY = 8;
const PAGES_GRID_PAGE_SIZE = 27;

const getMetadataString = (metadata: Record<string, unknown>, key: string) => {
  const value = metadata[key];
  return typeof value === "string" ? value.trim() : "";
};

const normalizeRagLine = (value: string) =>
  value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();

const removeRepeatedRagHeading = (text: string, heading: string) => {
  const trimmedText = text.trim();
  const trimmedHeading = heading.trim();
  if (!trimmedText || !trimmedHeading) return trimmedText;

  const [firstLine = "", ...remainingLines] = trimmedText.split(/\r?\n/);
  if (normalizeRagLine(firstLine) !== normalizeRagLine(trimmedHeading)) {
    return trimmedText;
  }

  return remainingLines.join("\n").trim();
};

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
  // RAG query state
  const [ragQuestion, setRagQuestion] = useState("");
  const [ragResults, setRagResults] = useState<RagMatch[]>([]);
  const [ragSearching, setRagSearching] = useState(false);
  const [showRagPanel, setShowRagPanel] = useState(false);
  const [expandedRagResultIds, setExpandedRagResultIds] = useState<Set<string>>(new Set());

  const [pagesLoading, setPagesLoading] = useState(false);
  const [deletingPageIds, setDeletingPageIds] = useState<Set<string>>(() => new Set());
  const [pagesGridPage, setPagesGridPage] = useState(1);

  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);

  const closePreview = useCallback(() => {
    setPreviewPage(null);
    setShowOcrText(false);
  }, []);

  useEffect(() => {
    if (!previewPage) return;

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
      if (event.key === "Escape") closePreview();
    };
    document.addEventListener("keydown", onKeyDown);

    return () => {
      document.removeEventListener("keydown", onKeyDown);
      style.overflow = previous.overflow;
      style.position = previous.position;
      style.top = previous.top;
      style.width = previous.width;
      window.scrollTo(0, scrollY);
    };
  }, [previewPage, closePreview]);

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

  const pagesGridTotalPages = useMemo(
    () => Math.max(1, Math.ceil(pages.length / PAGES_GRID_PAGE_SIZE)),
    [pages.length]
  );

  const safePagesGridPage = Math.min(pagesGridPage, pagesGridTotalPages);

  const paginatedGridPages = useMemo(() => {
    const start = (safePagesGridPage - 1) * PAGES_GRID_PAGE_SIZE;
    return pages.slice(start, start + PAGES_GRID_PAGE_SIZE);
  }, [pages, safePagesGridPage]);

  const pagesGridRangeStart =
    pages.length === 0 ? 0 : (safePagesGridPage - 1) * PAGES_GRID_PAGE_SIZE + 1;
  const pagesGridRangeEnd = Math.min(
    safePagesGridPage * PAGES_GRID_PAGE_SIZE,
    pages.length
  );

  const goToPagesGridPage = useCallback((page: number) => {
    setPagesGridPage(Math.min(Math.max(page, 1), pagesGridTotalPages));
  }, [pagesGridTotalPages]);

  useEffect(() => {
    setPagesGridPage(1);
  }, [caseId]);

  useEffect(() => {
    if (pagesGridPage > pagesGridTotalPages) {
      setPagesGridPage(pagesGridTotalPages);
    }
  }, [pagesGridPage, pagesGridTotalPages]);

  const getRagMatchPageLabel = (match: RagMatch) => {
    const metadataFilename =
      typeof match.metadata.original_filename === "string"
        ? match.metadata.original_filename.trim()
        : "";

    const pageId = typeof match.metadata.page_id === "string" ? match.metadata.page_id : "";
    if (!pageId) {
      return metadataFilename || null;
    }

    const matchedPage = pages.find((page) => page.id === pageId);
    if (!matchedPage) {
      return metadataFilename || null;
    }

    return matchedPage.original_filename;
  };

  const getRagMatchPage = (match: RagMatch) => {
    const pageId = getMetadataString(match.metadata, "page_id");
    if (!pageId) return null;
    return pages.find((page) => page.id === pageId) ?? null;
  };

  const getRagMatchTitle = (match: RagMatch) =>
    getMetadataString(match.metadata, "section_name") ||
    getMetadataString(match.metadata, "section_label") ||
    getMetadataString(match.metadata, "document_type_name") ||
    "Resultado relacionado";

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

  // ── RAG query handler ──────────────────────────────────────────────
  const handleRagSearch = async () => {
    if (!caseId) return;
    setExpandedRagResultIds(new Set());
    await runSemanticSearch({
      query: ragQuestion,
      search: (question) => ragQuery(caseId, question),
      setSearching: setRagSearching,
      setResults: setRagResults,
      fallbackError: "No se pudo completar la búsqueda",
    });
  };

  const handleDeletePage = async (page: Page) => {
    if (deletingPageIds.has(page.id)) return;
    const ok = window.confirm(
      `¿Eliminar definitivamente la página ${page.original_page_number} de "${page.original_filename}"?`
    );
    if (!ok) return;
    setDeletingPageIds((prev) => new Set(prev).add(page.id));
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
    } finally {
      setDeletingPageIds((prev) => {
        const next = new Set(prev);
        next.delete(page.id);
        return next;
      });
    }
  };

  if (!caseId || !caseData) {
    return (
      <div className="flex items-center justify-center h-96 text-brand-500/70">
        Cargando…
      </div>
    );
  }

  // ── Tab content renderers ────────────────────────────────────────────

  const renderPagesTab = () => (
    <div className="flex flex-col gap-6">
      <div id="workspace-upload-zone">
        <FileUpload caseId={caseId} onUploaded={refresh} />
      </div>

      {/* Stats bar */}
      <SolidCard className="workspace-stats-bar rounded-2xl px-4 py-3">
        <div className="relative z-10 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap items-center gap-2.5">
            <span
              className="workspace-stat-badge"
              aria-label={`${pages.length} páginas totales`}
            >
              <FileStack aria-hidden="true" />
              <span>{pages.length} páginas totales</span>
            </span>
            <span
              className="workspace-stat-badge workspace-stat-badge--success"
              aria-label={`${classifiedPages.length} páginas clasificadas`}
            >
              <CheckCircle2 aria-hidden="true" />
              <span>{classifiedPages.length} clasificadas</span>
            </span>
            <span
              className="workspace-stat-badge workspace-stat-badge--pending"
              aria-label={`${unclassifiedPages.length} páginas sin clasificar`}
            >
              <FileText aria-hidden="true" />
              <span>{unclassifiedPages.length} sin clasificar</span>
            </span>
            <span
              className="workspace-stat-badge"
              aria-label={`${extraPages.length} páginas extra`}
            >
              <Tag aria-hidden="true" />
              <span>{extraPages.length} extras</span>
            </span>
          </div>

          {/* Service status pills */}
          <div className="flex flex-wrap items-center gap-2 lg:justify-end">
            {indexingConfigured && (
              <Tooltip content="Busca cualquier dato dentro de los documentos del caso">
                <GlassButton
                  type="button"
                  onClick={() => setShowRagPanel(!showRagPanel)}
                  variant="secondary"
                  size="sm"
                  iconOnly
                  aria-pressed={showRagPanel}
                  aria-label="Buscar en documentos"
                  isActive={showRagPanel}
                >
                  <Search className="h-4 w-4" aria-hidden="true" />
                </GlassButton>
              </Tooltip>
            )}
          </div>
        </div>
      </SolidCard>

      {/* RAG Semantic Search Panel */}
      <AnimatePresence>
        {showRagPanel && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <SolidCard className="rounded-xl p-4">
              <div className="flex items-center gap-2 mb-3">
                <Search className="w-4 h-4 text-brand-600" />
                <h4 className="text-sm font-semibold text-brand-800">Búsqueda</h4>
              </div>
              <div className="flex flex-col gap-2 sm:flex-row">
                <input
                  className="flex-1 text-sm border border-brand-100 rounded-lg px-3 py-2 bg-nova-snow text-brand-800 focus:ring-2 focus:ring-brand-300 focus:border-brand-400 outline-none"
                  placeholder="¿Dónde aparece el nombre del esposo?"
                  value={ragQuestion}
                  onChange={(e) => setRagQuestion(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleRagSearch()}
                  aria-label="Pregunta para buscar en documentos"
                />
                <Tooltip content="Buscar">
                  <GlassButton
                    type="button"
                    onClick={handleRagSearch}
                    disabled={!ragQuestion.trim()}
                    loading={ragSearching}
                    variant="primary"
                    size="sm"
                    iconOnly
                    aria-label="Buscar"
                  >
                    <Send className="w-4 h-4" aria-hidden="true" />
                  </GlassButton>
                </Tooltip>
              </div>

              {ragSearching && (
                <div className="flex flex-col gap-2" role="status" aria-live="polite">
                  <span className="sr-only">Buscando en documentos</span>
                  {Array.from({ length: 3 }).map((_, index) => (
                    <div key={`rag-skeleton-${index}`} className="ai-result-row" aria-hidden="true">
                      <div className="skeleton-block mb-3 h-3 w-44" />
                      <div className="skeleton-block mb-2 h-2.5 w-full" />
                      <div className="skeleton-block h-2.5 w-2/3" />
                    </div>
                  ))}
                </div>
              )}

              {!ragSearching && ragResults.length > 0 && (
                <div>
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <p className="text-xs font-semibold text-brand-700 py-[10px] px-[5px]">
                      {ragResults.length} {ragResults.length === 1 ? "resultado" : "resultados"}
                    </p>
                  </div>
                  <div className="flex flex-col gap-2 max-h-96 overflow-y-auto custom-scroll pr-1">
                    {ragResults.map((match) => {
                      const ragPageLabel = getRagMatchPageLabel(match);
                      const matchPage = getRagMatchPage(match);
                      const resultTitle = getRagMatchTitle(match);
                      const rawText = getMetadataString(match.metadata, "text");
                      const snippetText = removeRepeatedRagHeading(rawText, resultTitle);
                      const snippet = extractSnippet(snippetText, ragQuestion);
                      const isExpanded = expandedRagResultIds.has(match.id);
                      const displayText = isExpanded ? snippetText : snippet.text;
                      const canExpand = snippetText !== snippet.text;
                      const sectionPathCode = getMetadataString(match.metadata, "section_path_code");
                      const pageNumberValue =
                        matchPage?.original_page_number ??
                        match.metadata.page_number ??
                        match.metadata.original_page_number;
                      const pageNumberLabel =
                        typeof pageNumberValue === "number"
                          ? String(pageNumberValue)
                          : typeof pageNumberValue === "string" && pageNumberValue.trim()
                            ? pageNumberValue.trim()
                            : "";

                      return (
                        <div key={match.id} className="ai-result-row">
                          <div className="ai-result-row__header">
                            <div className="min-w-0">
                              <h5 className="mt-0.5 truncate text-sm font-semibold text-brand-800">
                                {resultTitle}
                              </h5>
                            </div>
                            {matchPage && (
                              <button
                                type="button"
                                onClick={() => {
                                  setSelectedPage(matchPage);
                                  setPreviewPage(matchPage);
                                  setShowOcrText(true);
                                }}
                                className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-brand-100 bg-white px-2.5 py-1.5 text-[11px] font-semibold text-brand-700 transition hover:border-brand-200 hover:bg-brand-50"
                              >
                                <FileText className="h-3.5 w-3.5" aria-hidden="true" />
                                Ver página
                              </button>
                            )}
                          </div>
                          {displayText ? (
                            <p
                              className={`mt-2 text-sm leading-relaxed text-brand-700 whitespace-pre-wrap ${
                                isExpanded ? "" : "line-clamp-4"
                              }`}
                            >
                              {highlightTerms(displayText, ragQuestion)}
                            </p>
                          ) : (
                            <p className="mt-2 text-sm text-brand-500">Sin texto disponible para este resultado.</p>
                          )}
                          <div className="mt-3 flex flex-wrap items-center gap-1.5">
                            {sectionPathCode && (
                              <span className="rag-result-meta-pill text-brand-700">
                                {sectionPathCode}
                              </span>
                            )}
                            {ragPageLabel && (
                              <span
                                className="rag-result-meta-pill max-w-[280px] text-brand-600"
                                title={ragPageLabel}
                              >
                                <span className="truncate">{ragPageLabel}</span>
                              </span>
                            )}
                            {pageNumberLabel && (
                              <span className="rag-result-meta-pill text-brand-500">
                                pág. {pageNumberLabel}
                              </span>
                            )}
                          </div>
                          {canExpand && (
                            <button
                              type="button"
                              aria-expanded={isExpanded}
                              onClick={() => {
                                setExpandedRagResultIds((prev) => {
                                  const next = new Set(prev);
                                  if (next.has(match.id)) next.delete(match.id);
                                  else next.add(match.id);
                                  return next;
                                });
                              }}
                              className="mt-2 text-xs font-semibold text-brand-600 transition hover:text-brand-800"
                            >
                              {isExpanded ? "Ver menos" : "Ver más"}
                            </button>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </SolidCard>
          </motion.div>
        )}
      </AnimatePresence>

      {/* All pages grid */}
      <div
        id="pages-grid"
        className="flex flex-wrap justify-center gap-3 relative min-h-[200px]"
      >
        {pagesLoading && pages.length === 0 && (
          <>
            {Array.from({ length: 12 }).map((_, index) => (
              <div
                key={`page-skeleton-${index}`}
                className="w-36 overflow-hidden rounded-xl border border-brand-100/70 bg-white/55 shadow-sm"
                aria-hidden="true"
              >
                <div className="skeleton-block h-48 rounded-none" />
                <div className="space-y-2 border-t border-white/50 px-2 py-2">
                  <div className="skeleton-block h-2.5 w-24" />
                  <div className="skeleton-block h-2 w-10" />
                </div>
              </div>
            ))}
            <div className="sr-only" role="status">
              Cargando páginas
            </div>
          </>
        )}
        {paginatedGridPages.map((page) => (
          <PageThumbnail
            key={page.id}
            page={page}
            disableAnimation
            selected={selectedPage?.id === page.id}
            onRemove={() => handleDeletePage(page)}
            removing={deletingPageIds.has(page.id)}
            removeTooltip="Eliminar página definitivamente"
            onClick={() => {
              setSelectedPage(page);
              setPreviewPage(page);
            }}
            showIndexStatus={indexingConfigured}
          />
        ))}
        {pages.length === 0 && !pagesLoading && (
          <div className="w-full flex justify-center py-12">
            <EmptyState
              icon="documents"
              title="Sin documentos"
              description="Sube o arrastra tus archivos PDF o imágenes aquí para comenzar a organizar tu caso."
              action={
                <button
                  type="button"
                  onClick={() => document.getElementById("workspace-upload-zone")?.scrollIntoView({ behavior: "smooth", block: "center" })}
                  className="inline-flex items-center gap-2 rounded-full border border-brand-100 bg-nova-snow px-5 py-2.5 text-sm font-semibold text-brand-700 shadow-sm transition hover:border-brand-200 hover:bg-brand-50"
                >
                  <Upload className="h-4 w-4" aria-hidden="true" />
                  Ir a subir archivos
                </button>
              }
            />
          </div>
        )}
      </div>

      {pages.length > PAGES_GRID_PAGE_SIZE && (
        <nav
          aria-label="Paginación de páginas del caso"
          className="flex flex-col items-center justify-center gap-3 sm:flex-row sm:justify-between"
        >
          <p className="text-xs font-medium text-brand-600">
            Mostrando {pagesGridRangeStart}&ndash;{pagesGridRangeEnd} de {pages.length} páginas
          </p>
          <div className="inline-flex items-center gap-1">
            <Tooltip content="Primera página">
              <GlassButton
                type="button"
                variant="secondary"
                size="xs"
                iconOnly
                onClick={() => goToPagesGridPage(1)}
                disabled={safePagesGridPage === 1}
                aria-label="Ir a la primera página"
                className="bg-white/75"
              >
                <ChevronsLeft className="h-4 w-4" aria-hidden="true" />
              </GlassButton>
            </Tooltip>
            <Tooltip content="Página anterior">
              <GlassButton
                type="button"
                variant="secondary"
                size="xs"
                iconOnly
                onClick={() => goToPagesGridPage(safePagesGridPage - 1)}
                disabled={safePagesGridPage === 1}
                aria-label="Página anterior"
                className="bg-white/75"
              >
                <ChevronLeft className="h-4 w-4" aria-hidden="true" />
              </GlassButton>
            </Tooltip>
            <span className="min-w-[5.5rem] px-2 text-center text-sm font-semibold text-brand-800">
              {safePagesGridPage} / {pagesGridTotalPages}
            </span>
            <Tooltip content="Página siguiente">
              <GlassButton
                type="button"
                variant="secondary"
                size="xs"
                iconOnly
                onClick={() => goToPagesGridPage(safePagesGridPage + 1)}
                disabled={safePagesGridPage === pagesGridTotalPages}
                aria-label="Página siguiente"
                className="bg-white/75"
              >
                <ChevronRight className="h-4 w-4" aria-hidden="true" />
              </GlassButton>
            </Tooltip>
            <Tooltip content="Última página">
              <GlassButton
                type="button"
                variant="secondary"
                size="xs"
                iconOnly
                onClick={() => goToPagesGridPage(pagesGridTotalPages)}
                disabled={safePagesGridPage === pagesGridTotalPages}
                aria-label="Ir a la última página"
                className="bg-white/75"
              >
                <ChevronsRight className="h-4 w-4" aria-hidden="true" />
              </GlassButton>
            </Tooltip>
          </div>
        </nav>
      )}
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
      <div className="grid grid-cols-12 gap-5 h-[calc(100vh-200px)] min-h-0">
        {/* Left: Document tree */}
        <div className="col-span-3 flex min-h-0 flex-col gap-4">
          <SolidCard className="rounded-2xl p-4 flex-1 min-h-0 overflow-y-auto custom-scroll">
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
          </SolidCard>

          {/* PDF Download Button */}
          <motion.button
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            onClick={() => downloadExportPdf(caseId)}
            className="solid-panel flex items-center gap-3 rounded-2xl p-3 text-left shadow-sm transition-[background-color,border-color,box-shadow] hover:border-brand-200 hover:bg-brand-50 hover:shadow-md"
          >
            <div className="shrink-0 rounded-lg bg-red-50 p-2 transition">
              <AnimatedPDF className="w-6 h-6" />
            </div>
            <div>
              <p className="font-semibold text-xs text-brand-800">Descargar PDF</p>
              <p className="text-[10px] text-brand-500 leading-tight mt-0.5">
                Consolidado con marcadores navegables
              </p>
            </div>
          </motion.button>
        </div>

        {/* Center: Section content / Drop zones — hierarchical */}
        <div className="col-span-5 flex min-h-0 flex-col gap-4 overflow-y-auto custom-scroll pr-1">
          {/* ─── When a specific section is selected ─── */}
          {selectedSectionId && selectedDocTypeId && (() => {
            const dt = docTypes.find((d) => d.id === selectedDocTypeId);
            if (!dt) return null;
            const sec = findSectionInTree(selectedSectionId, dt.sections);
            if (!sec) return null;

            return (
              <div className="flex flex-col gap-2">
                {/* Breadcrumb header */}
                <div className="flex items-center gap-1.5 text-xs text-brand-500/70 mb-1">
                  <FolderOpen className="w-3.5 h-3.5 text-brand-600" />
                  <span className="font-medium text-brand-600">{dt.code} – {dt.name}</span>
                  <span>›</span>
                  <span className="font-semibold text-brand-800">{sec.path_code || `${dt.code}.${sec.code}`} – {sec.name}</span>
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
                  <div className="flex items-center gap-2 px-3 py-2 bg-nova-ice/80 rounded-lg border border-white/50 shadow-sm sticky top-0 z-10">
                    <FolderOpen className="w-4 h-4 text-brand-600 shrink-0" />
                    <span className="text-sm font-bold text-brand-800 truncate">
                      {dt.code} – {dt.name}
                    </span>
                    <span className="ml-auto text-[10px] text-brand-500/70">
                      {dt.sections.length} {dt.sections.length === 1 ? "sección" : "secciones"}
                    </span>
                  </div>

                  {/* Sections tree */}
                  {dt.sections
                    .slice()
                    .sort((a, b) => a.order - b.order)
                    .map((sec) => renderSectionZones(sec, dt, 0))}

                  {dt.sections.length === 0 && (
                    <p className="text-xs text-brand-500/70 italic text-center py-3">
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
            <div className="rounded-xl border border-dashed border-brand-100 bg-white/40 px-4 py-6 text-center">
              <p className="text-sm font-medium text-brand-700">Zonas de clasificación</p>
              <p className="mt-1 text-xs leading-relaxed text-brand-500">
                Define la estructura en el panel izquierdo para ver aquí las secciones del expediente.
              </p>
            </div>
          )}
        </div>

        {/* Right: Unclassified pages */}
        <div className="col-span-4 flex min-h-0 flex-col overflow-hidden">
          <SolidCard className="rounded-2xl p-4 flex-1 overflow-y-auto custom-scroll flex flex-col min-h-0 h-full w-full max-w-full">
            <div className="flex items-center justify-between mb-3 shrink-0">
              <h3 className="text-xs font-bold text-brand-500 uppercase tracking-wider">
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
                fillHeight
                onClickPage={(p) => {
                  setSelectedPage(p);
                  setPreviewPage(p);
                }}
                selectedPageId={selectedPage?.id}
                multiSelectedIds={selectedPageIds}
                onToggleSelectPage={handleToggleSelectPage}
              />
            </div>
          </SolidCard>
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
                  <p className="text-[10px] text-brand-500 truncate" title={draggedPage.original_filename}>
                    {draggedPage.original_filename}
                  </p>
                  <div className="flex items-center justify-between text-[10px] text-brand-500/70">
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
    <>
    <div className="page-container">
      {/* ── Header ────────────────────────────────────────────────── */}
      <div className="dashboard-section-header mb-6">
        <div className="flex items-start gap-3">
          <Link
            to="/"
            aria-label="Volver al dashboard"
            className="mt-1 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-brand-600 transition-colors hover:bg-brand-50 hover:text-brand-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300"
          >
            <ArrowLeft className="w-5 h-5" aria-hidden="true" />
          </Link>
          <div className="min-w-0 flex-1">
            <h1 className="page-title">{caseData.name}</h1>
            {caseData.description && (
              <p className="page-subtitle">{caseData.description}</p>
            )}
          </div>
        </div>
      </div>

      {/* ── Tab bar ───────────────────────────────────────────────── */}
      <div className="mb-8 flex justify-center">
        <SolidCard className="nav-tabs-bar rounded-2xl p-2 w-full max-w-3xl">
          <div className="relative z-10 h-full w-full flex flex-wrap sm:flex-nowrap items-center justify-center gap-1.5">
          {tabs.map((t) => {
            const isActive = tab === t.key;
            return (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={`relative inline-flex items-center justify-center gap-2 px-5 py-2.5 min-w-[150px] text-sm font-medium transition-colors rounded-full ${
                  isActive ? "text-brand-800" : "text-brand-600 hover:text-brand-800"
                }`}
              >
                {isActive && (
                  <motion.div
                    layoutId="active-tab"
                    className="absolute inset-0 nav-tab-active rounded-full"
                    transition={{ type: "spring", stiffness: 360, damping: 32, mass: 0.8 }}
                    style={{ zIndex: -1 }}
                  />
                )}
                <span className="relative z-10">{t.icon}</span>
                <span className="relative z-10">{t.label}</span>
              </button>
            );
          })}
          </div>
        </SolidCard>
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

    </div>

      {/* ── Full-size page preview modal (portal, viewport-centered) ─ */}
      {createPortal(
        <AnimatePresence>
          {previewPage && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              role="dialog"
              aria-modal="true"
              aria-label="Vista previa de página"
              className="fixed inset-0 z-[80] flex items-center justify-center bg-nova-slate/60 p-4 sm:p-8"
              onClick={closePreview}
            >
              <motion.div
                initial={{ scale: 0.95, opacity: 0, y: 10 }}
                animate={{ scale: 1, opacity: 1, y: 0 }}
                exit={{ scale: 0.95, opacity: 0, y: 10 }}
                transition={{ type: "spring", stiffness: 300, damping: 25 }}
                className={`relative w-full max-h-[calc(100vh-2rem)] ${
                  showOcrText && previewPage.ocr_text ? "max-w-6xl" : "max-w-3xl"
                }`}
                onClick={(e: React.MouseEvent) => e.stopPropagation()}
              >
                <SolidCard
                  reading
                  className="relative rounded-3xl shadow-2xl flex flex-col max-h-[calc(100vh-2rem)] overflow-hidden"
                >
                {/* Close button */}
                <Tooltip content="Cerrar vista previa">
                  <button
                    onClick={closePreview}
                    className="absolute top-2 right-3 z-10 inline-flex h-7 w-7 items-center justify-center rounded-full bg-white/85 text-brand-600 transition-colors hover:bg-brand-50 hover:text-brand-800"
                    aria-label="Cerrar vista previa"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </Tooltip>

              {/* Content area */}
              <div className={`flex flex-1 min-h-0 overflow-hidden ${showOcrText && previewPage.ocr_text ? "flex-row" : ""}`}>
                {/* Image */}
                <div className={`overflow-auto ${showOcrText && previewPage.ocr_text ? "w-1/2 border-r" : "w-full"}`}>
                  <img
                    src={previewPage.file_url}
                    alt="Preview"
                    className="max-h-[calc(100vh-12rem)] w-auto mx-auto"
                  />
                </div>

                {/* OCR Text panel */}
                {showOcrText && previewPage.ocr_text && (
                  <div className="w-1/2 flex flex-col overflow-hidden min-h-0">
                    <div className="px-3 py-2 pr-12 bg-brand-50/70 border-b border-brand-100/70 flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <FileText className="w-4 h-4 text-brand-600" />
                        <span className="text-xs font-semibold text-brand-800">
                          Texto Extraído
                        </span>
                      </div>
                      <button
                        onClick={() => {
                          navigator.clipboard.writeText(previewPage.ocr_text || "");
                          toast.success("Texto copiado");
                        }}
                        className="p-1 rounded text-brand-500 transition-colors hover:bg-brand-100 hover:text-brand-700"
                        aria-label="Copiar texto extraído"
                        title="Copiar texto"
                      >
                        <Copy className="w-3.5 h-3.5" />
                      </button>
                    </div>
                    <div className="flex-1 overflow-y-auto p-4 custom-scroll">
                      <pre className="text-xs text-brand-700 whitespace-pre-wrap font-mono leading-relaxed">
                        {previewPage.ocr_text}
                      </pre>
                    </div>
                  </div>
                )}
              </div>

              {/* Footer bar */}
              <div className="px-4 py-3 bg-brand-50/70 border-t border-brand-100/70 flex items-center justify-between text-sm shrink-0">
                <span className="text-brand-600 font-medium">
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
                    <span className="flex items-center gap-1 text-xs text-brand-600">
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      Extrayendo desde AI Autopilot…
                    </span>
                  ) : null}

                  {/* Search readiness status */}
                  {indexingConfigured && previewPage.extraction_status === "done" && (
                    <>
                      <div className="h-4 w-px bg-brand-200" />
                      {previewPage.index_status === "processing" ? (
                        <span className="flex items-center gap-1 text-xs text-brand-600">
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          Preparando búsqueda…
                        </span>
                      ) : previewPage.index_status === "error" ? (
                        <span className="flex items-center gap-1 text-xs text-red-500">
                          <AlertCircle className="w-3.5 h-3.5" />
                          Error al preparar búsqueda
                        </span>
                      ) : null}
                    </>
                  )}

                  {/* Divider */}
                  <div className="h-4 w-px bg-brand-200" />

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
                          ? "bg-brand-100 text-brand-700"
                          : "bg-brand-50 text-brand-500"
                    }`}
                  >
                    {previewPage.status}
                  </span>
                </div>
              </div>
                </SolidCard>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>,
        document.body
      )}
    </>
  );
}

