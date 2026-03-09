import { useDroppable } from "@dnd-kit/core";
import {
  SortableContext,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { Inbox, FolderOpen, FileText, ChevronRight } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import type { Page } from "../types";
import PageThumbnail from "./PageThumbnail";

// ── Depth visual config ────────────────────────────────────────────────
const DEPTH_COLORS = [
  // depth 0 – root sections
  {
    border: "#3b82f6",      // blue-500
    borderIdle: "#bfdbfe",  // blue-200
    bg: "#eff6ff",          // blue-50
    bgIdle: "#ffffff",
    accent: "#3b82f6",
    label: "text-blue-700",
    badge: "bg-blue-100 text-blue-700",
    icon: "text-blue-400",
    empty: "text-blue-300",
  },
  // depth 1 – subsections
  {
    border: "#8b5cf6",      // violet-500
    borderIdle: "#ddd6fe",  // violet-200
    bg: "#f5f3ff",          // violet-50
    bgIdle: "#faf9ff",
    accent: "#8b5cf6",
    label: "text-violet-700",
    badge: "bg-violet-100 text-violet-700",
    icon: "text-violet-400",
    empty: "text-violet-300",
  },
  // depth 2+ – deep subsections
  {
    border: "#06b6d4",      // cyan-500
    borderIdle: "#a5f3fc",  // cyan-200
    bg: "#ecfeff",          // cyan-50
    bgIdle: "#f8fffe",
    accent: "#06b6d4",
    label: "text-cyan-700",
    badge: "bg-cyan-100 text-cyan-700",
    icon: "text-cyan-400",
    empty: "text-cyan-300",
  },
];

function depthConfig(depth: number) {
  return DEPTH_COLORS[Math.min(depth, DEPTH_COLORS.length - 1)];
}

interface Props {
  sectionId: string;
  label: string;
  pathCode?: string;
  depth?: number;
  pages: Page[];
  onRemovePage?: (pageId: string) => void;
  onClickPage?: (page: Page) => void;
  selectedPageId?: string | null;
  /** If true, renders a simpler style (used for special zones like "extra", "unclassified") */
  isSpecialZone?: boolean;
}

export default function SectionDropZone({
  sectionId,
  label,
  pathCode,
  depth = 0,
  pages,
  onRemovePage,
  onClickPage,
  selectedPageId,
  isSpecialZone = false,
}: Props) {
  const { setNodeRef, isOver } = useDroppable({ id: sectionId });

  const extractedCount = pages.filter((p) => p.extraction_status === "done").length;
  const dc = depthConfig(depth);

  // Special zones (unclassified / extra) use neutral styling
  if (isSpecialZone) {
    return (
      <motion.div
        ref={setNodeRef}
        animate={{
          scale: isOver ? 1.01 : 1,
          borderColor: isOver ? "#f59e0b" : "var(--glass-border)",
          backgroundColor: isOver ? "rgba(255, 251, 235, 0.4)" : "rgba(255, 255, 255, 0.2)",
        }}
        transition={{ duration: 0.2 }}
        className="rounded-xl border border-dashed p-3 min-h-[80px] shadow-sm glass-fallback"
      >
        {label && (
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
            {label}
          </h4>
        )}
        {pages.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-4 text-gray-300">
            <Inbox className="w-6 h-6 mb-1 opacity-50" />
            <span className="text-[10px]">Arrastra páginas aquí</span>
          </div>
        ) : (
          <SortableContext
            items={pages.map((p) => `${p.id}::${sectionId}`)}
            strategy={verticalListSortingStrategy}
          >
            <motion.div layout className="flex flex-wrap gap-2">
              <AnimatePresence>
                {pages.map((page) => (
                  <PageThumbnail
                    key={`${page.id}::${sectionId}`}
                    page={page}
                    sortableId={`${page.id}::${sectionId}`}
                    sortable
                    compact
                    selected={selectedPageId === page.id}
                    onRemove={onRemovePage ? () => onRemovePage(page.id) : undefined}
                    onClick={() => onClickPage?.(page)}
                  />
                ))}
              </AnimatePresence>
            </motion.div>
          </SortableContext>
        )}
      </motion.div>
    );
  }

  // ── Normal section drop zone with depth-based visuals ───────────────
  return (
    <motion.div
      ref={setNodeRef}
      animate={{
        scale: isOver ? 1.015 : 1,
        borderColor: isOver ? dc.border : "var(--glass-border)",
        backgroundColor: isOver ? dc.bg : "rgba(255, 255, 255, 0.3)",
      }}
      transition={{ duration: 0.2 }}
      className="rounded-xl border p-3 shadow-sm transition-shadow hover:shadow-glass glass-fallback"
      style={{
        marginLeft: depth > 0 ? `${depth * 16}px` : undefined,
        borderStyle: pages.length === 0 ? "dashed" : "solid",
      }}
    >
      {/* Header */}
      <div className="flex items-center gap-2 mb-2">
        {/* Depth breadcrumb trail */}
        {depth > 0 && (
          <div className="flex items-center gap-0.5">
            {Array.from({ length: depth }).map((_, i) => (
              <ChevronRight key={i} className={`w-3 h-3 ${dc.icon}`} />
            ))}
          </div>
        )}

        {/* Icon */}
        {depth === 0 ? (
          <FolderOpen className={`w-4 h-4 ${dc.icon} shrink-0`} />
        ) : (
          <FileText className={`w-3.5 h-3.5 ${dc.icon} shrink-0`} />
        )}

        {/* Path code badge */}
        {pathCode && (
          <span className={`text-[10px] font-mono font-bold px-1.5 py-0.5 rounded ${dc.badge}`}>
            {pathCode}
          </span>
        )}

        {/* Label */}
        <h4 className={`text-xs font-semibold ${dc.label} truncate flex-1`}>
          {label}
        </h4>

        {/* Page count / extracted count */}
        <span className="text-[10px] text-gray-400 shrink-0">
          {pages.length > 0
            ? `${pages.length} pág${pages.length !== 1 ? "s" : ""}`
            : "vacío"}
          {pages.length > 0 && extractedCount > 0 && (
            <span className="ml-1 text-purple-500">
              ({extractedCount} ext.)
            </span>
          )}
        </span>

      </div>

      {/* Pages grid — adapts to content */}
      {pages.length === 0 ? (
        <motion.div
          animate={{
            borderColor: isOver ? dc.border : "transparent",
          }}
          className={`flex flex-col items-center justify-center py-5 rounded-lg border-2 border-dashed ${dc.empty}`}
        >
          <Inbox className="w-6 h-6 mb-1 opacity-50" />
          <span className="text-[10px]">Arrastra páginas aquí</span>
        </motion.div>
      ) : (
        <SortableContext
          items={pages.map((p) => `${p.id}::${sectionId}`)}
          strategy={verticalListSortingStrategy}
        >
          <motion.div layout className="grid grid-cols-[repeat(auto-fill,minmax(96px,1fr))] gap-2">
            <AnimatePresence>
              {pages.map((page) => {
                // Determine if this page is shown as secondary (reference) in this section
                const isPrimary = page.section_links?.some(
                  (lk) => lk.section_id === sectionId && lk.is_primary
                ) ?? (page.section_id === sectionId);
                const isSecondary = !isPrimary && (page.link_count ?? 0) > 0;
                const compoundId = `${page.id}::${sectionId}`;
                return (
                  <PageThumbnail
                    key={compoundId}
                    page={page}
                    sortableId={compoundId}
                    sortable
                    compact
                    selected={selectedPageId === page.id}
                    onRemove={onRemovePage ? () => onRemovePage(page.id) : undefined}
                    onClick={() => onClickPage?.(page)}
                    isSecondary={isSecondary}
                  />
                );
              })}
            </AnimatePresence>
          </motion.div>
        </SortableContext>
      )}
    </motion.div>
  );
}
