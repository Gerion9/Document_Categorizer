import { useEffect, useState } from "react";
import {
  CheckCircle2,
  Circle,
  XCircle,
  MinusCircle,
  Plus,
  Trash2,
  Link2,
  Unlink,
  ChevronDown,
  ChevronRight,
  MapPin,
  Navigation,
  X,
} from "lucide-react";
import toast from "react-hot-toast";
import { motion, AnimatePresence } from "framer-motion";
import { EmptyState } from "./ui/EmptyState";
import { Tooltip } from "./ui/Tooltip";
import type { Checklist, ChecklistItem, DocumentType, Page, Section } from "../types";
import {
  createChecklist,
  createChecklistItem,
  updateChecklistItem,
  deleteChecklistItem,
  deleteChecklist,
  addEvidence,
  removeEvidence,
  upsertItemTargets,
} from "../api/client";

interface Props {
  caseId: string;
  checklists: Checklist[];
  /** Currently selected page that can be linked as evidence */
  selectedPage: Page | null;
  onRefresh: () => void;
  /** All document types (with sections tree) for the target section picker */
  docTypes?: DocumentType[];
  /** Callback to navigate to a section in the Organize tab */
  onNavigateToSection?: (sectionId: string, docTypeId: string) => void;
}

const STATUS_ICON: Record<string, React.ReactNode> = {
  pending: <Circle className="w-4 h-4 text-gray-400" />,
  complete: <CheckCircle2 className="w-4 h-4 text-green-500" />,
  incomplete: <XCircle className="w-4 h-4 text-red-500" />,
  na: <MinusCircle className="w-4 h-4 text-gray-300" />,
};

const NEXT_STATUS: Record<string, string> = {
  pending: "complete",
  complete: "incomplete",
  incomplete: "na",
  na: "pending",
};

// Flatten sections from a doc type tree
function flattenSections(sections: Section[]): Section[] {
  const result: Section[] = [];
  for (const sec of sections) {
    result.push(sec);
    if (sec.children?.length) {
      result.push(...flattenSections(sec.children));
    }
  }
  return result;
}

// Collect all descendant IDs of a section (recursive)
function getDescendantIds(sectionId: string, allSections: Section[]): string[] {
  const ids: string[] = [];
  const directChildren = allSections.filter((s) => s.parent_section_id === sectionId);
  for (const child of directChildren) {
    ids.push(child.id);
    ids.push(...getDescendantIds(child.id, allSections));
  }
  return ids;
}

// Check if a section has ALL its children selected (for visual indicator)
function getSelectionState(
  sectionId: string,
  selectedIds: string[],
  allSections: Section[]
): "none" | "partial" | "all" {
  const descendants = getDescendantIds(sectionId, allSections);
  if (descendants.length === 0) return selectedIds.includes(sectionId) ? "all" : "none";
  const selectedDescendants = descendants.filter((id) => selectedIds.includes(id));
  const selfSelected = selectedIds.includes(sectionId);
  if (selfSelected && selectedDescendants.length === descendants.length) return "all";
  if (selfSelected || selectedDescendants.length > 0) return "partial";
  return "none";
}

