import { memo, useEffect, useRef } from "react";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, X, Tag, Sparkles, Loader2, Link2, CheckCircle2 } from "lucide-react";
import { Tooltip } from "./ui/Tooltip";
import { motion } from "framer-motion";
import type { Page } from "../types";

interface Props {
  page: Page;
  /** When true the thumbnail is being used inside a sortable list */
  sortable?: boolean;
  /** If provided, show a remove button */
  onRemove?: () => void;
  /** Tooltip text for remove button */
  removeTooltip?: string;
  /** Click handler for preview */
  onClick?: () => void;
  /** Whether this page is currently selected */
  selected?: boolean;
  compact?: boolean;
  /** If provided, render as secondary (reference) style */
  isSecondary?: boolean;
  /** Override the sortable id (used to make IDs unique across multiple SortableContexts) */
  sortableId?: string;
  /** Show Pinecone index status indicator */
  showIndexStatus?: boolean;
  /** Multi-select state */
  multiSelected?: boolean;
  /** Multi-select toggle handler */
  onToggleSelect?: (selected: boolean) => void;
  /** Skip mount/exit motion (e.g. paginated grid swaps) */
  disableAnimation?: boolean;
  /** Show loading state on remove button */
  removing?: boolean;
}

function PageThumbnail({
  page,
  sortable = false,
  onRemove,
  removeTooltip = "Quitar página de la sección",
  onClick,
  selected = false,
  compact = false,
  isSecondary = false,
  sortableId,
  showIndexStatus = false,
  multiSelected = false,
  onToggleSelect,
  disableAnimation = false,
  removing = false,
}: Props) {
  const effectiveId = sortableId || page.id;
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: effectiveId, disabled: !sortable });

  // ── Click vs drag detection ──────────────────────────────────────
  // Track whether a drag just finished so we can suppress the click that follows.
  const wasDragging = useRef(false);
  const prevDragging = useRef(false);

  useEffect(() => {
    // Detect transition from dragging → not-dragging
    if (prevDragging.current && !isDragging) {
      wasDragging.current = true;
      // Clear after a tick so the next real click works
      requestAnimationFrame(() => {
        wasDragging.current = false;
      });
    }
    prevDragging.current = isDragging;
  }, [isDragging]);

  const handleClick = () => {
    // If a drag just ended, ignore this click
    if (wasDragging.current) return;
    onClick?.();
  };

  // ── Compose dnd-kit listeners with our onClick ───────────────────
  // We spread dnd-kit's listeners as-is (preserving onPointerDown etc.)
  // and add onClick separately — it only fires when the PointerSensor
  // did NOT activate (distance < 8px).
  const composedProps = sortable
    ? { ...attributes, ...listeners }
    : {};

  const style = sortable
    ? {
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.4 : 1,
      }
    : undefined;

  const statusColor =
    page.status === "classified"
      ? "bg-green-500"
      : page.status === "extra"
        ? "bg-brand-600"
        : "bg-brand-300";
  const extractionDone = page.extraction_status === "done";
  const extractionProcessing = page.extraction_status === "processing";
  const indexProcessing = showIndexStatus && extractionDone && page.index_status === "processing";
  const showProcessingIndicator = extractionProcessing || indexProcessing;
  const showCompletedIndicator =
    extractionDone && (!showIndexStatus || page.index_status === "done");
  const combinedIndicatorTitle = showProcessingIndicator
    ? indexProcessing
      ? "Preparando búsqueda en documentos"
      : "Procesando contenido"
    : showCompletedIndicator
      ? showIndexStatus
        ? "Contenido listo para búsqueda"
        : "Texto extraído"
      : undefined;

  return (
    <motion.div
      layout={!disableAnimation}
      initial={disableAnimation ? false : { opacity: 0, scale: 0.9 }}
      animate={disableAnimation ? undefined : { opacity: 1, scale: 1 }}
      exit={disableAnimation ? undefined : { opacity: 0, scale: 0.9 }}
      transition={disableAnimation ? undefined : { duration: 0.2 }}
      ref={sortable ? setNodeRef : undefined}
      style={style}
      {...composedProps}
      onClick={handleClick}
      className={`
        group relative rounded-xl border overflow-hidden
        transition-[background-color,border-color,box-shadow,transform] duration-200 touch-none solid-panel
        ${selected ? "ring-2 ring-brand-500 border-brand-400" : "border-white/40"}
        ${compact ? "w-24" : "w-36"}
        ${sortable ? "cursor-grab active:cursor-grabbing" : "cursor-pointer"}
        ${isDragging ? "shadow-2xl z-50 bg-white/60 border-brand-400 scale-105" : "shadow-sm hover:shadow-glass hover:-translate-y-0.5 bg-white/40"}
      `}
    >
      {/* Multi-select checkbox */}
      {onToggleSelect && (
        <div 
          className={`absolute top-1 left-1 z-20 transition-opacity ${multiSelected ? "opacity-100" : "opacity-0 group-hover:opacity-100"}`}
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => {
            e.stopPropagation();
            onToggleSelect(!multiSelected);
          }}
          title={multiSelected ? "Deseleccionar" : "Seleccionar"}
        >
          <div className="bg-white/90 rounded-full cursor-pointer hover:bg-brand-50 transition-colors flex items-center justify-center p-0.5">
            {multiSelected ? <CheckCircle2 className="w-4 h-4 text-brand-600 fill-brand-100" /> : <div className="w-4 h-4 rounded-full border-2 border-brand-300 m-[1px]" />}
          </div>
        </div>
      )}

      {/* Visual drag indicator — shown on hover to hint "draggable" */}
      {sortable && (
        <div className={`absolute top-1 z-10 rounded bg-white/80 p-0.5 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none ${onToggleSelect ? "left-6" : "left-1"}`}>
          <GripVertical className="w-3.5 h-3.5 text-brand-400" />
        </div>
      )}

      {/* Remove button */}
      {onRemove && (
        <Tooltip content={removeTooltip}>
          <button
            onClick={(e) => {
              e.stopPropagation();
              if (!removing) onRemove();
            }}
            onPointerDown={(e) => e.stopPropagation()}
            disabled={removing}
            aria-busy={removing || undefined}
            className="absolute top-1 right-1 z-10 rounded-full bg-white/80 p-0.5 opacity-0 group-hover:opacity-100 transition-opacity hover:bg-red-100 disabled:opacity-100 disabled:cursor-not-allowed"
          >
            {removing ? (
              <Loader2 className="w-3.5 h-3.5 text-red-500 animate-spin" aria-hidden="true" />
            ) : (
              <X className="w-3.5 h-3.5 text-red-500" />
            )}
          </button>
        </Tooltip>
      )}

      {/* Status dot */}
      <div className={`absolute top-1.5 right-1.5 w-2 h-2 rounded-full ${statusColor}`} />

      {/* Multi-link badge */}
      {(page.link_count ?? 0) > 1 && (
        <Tooltip content={`Esta página está en ${page.link_count} secciones`}>
          <div className="absolute bottom-[28px] right-1 z-10 flex items-center gap-0.5 bg-brand-600 text-white text-[8px] font-bold px-1.5 py-0.5 rounded-full shadow pointer-events-none">
            <Link2 className="w-2.5 h-2.5" />
            {page.link_count}
          </div>
        </Tooltip>
      )}

      {/* Secondary (reference) overlay */}
      {isSecondary && (
        <div className="absolute inset-0 bg-brand-500/10 pointer-events-none z-[1]" />
      )}

      {/* Thumbnail image */}
      <div className="bg-brand-50 select-none">
        <img
          src={page.thumbnail_url}
          alt={`${page.original_filename} p${page.original_page_number}`}
          className={`w-full object-cover pointer-events-none ${compact ? "h-32" : "h-48"}`}
          loading="lazy"
          draggable={false}
        />
      </div>

      {/* Combined processing/completion indicator */}
      {(showProcessingIndicator || showCompletedIndicator) && (
        <div
          className="absolute top-1.5 left-1.5 z-10 pointer-events-none"
          title={combinedIndicatorTitle}
        >
          {showProcessingIndicator ? (
            <Loader2 className="w-3 h-3 animate-spin text-brand-500" />
          ) : (
            <Sparkles className="w-3 h-3 text-brand-500" />
          )}
        </div>
      )}

      {/* Footer info */}
      <div className="px-1.5 py-1.5 bg-white/60 backdrop-blur-sm select-none border-t border-white/40">
        <p className="text-[10px] text-brand-500 truncate" title={page.original_filename}>
          {page.original_filename}
        </p>
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-brand-500/70">
            p. {page.original_page_number}
          </span>
          {page.subindex && (
            <span className="inline-flex items-center gap-0.5 text-[10px] font-semibold text-brand-600">
              <Tag className="w-2.5 h-2.5" />
              {page.subindex}
            </span>
          )}
        </div>
      </div>
    </motion.div>
  );
}

export default memo(PageThumbnail);
