import { useCallback, useEffect, useState } from "react";
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
  FileDown,
  LayoutGrid,
  Upload,
  X,
  Tag,
  Table2,
  Type,
  Loader2,
  CheckCircle2,
  AlertCircle,
  FileText,
  Copy,
  FolderOpen,
  Database,
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
  Checklist,
  DocumentType,
  ExtractionStatus as ExtStatusType,
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
  exportPdf,
} from "../api/client";

import FileUpload from "../components/FileUpload";
import PageThumbnail from "../components/PageThumbnail";
import DocumentTree from "../components/DocumentTree";
import SectionDropZone from "../components/SectionDropZone";
import QCBuilderPanel from "../components/checklist/QCBuilderPanel";
import { GlassSurface } from "../components/glass/GlassSurface";
import { AnimatedPDF } from "../components/ui/AnimatedPDF";

type Tab = "pages" | "organize" | "qc";

export default function CaseWorkspace() {
  const { caseId } = useParams<{ caseId: string }>();
  const navigate = useNavigate();

  const [caseData, setCaseData] = useState<Case | null>(null);
  const [docTypes, setDocTypes] = useState<DocumentType[]>([]);
  const [pages, setPages] = useState<Page[]>([]);
  const [checklists] = useState<Checklist[]>([]);
  const [tab, setTab] = useState<Tab>("pages");
  const [selectedSectionId, setSelectedSectionId] = useState<string | null>(null);
  const [selectedDocTypeId, setSelectedDocTypeId] = useState<string | null>(null);
  const [selectedPage, setSelectedPage] = useState<Page | null>(null);
  const [previewPage, setPreviewPage] = useState<Page | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [geminiConfigured, setGeminiConfigured] = useState<boolean | null>(null);
  const [pineconeConfigured, setPineconeConfigured] = useState(false);
  const [indexingConfigured, setIndexingConfigured] = useState(false);
  const [showOcrText, setShowOcrText] = useState(false);
  const [reindexing, setReindexing] = useState(false);

  // RAG query state
  const [ragQuestion, setRagQuestion] = useState("");
  const [ragResults, setRagResults] = useState<RagMatch[]>([]);
  const [ragSearching, setRagSearching] = useState(false);
  const [showRagPanel, setShowRagPanel] = useState(false);

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
    getPages(caseId).then(setPages);
  }, [caseId, refreshKey]);

  // Old checklist loading removed – QC Checklist is the primary system now

  useEffect(() => {
    getExtractionStatus()
      .then((r) => {
        setGeminiConfigured(r.gemini_configured ?? r.configured);
        setPineconeConfigured(r.pinecone_configured ?? false);
        setIndexingConfigured(r.indexing_configured ?? false);
      })
      .catch(() => {
        setGeminiConfigured(false);
        setPineconeConfigured(false);
        setIndexingConfigured(false);
      });
  }, []);

  // ── Derived data ─────────────────────────────────────────────────────
  const unclassifiedPages = pages.filter((p) => p.status === "unclassified");
  const extraPages = pages.filter((p) => p.status === "extra");
  const classifiedPages = pages.filter((p) => p.status === "classified");

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

  // Flatten all sections recursively from doc type tree for DnD lookup
  const flattenSections = (sections: import("../types").Section[]): import("../types").Section[] => {
    const result: import("../types").Section[] = [];
    for (const sec of sections) {
      result.push(sec);
      if (sec.children?.length) {
        result.push(...flattenSections(sec.children));
      }
    }
    return result;
  };

  const allSectionsFlat = docTypes.flatMap((dt) => flattenSections(dt.sections));

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
    const pageId = rawActiveId.includes("::") ? rawActiveId.split("::")[0] : rawActiveId;
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

    // If overId is "unclassified" drop zone
    if (overId === "unclassified-zone") {
      try {
        await unclassifyPage(pageId);
        refresh();
      } catch {
        toast.error("Error al desclasificar");
      }
      return;
    }

    // If overId is "extra" zone
    if (overId === "extra-zone") {
      try {
        await markExtra(pageId);
        refresh();
      } catch {
        toast.error("Error al marcar como extra");
      }
      return;
    }

    // If we found a target section, classify the page
    if (targetSectionId && targetDocTypeId) {
      try {
        const dragPage = pages.find((p) => p.id === pageId);
        const isAlreadyClassified = dragPage && dragPage.status === "classified";
        const isAlreadyLinkedHere = dragPage?.section_links?.some(
          (lk) => lk.section_id === targetSectionId
        );

        if (isAlreadyLinkedHere) {
          // Already linked to this section, nothing to do
          return;
        }

        if (isAlreadyClassified) {
          // Page already has a primary → add as secondary link
          await addPageSectionLink(pageId, {
            section_id: targetSectionId,
            is_primary: false,
          });
          toast.success("Página vinculada como referencia");
        } else {
          // First classification → set as primary
          await classifyPage(pageId, {
            document_type_id: targetDocTypeId,
            section_id: targetSectionId,
          });
        }
        refresh();
      } catch {
        toast.error("Error al clasificar");
      }
    }
  };

  // ── Reindex handlers ─────────────────────────────────────────────────
  const handleReindexPage = async (page: Page) => {
    try {
      await reindexPage(page.id);
      toast.success("Pagina en cola de re-indexacion");
      setTimeout(() => refresh(), 4000);
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || "Error al reindexar pagina");
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
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || "Error al reindexar caso");
    }
    setReindexing(false);
  };

  // ── RAG query handler ──────────────────────────────────────────────
  const handleRagSearch = async () => {
    if (!ragQuestion.trim() || !caseId) return;
    setRagSearching(true);
    try {
      const result = await ragQuery(caseId, ragQuestion.trim());
      setRagResults(result.matches);
      if (result.matches.length === 0) toast("Sin resultados para esa consulta");
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || "Error en consulta semantica");
    }
    setRagSearching(false);
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
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || "Error al eliminar página");
    }
  };

  // Get the DocumentType for a page (to check has_tables)
  const getPageDocType = (page: Page): DocumentType | undefined =>
    docTypes.find((dt) => dt.id === page.document_type_id);

  if (!caseId || !caseData) {
    return (
      <div className="flex items-center justify-center h-96 text-gray-400">
        Cargando...
      </div>
    );
  }

  // ── Tab content renderers ────────────────────────────────────────────

  const indexedPages = pages.filter((p) => p.index_status === "done");

  const renderPagesTab = () => (
    <div className="flex flex-col gap-6">
      <FileUpload caseId={caseId} onUploaded={refresh} />

      {/* Stats bar */}
      <div className="flex items-center gap-6 text-sm text-gray-500 flex-wrap">
        <span>{pages.length} paginas totales</span>
        <span className="text-green-600">{classifiedPages.length} clasificadas</span>
        <span className="text-gray-400">{unclassifiedPages.length} sin clasificar</span>
        <span className="text-amber-500">{extraPages.length} extras</span>

        {indexingConfigured && (
          <span className="flex items-center gap-1 text-indigo-600">
            <Database className="w-3.5 h-3.5" />
            {indexedPages.length} indexadas
          </span>
        )}

        {/* Service status pills */}
        <div className="ml-auto flex items-center gap-2">
          {pineconeConfigured && (
            <span className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-600 border border-indigo-200">
              <Database className="w-3 h-3" /> Pinecone
            </span>
          )}

          {indexingConfigured && pages.some((p) => p.extraction_status === "done") && (
            <Tooltip content="Re-indexar todas las paginas extraidas en Pinecone">
              <button
                onClick={handleReindexCase}
                disabled={reindexing}
                className="flex items-center gap-1 text-[10px] px-2 py-1 rounded-lg bg-indigo-100 text-indigo-700 hover:bg-indigo-200 transition disabled:opacity-50"
              >
                <RefreshCw className={`w-3 h-3 ${reindexing ? "animate-spin" : ""}`} />
                Reindexar caso
              </button>
            </Tooltip>
          )}

          {indexingConfigured && (
            <Tooltip content="Busqueda semantica en el contenido del caso">
              <button
                onClick={() => setShowRagPanel(!showRagPanel)}
                className={`flex items-center gap-1 text-[10px] px-2 py-1 rounded-lg transition ${
                  showRagPanel
                    ? "bg-purple-600 text-white"
                    : "bg-purple-50 text-purple-700 hover:bg-purple-100"
                }`}
              >
                <Search className="w-3 h-3" />
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
                <h4 className="text-sm font-semibold text-gray-700">Busqueda Semantica (RAG)</h4>
              </div>
              <div className="flex gap-2 mb-3">
                <input
                  className="flex-1 text-sm border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-purple-300 focus:border-purple-400 outline-none"
                  placeholder="Escribe tu pregunta sobre los documentos del caso..."
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
                  {ragResults.map((match, i) => (
                    <div key={match.id} className="p-3 bg-white/60 rounded-lg border border-gray-200 text-xs">
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-semibold text-gray-700">#{i + 1}</span>
                        <span className="text-[10px] text-purple-600 font-mono">
                          score: {match.score.toFixed(3)}
                        </span>
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
                        {!!match.metadata.page_id && (
                          <span className="text-[9px] bg-gray-100 text-gray-500 rounded px-1.5 py-0.5">
                            page: {String(match.metadata.page_id).slice(0, 8)}...
                          </span>
                        )}
                        {match.metadata.chunk_index != null && (
                          <span className="text-[9px] bg-gray-100 text-gray-500 rounded px-1.5 py-0.5">
                            chunk #{String(match.metadata.chunk_index)}
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </GlassSurface>
          </motion.div>
        )}
      </AnimatePresence>

      {/* All pages grid */}
      <motion.div layout className="flex flex-wrap gap-3">
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
        {pages.length === 0 && (
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
          <motion.a
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            href={exportPdf(caseId)}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-3 p-3 rounded-2xl border border-white/40 bg-white/30 hover:bg-white/50 shadow-sm hover:shadow-md transition-all group"
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
          </motion.a>
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
        <GlassSurface filterId="glass-panel" className="col-span-3 rounded-2xl p-4 overflow-y-auto custom-scroll">
          <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-3">
            Sin Clasificar ({unclassifiedPages.length})
          </h3>
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
          />
        </GlassSurface>
      </div>
      {/* Drag ghost that follows cursor across the whole workspace */}
      <DragOverlay zIndex={1200}>
        {draggedPage ? (
          <div className="pointer-events-none w-28 rounded-lg border border-brand-300 bg-white shadow-2xl overflow-hidden">
            <img
              src={`/storage/${draggedPage.thumbnail_path}`}
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
        ) : null}
      </DragOverlay>
    </DndContext>
  );

  // ── Tabs definition ──────────────────────────────────────────────────
  const tabs: { key: Tab; label: string; icon: React.ReactNode }[] = [
    { key: "pages", label: "Paginas", icon: <Upload className="w-4 h-4" /> },
    { key: "organize", label: "Organizar", icon: <LayoutGrid className="w-4 h-4" /> },
    { key: "qc", label: "QC Checklist", icon: <CheckCircle2 className="w-4 h-4" /> },
  ];

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
        <div className="flex items-center gap-4 text-xs text-gray-500">
          <span>{pages.length} paginas</span>
          <span className="text-green-600">
            {classifiedPages.length} clasificadas
          </span>
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
            <QCBuilderPanel caseId={caseId} onRefresh={refresh} docTypes={docTypes} />
          </div>
        </div>
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
                    src={`/storage/${previewPage.file_path}`}
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
                      Extrayendo desde AI Autopilot...
                    </span>
                  ) : null}

                  {/* Reindex / Index status */}
                  {indexingConfigured && previewPage.extraction_status === "done" && (
                    <>
                      <div className="h-4 w-px bg-gray-300" />
                      {previewPage.index_status === "done" ? (
                        <span className="flex items-center gap-1 text-[10px] text-indigo-600">
                          <Database className="w-3 h-3" />
                          Indexada ({previewPage.indexed_vector_count} vectores)
                        </span>
                      ) : previewPage.index_status === "processing" ? (
                        <span className="flex items-center gap-1 text-[10px] text-amber-600">
                          <Loader2 className="w-3 h-3 animate-spin" />
                          Indexando...
                        </span>
                      ) : previewPage.index_status === "error" ? (
                        <span className="flex items-center gap-1 text-[10px] text-red-500">
                          <AlertCircle className="w-3 h-3" />
                          Error de indexacion
                        </span>
                      ) : null}
                      <button
                        onClick={() => handleReindexPage(previewPage)}
                        className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-md bg-indigo-50 text-indigo-600 hover:bg-indigo-100 transition"
                        title="Re-indexar esta pagina en Pinecone"
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