export default function ChecklistPanel({
  caseId,
  checklists,
  selectedPage,
  onRefresh,
  docTypes = [],
  onNavigateToSection,
}: Props) {
  const [addingCl, setAddingCl] = useState(false);
  const [clName, setClName] = useState("");
  const [addingItemFor, setAddingItemFor] = useState<string | null>(null);
  const [itemDesc, setItemDesc] = useState("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [mappingItem, setMappingItem] = useState<string | null>(null);

  const allSections = docTypes.flatMap((dt) => flattenSections(dt.sections));

  const toggleExpand = (id: string) =>
    setExpanded((p) => ({ ...p, [id]: !p[id] }));

  const handleCreateChecklist = async () => {
    if (!clName.trim()) return;
    await createChecklist(caseId, clName.trim());
    setClName("");
    setAddingCl(false);
    onRefresh();
  };

  const handleCreateItem = async (clId: string) => {
    if (!itemDesc.trim()) return;
    const cl = checklists.find((c) => c.id === clId);
    await createChecklistItem(clId, {
      description: itemDesc.trim(),
      order: cl?.items.length ?? 0,
    });
    setItemDesc("");
    setAddingItemFor(null);
    onRefresh();
  };

  const cycleStatus = async (item: ChecklistItem) => {
    await updateChecklistItem(item.id, {
      status: NEXT_STATUS[item.status] as ChecklistItem["status"],
    });
    onRefresh();
  };

  const handleLinkEvidence = async (itemId: string) => {
    if (!selectedPage) {
      toast.error("Selecciona una pagina primero");
      return;
    }
    await addEvidence(itemId, { page_id: selectedPage.id });
    toast.success("Evidencia vinculada");
    onRefresh();
  };

  const handleToggleTarget = async (itemId: string, sectionId: string, current: string[]) => {
    const descendantIds = getDescendantIds(sectionId, allSections);
    const allRelated = [sectionId, ...descendantIds];

    let next: string[];
    if (current.includes(sectionId)) {
      // Unchecking: remove this section AND all its descendants
      next = current.filter((id) => !allRelated.includes(id));
    } else {
      // Checking: add this section AND all its descendants
      const toAdd = allRelated.filter((id) => !current.includes(id));
      next = [...current, ...toAdd];
    }

    try {
      await upsertItemTargets(itemId, next);
      onRefresh();
    } catch {
      toast.error("Error al actualizar secciones destino");
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold text-gray-700 uppercase tracking-wider">
          Checklists
        </h3>
        <Tooltip content="Crear nuevo checklist">
          <button
            onClick={() => setAddingCl(true)}
            className="p-1 rounded hover:bg-gray-200 text-brand-600 transition"
          >
            <Plus className="w-4 h-4" />
          </button>
        </Tooltip>
      </div>

      {addingCl && (
        <div className="flex gap-1">
          <input
            className="flex-1 text-xs border rounded px-2 py-1"
            placeholder="Nombre del checklist"
            value={clName}
            onChange={(e) => setClName(e.target.value)}
            autoFocus
            onKeyDown={(e) => e.key === "Enter" && handleCreateChecklist()}
          />
          <button
            onClick={handleCreateChecklist}
            className="text-xs bg-brand-600 text-white rounded px-2 hover:bg-brand-700"
          >
            OK
          </button>
          <button
            onClick={() => setAddingCl(false)}
            className="text-xs bg-gray-200 rounded px-2"
          >
            X
          </button>
        </div>
      )}

      {checklists.map((cl) => (
        <div key={cl.id} className="border rounded-lg bg-white">
          {/* Checklist header */}
          <div
            className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-gray-50"
            onClick={() => toggleExpand(cl.id)}
          >
            {expanded[cl.id] ? (
              <ChevronDown className="w-3.5 h-3.5 text-gray-400" />
            ) : (
              <ChevronRight className="w-3.5 h-3.5 text-gray-400" />
            )}
            <span className="text-sm font-semibold flex-1">{cl.name}</span>
            <span className="text-[10px] text-gray-400">
              {cl.completion_pct.toFixed(0)}%
            </span>
            {/* Progress bar */}
            <div className="w-16 h-1.5 bg-gray-200 rounded-full overflow-hidden">
              <div
                className="h-full bg-green-500 rounded-full transition-all"
                style={{ width: `${cl.completion_pct}%` }}
              />
            </div>
            <Tooltip content="Eliminar checklist">
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  if (confirm("Eliminar checklist?")) {
                    deleteChecklist(cl.id).then(onRefresh);
                  }
                }}
                className="p-0.5 text-gray-400 hover:text-red-500 transition-colors"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </Tooltip>
          </div>

          {/* Items */}
          {expanded[cl.id] && (
            <div className="px-3 pb-2 flex flex-col gap-1">
              {cl.items.map((item) => {
                const currentTargetIds = item.target_sections?.map((t) => t.section_id) ?? [];
                return (
                  <div key={item.id} className="group">
                    <div className="flex items-start gap-1.5">
                      <Tooltip content={`Estado actual: ${item.status}. Clic para cambiar estado.`}>
                        <button
                          onClick={() => cycleStatus(item)}
                          className="mt-0.5 shrink-0 transition-transform hover:scale-110"
                        >
                          {STATUS_ICON[item.status]}
                        </button>
                      </Tooltip>
                      <span
                        className={`text-xs flex-1 ${
                          item.status === "complete"
                            ? "line-through text-gray-400"
                            : "text-gray-700"
                        }`}
                      >
                        {item.description}
                      </span>
                      {/* Map target sections button */}
                      <Tooltip content="Mapear a secciones destino del documento">
                        <button
                          onClick={() => setMappingItem(mappingItem === item.id ? null : item.id)}
                          className={`p-0.5 rounded transition-colors ${
                            mappingItem === item.id
                              ? "text-indigo-600 bg-indigo-50"
                              : currentTargetIds.length > 0
                                ? "text-indigo-500"
                                : "opacity-0 group-hover:opacity-100 text-gray-400 hover:text-indigo-500"
                          }`}
                        >
                          <MapPin className="w-3.5 h-3.5" />
                        </button>
                      </Tooltip>
                      <Tooltip content="Vincular página seleccionada como evidencia">
                        <button
                          onClick={() => handleLinkEvidence(item.id)}
                          className="opacity-0 group-hover:opacity-100 p-0.5 text-gray-400 hover:text-brand-600 transition-colors"
                        >
                          <Link2 className="w-3.5 h-3.5" />
                        </button>
                      </Tooltip>
                      <Tooltip content="Eliminar ítem del checklist">
                        <button
                          onClick={() => {
                            deleteChecklistItem(item.id).then(onRefresh);
                          }}
                          className="opacity-0 group-hover:opacity-100 p-0.5 text-gray-400 hover:text-red-500 transition-colors"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </Tooltip>
                    </div>

                    {/* Target sections chips */}
                    {item.target_sections && item.target_sections.length > 0 && (
                      <div className="ml-6 mt-0.5 flex flex-wrap gap-1">
                        {item.target_sections.map((t) => (
                          <Tooltip key={t.id} content={`Ir a sección: ${t.section_path_code || t.section_name}`}>
                            <button
                              onClick={() => {
                                if (onNavigateToSection) {
                                  const sec = allSections.find((s) => s.id === t.section_id);
                                  if (sec) onNavigateToSection(sec.id, sec.document_type_id);
                                }
                              }}
                              className="inline-flex items-center gap-0.5 text-[10px] bg-indigo-50 text-indigo-700 rounded px-1.5 py-0.5 hover:bg-indigo-100 transition"
                            >
                              <Navigation className="w-2.5 h-2.5" />
                              {t.section_path_code || t.section_name}
                            </button>
                          </Tooltip>
                        ))}
                      </div>
                    )}

                    {/* Target section picker (inline) */}
                    {mappingItem === item.id && (
                      <div className="ml-6 mt-1 p-2 bg-indigo-50 rounded-lg border border-indigo-200 max-h-40 overflow-y-auto custom-scroll">
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-[10px] font-semibold text-indigo-700 uppercase">
                            Secciones destino
                          </span>
                          <button onClick={() => setMappingItem(null)} className="text-gray-400 hover:text-gray-600">
                            <X className="w-3 h-3" />
                          </button>
                        </div>
                        {allSections.length === 0 ? (
                          <p className="text-[10px] text-gray-400 italic">Crea secciones primero</p>
                        ) : (
                          <div className="flex flex-col gap-0.5">
                            {allSections.map((sec) => {
                              const dt = docTypes.find((d) => d.id === sec.document_type_id);
                              const label = sec.path_code || `${dt?.code || ""}${sec.code}`;
                              const isTarget = currentTargetIds.includes(sec.id);
                              const selState = getSelectionState(sec.id, currentTargetIds, allSections);
                              const hasKids = allSections.some((s) => s.parent_section_id === sec.id);
                              return (
                                <label
                                  key={sec.id}
                                  className={`flex items-center gap-1.5 text-[10px] px-1.5 py-0.5 rounded cursor-pointer transition ${
                                    selState === "all" ? "bg-indigo-100 text-indigo-800"
                                    : selState === "partial" ? "bg-indigo-50 text-indigo-700"
                                    : "hover:bg-indigo-100/50 text-gray-600"
                                  }`}
                                  style={{ paddingLeft: `${4 + (sec.depth || 0) * 12}px` }}
                                >
                                  <input
                                    type="checkbox"
                                    checked={isTarget}
                                    ref={(el) => {
                                      if (el) el.indeterminate = selState === "partial" && !isTarget;
                                    }}
                                    onChange={() => handleToggleTarget(item.id, sec.id, currentTargetIds)}
                                    className="rounded border-indigo-300 text-indigo-600 focus:ring-indigo-500 w-3 h-3"
                                  />
                                  <span className="font-mono">{label}</span>
                                  <span className="text-gray-400">{sec.name}</span>
                                  {hasKids && isTarget && (
                                    <span className="text-[8px] text-indigo-400 ml-auto">+hijos</span>
                                  )}
                                </label>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Evidence links */}
                    {item.evidence_links.length > 0 && (
                      <div className="ml-6 mt-0.5 flex flex-wrap gap-1">
                        {item.evidence_links.map((ev) => (
                          <span
                            key={ev.id}
                            className="inline-flex items-center gap-0.5 text-[10px] bg-brand-50 text-brand-700 rounded px-1.5 py-0.5"
                          >
                            {ev.page?.subindex
                              ? `${ev.page.subindex} p${ev.page.order_in_section ?? "?"}`
                              : ev.page
                                ? `${ev.page.original_filename} p${ev.page.original_page_number}`
                                : "?"}
                            <Tooltip content="Quitar evidencia vinculada">
                              <button
                                onClick={() =>
                                  removeEvidence(ev.id).then(onRefresh)
                                }
                                className="hover:text-red-500 transition-colors"
                              >
                                <Unlink className="w-2.5 h-2.5" />
                              </button>
                            </Tooltip>
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}

              {/* Add item */}
              {addingItemFor === cl.id ? (
                <div className="flex gap-1 mt-1">
                  <input
                    className="flex-1 text-xs border rounded px-2 py-0.5"
                    placeholder="Descripcion del item"
                    value={itemDesc}
                    onChange={(e) => setItemDesc(e.target.value)}
                    autoFocus
                    onKeyDown={(e) =>
                      e.key === "Enter" && handleCreateItem(cl.id)
                    }
                  />
                  <button
                    onClick={() => handleCreateItem(cl.id)}
                    className="text-[10px] bg-brand-600 text-white rounded px-1.5"
                  >
                    OK
                  </button>
                  <button
                    onClick={() => setAddingItemFor(null)}
                    className="text-[10px] bg-gray-200 rounded px-1.5"
                  >
                    X
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setAddingItemFor(cl.id)}
                  className="flex items-center gap-1 text-[10px] text-brand-600 hover:text-brand-700 mt-1"
                >
                  <Plus className="w-3 h-3" /> Agregar item
                </button>
              )}
            </div>
          )}
        </div>
      ))}

      {checklists.length === 0 && !addingCl && (
        <div className="py-4">
          <EmptyState
            icon="checklists"
            title="Sin Checklists"
            description="Crea tu primer checklist o aplica una plantilla para comenzar a verificar los requisitos del caso."
          />
        </div>
      )}
    </div>
  );
}
