import { useEffect, useRef, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  FolderOpen,
  Plus,
  Trash2,
  FileText,
  AlertTriangle,
  Table2,
  Type,
  Download,
  BookTemplate,
} from "lucide-react";
import { useDroppable } from "@dnd-kit/core";
import toast from "react-hot-toast";
import { motion, AnimatePresence } from "framer-motion";
import { Tooltip } from "./ui/Tooltip";
import { EmptyState } from "./ui/EmptyState";
import type { DocumentType, Section, Template } from "../types";
import {
  createDocumentType,
  createSection,
  deleteDocumentType,
  deleteSection,
  updateDocumentType,
  updateSection,
  getTemplates,
  applyTemplate,
  saveDocTaxonomyAsTemplate,
} from "../api/client";

// ── Auto-code helpers ──────────────────────────────────────────────────

/** Detect if a code is numeric ("1", "12") or alphabetic ("a", "B") */
function isNumericCode(code: string): boolean {
  return /^\d+$/.test(code);
}

/** Get the next code in sequence: "1"→"2", "a"→"b", "Z"→"AA" */
function nextCode(code: string): string {
  if (isNumericCode(code)) {
    return String(Number(code) + 1);
  }
  // Letter sequence
  const isUpper = code === code.toUpperCase();
  const chars = code.toLowerCase();
  // simple a→b, z→aa
  let carry = true;
  let result = "";
  for (let i = chars.length - 1; i >= 0 && carry; i--) {
    let c = chars.charCodeAt(i) + 1;
    if (c > 122) { // past 'z'
      result = "a" + result;
      carry = true;
    } else {
      result = String.fromCharCode(c) + result;
      carry = false;
    }
    if (i > 0) result = chars.slice(0, i) + result;
  }
  if (carry) result = "a" + result;
  return isUpper ? result.toUpperCase() : result;
}

/** Given existing sibling codes, compute the next auto-code */
function autoNextCode(siblings: Section[]): string {
  if (siblings.length === 0) return "1"; // default to numeric
  const sorted = siblings.slice().sort((a, b) => a.order - b.order);
  const lastCode = sorted[sorted.length - 1].code;
  return nextCode(lastCode);
}

/** Flatten all sections from a tree */
function flattenAll(sections: Section[]): Section[] {
  const r: Section[] = [];
  for (const s of sections) {
    r.push(s);
    if (s.children?.length) r.push(...flattenAll(s.children));
  }
  return r;
}

// ── Droppable wrapper for tree nodes ──────────────────────────────────
function DroppableTreeNode({
  id,
  children,
  onAutoExpand,
  autoExpandDelay = 600,
}: {
  id: string;
  children: (isOver: boolean) => React.ReactNode;
  onAutoExpand?: () => void;
  autoExpandDelay?: number;
}) {
  const { setNodeRef, isOver } = useDroppable({ id });
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (isOver && onAutoExpand) {
      timerRef.current = setTimeout(() => {
        onAutoExpand();
      }, autoExpandDelay);
    }
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [isOver, onAutoExpand, autoExpandDelay]);

  return <div ref={setNodeRef}>{children(isOver)}</div>;
}


interface Props {
  caseId: string;
  docTypes: DocumentType[];
  selectedSectionId: string | null;
  onSelectSection: (sectionId: string, docTypeId: string) => void;
  onRefresh: () => void;
}

export default function DocumentTree({
  caseId,
  docTypes,
  selectedSectionId,
  onSelectSection,
  onRefresh,
}: Props) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [addingDocType, setAddingDocType] = useState(false);
  const [newDt, setNewDt] = useState({ name: "", code: "", has_tables: false });
  const [addingSectionFor, setAddingSectionFor] = useState<string | null>(null);
  const [addingSubsectionFor, setAddingSubsectionFor] = useState<string | null>(null);
  const [newSec, setNewSec] = useState({ name: "", code: "" });
  const [editingCodeFor, setEditingCodeFor] = useState<string | null>(null);
  const [editCodeValue, setEditCodeValue] = useState("");

  // Template selector
  const [templates, setTemplates] = useState<Template[]>([]);
  const [showTemplates, setShowTemplates] = useState(false);

  const handleSaveDocAsTemplate = async () => {
    try {
      await saveDocTaxonomyAsTemplate(caseId, `Documentos - ${new Date().toLocaleDateString()}`);
      toast.success("Estructura guardada como plantilla");
    } catch { toast.error("Error al guardar plantilla"); }
  };

  useEffect(() => {
    if (showTemplates) {
      getTemplates().then(setTemplates).catch(() => {});
    }
  }, [showTemplates]);

  const toggle = (id: string) =>
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));

  const handleAddDocType = async () => {
    if (!newDt.name || !newDt.code) return;
    try {
      await createDocumentType(caseId, {
        name: newDt.name,
        code: newDt.code,
        order: docTypes.length,
        has_tables: newDt.has_tables,
      });
      setNewDt({ name: "", code: "", has_tables: false });
      setAddingDocType(false);
      onRefresh();
    } catch {
      toast.error("Error al crear tipo de documento");
    }
  };

  const handleToggleTables = async (dtId: string, current: boolean) => {
    try {
      await updateDocumentType(dtId, { has_tables: !current });
      onRefresh();
      toast.success(!current ? "Modo tablas activado" : "Modo texto activado");
    } catch {
      toast.error("Error al cambiar modo");
    }
  };

  const handleAddSection = async (dtId: string, parentId?: string) => {
    if (!newSec.name || !newSec.code) return;
    const dt = docTypes.find((d) => d.id === dtId);
    try {
      await createSection(dtId, {
        name: newSec.name,
        code: newSec.code,
        order: dt?.sections.length ?? 0,
        parent_section_id: parentId,
      });
      setNewSec({ name: "", code: "" });
      setAddingSectionFor(null);
      setAddingSubsectionFor(null);
      onRefresh();
    } catch {
      toast.error("Error al crear seccion");
    }
  };

  const handleDeleteDocType = async (id: string) => {
    if (!confirm("Eliminar tipo de documento y todas sus secciones?")) return;
    await deleteDocumentType(id);
    onRefresh();
  };

  const handleDeleteSection = async (id: string) => {
    if (!confirm("Eliminar seccion y sus subsecciones?")) return;
    await deleteSection(id);
    onRefresh();
  };

  const handleSaveCode = async (secId: string) => {
    if (!editCodeValue.trim()) return;
    try {
      await updateSection(secId, { code: editCodeValue.trim() });
      setEditingCodeFor(null);
      onRefresh();
    } catch {
      toast.error("Error al actualizar código");
    }
  };

  const handleApplyTemplate = async (tplId: string) => {
    try {
      await applyTemplate(caseId, tplId);
      toast.success("Plantilla aplicada exitosamente");
      setShowTemplates(false);
      onRefresh();
    } catch {
      toast.error("Error al aplicar plantilla");
    }
  };

  // Recursive section renderer
  const renderSection = (sec: Section, dt: DocumentType, indent: number) => {
    const isSelected = selectedSectionId === sec.id;
    const hasChildren = sec.children && sec.children.length > 0;
    const isExpanded = expanded[sec.id];

    const handleAutoExpand = hasChildren
      ? () => {
          if (!expanded[sec.id]) {
            setExpanded((prev) => ({ ...prev, [sec.id]: true }));
          }
        }
      : undefined;

    return (
      <DroppableTreeNode key={sec.id} id={sec.id} onAutoExpand={handleAutoExpand}>
        {(isOver) => (
          <div>
            <div
              className={`flex items-center gap-1 px-2 py-1 rounded-md cursor-pointer group transition-colors
                ${isOver ? "bg-brand-100 ring-1 ring-brand-400" : ""}
                ${isSelected && !isOver ? "bg-white/60 shadow-sm text-brand-700" : ""}
                ${!isSelected && !isOver ? "hover:bg-white/40 text-gray-700" : ""}`}
              style={{ paddingLeft: `${8 + indent * 16}px` }}
              onClick={() => onSelectSection(sec.id, dt.id)}
            >
          {hasChildren ? (
            <button
              onClick={(e) => { e.stopPropagation(); toggle(sec.id); }}
              className="shrink-0"
            >
              {isExpanded ? (
                <ChevronDown className="w-3 h-3 text-gray-400" />
              ) : (
                <ChevronRight className="w-3 h-3 text-gray-400" />
              )}
            </button>
          ) : (
            <span className="w-3 shrink-0" />
          )}
          <FileText className="w-3.5 h-3.5 shrink-0" />
          {editingCodeFor === sec.id ? (
            <span className="flex items-center gap-0.5 flex-1" onClick={(e) => e.stopPropagation()}>
              <input
                className="w-10 text-[10px] font-mono border rounded px-1 py-0 text-center focus:ring-1 focus:ring-brand-400 outline-none"
                value={editCodeValue}
                onChange={(e) => setEditCodeValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleSaveCode(sec.id);
                  if (e.key === "Escape") setEditingCodeFor(null);
                }}
                onBlur={() => handleSaveCode(sec.id)}
                autoFocus
              />
              <span className="text-xs text-gray-500 truncate">&ndash; {sec.name}</span>
            </span>
          ) : (
            <Tooltip content="Doble clic para editar código">
              <span
                className="text-xs flex-1 truncate"
                onDoubleClick={(e) => {
                  e.stopPropagation();
                  setEditCodeValue(sec.code);
                  setEditingCodeFor(sec.id);
                }}
              >
                {sec.path_code || `${dt.code}.${sec.code}`} &ndash; {sec.name}
              </span>
            </Tooltip>
          )}
          <span className="text-[10px] text-gray-400">{sec.page_count}p</span>
          {sec.is_required && sec.page_count === 0 && (
            <Tooltip content="Sección requerida pero no tiene páginas asignadas">
              <span>
                <AlertTriangle className="w-3 h-3 text-amber-500" />
              </span>
            </Tooltip>
          )}
          {/* Add subsection button */}
          <Tooltip content="Agregar subsección">
            <button
              onClick={(e) => {
                e.stopPropagation();
                // Auto-compute next code from siblings
                const siblings = sec.children || [];
                const auto = autoNextCode(siblings);
                setNewSec({ name: "", code: auto });
                setAddingSubsectionFor(sec.id);
                setAddingSectionFor(dt.id);
              }}
              className="opacity-0 group-hover:opacity-100 p-0.5 text-gray-400 hover:text-brand-600 transition-colors"
            >
              <Plus className="w-3 h-3" />
            </button>
          </Tooltip>
          <Tooltip content="Eliminar sección">
            <button
              onClick={(e) => {
                e.stopPropagation();
                handleDeleteSection(sec.id);
              }}
              className="opacity-0 group-hover:opacity-100 p-0.5 text-gray-400 hover:text-red-500 transition-colors"
            >
              <Trash2 className="w-3 h-3" />
            </button>
          </Tooltip>
        </div>

        {/* Inline subsection form */}
        {addingSubsectionFor === sec.id && (
          <div
            className="flex flex-col gap-1.5 p-2 bg-indigo-50 rounded-lg border border-indigo-200 mt-0.5 mb-0.5"
            style={{ marginLeft: `${16 + indent * 16}px` }}
          >
            <input
              className="text-xs border rounded px-2 py-1 focus:ring-1 focus:ring-brand-400 focus:border-brand-400 outline-none"
              placeholder="Nombre subsección"
              value={newSec.name}
              onChange={(e) => setNewSec((p) => ({ ...p, name: e.target.value }))}
              autoFocus
            />
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] text-gray-500 shrink-0">
                {sec.path_code || `${dt.code}.${sec.code}`}.
              </span>
              <input
                className="w-12 text-xs border rounded px-1.5 py-0.5 font-mono text-center focus:ring-1 focus:ring-brand-400 focus:border-brand-400 outline-none"
                value={newSec.code}
                onChange={(e) => setNewSec((p) => ({ ...p, code: e.target.value }))}
                title="Código auto-generado, editable"
              />
              <span className="text-[10px] text-gray-400 truncate flex-1">
                {newSec.name || "Nombre..."}
              </span>
            </div>
            <div className="flex gap-1">
              <button
                onClick={() => handleAddSection(dt.id, sec.id)}
                disabled={!newSec.name}
                className="flex-1 text-[10px] bg-brand-600 text-white rounded py-0.5 hover:bg-brand-700 disabled:opacity-40 disabled:cursor-not-allowed transition"
              >
                Crear
              </button>
              <button
                onClick={() => { setAddingSubsectionFor(null); setNewSec({ name: "", code: "" }); }}
                className="flex-1 text-[10px] bg-gray-200 rounded py-0.5 hover:bg-gray-300 transition"
              >
                Cancelar
              </button>
            </div>
          </div>
        )}

        {/* Render children recursively */}
        {isExpanded && hasChildren &&
          sec.children
            .slice()
            .sort((a, b) => a.order - b.order)
            .map((child) => renderSection(child, dt, indent + 1))
        }
          </div>
        )}
      </DroppableTreeNode>
    );
  };

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-bold text-gray-700 uppercase tracking-wider">
          Documentos
        </h3>
        <div className="flex items-center gap-1">
          {docTypes.length > 0 && (
            <Tooltip content="Guardar estructura actual como plantilla reutilizable">
              <button
                onClick={handleSaveDocAsTemplate}
                className="p-1 rounded hover:bg-green-100 text-gray-400 hover:text-green-600 transition"
              >
                <Download className="w-4 h-4" />
              </button>
            </Tooltip>
          )}
          <Tooltip content="Aplicar plantilla predefinida">
            <button
              onClick={() => setShowTemplates(!showTemplates)}
              className={`p-1 rounded transition-colors ${
                showTemplates ? "bg-brand-100 text-brand-600" : "hover:bg-gray-200 text-gray-500"
              }`}
            >
              <BookTemplate className="w-4 h-4" />
            </button>
          </Tooltip>
          <Tooltip content="Agregar tipo de documento manual">
            <button
              onClick={() => setAddingDocType(true)}
              className="p-1 rounded hover:bg-gray-200 text-brand-600 transition"
            >
              <Plus className="w-4 h-4" />
            </button>
          </Tooltip>
        </div>
      </div>

      {/* Template selector */}
      {showTemplates && (
        <div className="mb-2 p-2 bg-purple-50 rounded-lg border border-purple-200">
          <p className="text-[10px] font-semibold text-purple-700 uppercase mb-1">
            Plantillas disponibles
          </p>
          {templates.length === 0 ? (
            <p className="text-[10px] text-gray-400 italic">
              No hay plantillas creadas.
            </p>
          ) : (
            <div className="flex flex-col gap-1">
              {templates.map((tpl) => (
                <button
                  key={tpl.id}
                  onClick={() => handleApplyTemplate(tpl.id)}
                  className="flex items-center gap-1.5 text-xs text-left px-2 py-1.5 rounded hover:bg-purple-100 transition"
                >
                  <Download className="w-3.5 h-3.5 text-purple-500 shrink-0" />
                  <div className="flex-1">
                    <span className="font-medium text-gray-800">{tpl.name}</span>
                    {tpl.description && (
                      <p className="text-[10px] text-gray-400 truncate">{tpl.description}</p>
                    )}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Add new doc type inline form */}
      {addingDocType && (
        <div className="flex flex-col gap-1 mb-2 p-2 bg-blue-50 rounded-lg border border-blue-200">
          <input
            className="text-xs border rounded px-2 py-1"
            placeholder="Nombre (ej. FBI Records)"
            value={newDt.name}
            onChange={(e) => setNewDt((p) => ({ ...p, name: e.target.value }))}
            autoFocus
          />
          <input
            className="text-xs border rounded px-2 py-1"
            placeholder="Codigo (ej. 11)"
            value={newDt.code}
            onChange={(e) => setNewDt((p) => ({ ...p, code: e.target.value }))}
          />
          <label className="flex items-center gap-2 text-xs text-gray-600 px-1 py-0.5 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={newDt.has_tables}
              onChange={(e) =>
                setNewDt((p) => ({ ...p, has_tables: e.target.checked }))
              }
              className="rounded border-gray-300 text-brand-600 focus:ring-brand-500"
            />
            <Table2 className="w-3.5 h-3.5 text-gray-500" />
            Contiene tablas (usar Gemini Vision)
          </label>
          <div className="flex gap-1">
            <button
              onClick={handleAddDocType}
              className="flex-1 text-xs bg-brand-600 text-white rounded py-1 hover:bg-brand-700"
            >
              Crear
            </button>
            <button
              onClick={() => setAddingDocType(false)}
              className="flex-1 text-xs bg-gray-200 rounded py-1 hover:bg-gray-300"
            >
              Cancelar
            </button>
          </div>
        </div>
      )}

      {/* Doc type list */}
      {docTypes.map((dt) => (
        <div key={dt.id} className="select-none">
          {/* Doc type header */}
          <div
            className="flex items-center gap-1 px-2 py-1.5 rounded-md hover:bg-white/40 cursor-pointer group transition-colors"
            onClick={() => toggle(dt.id)}
          >
            {expanded[dt.id] ? (
              <ChevronDown className="w-3.5 h-3.5 text-gray-400 shrink-0" />
            ) : (
              <ChevronRight className="w-3.5 h-3.5 text-gray-400 shrink-0" />
            )}
            <FolderOpen className="w-4 h-4 text-amber-500 shrink-0" />
            <span className="text-sm font-medium text-gray-800 truncate flex-1">
              {dt.code} &ndash; {dt.name}
            </span>
            {/* Tables/Text mode indicator & toggle */}
            <Tooltip content={dt.has_tables ? "Modo Tablas activado (Gemini Vision). Haz clic para desactivar." : "Modo Texto activado (OCR normal). Haz clic para activar tablas."}>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  handleToggleTables(dt.id, dt.has_tables);
                }}
                className={`p-0.5 rounded transition-colors shrink-0 ${
                  dt.has_tables
                    ? "text-purple-600 bg-purple-50 hover:bg-purple-100"
                    : "text-gray-400 hover:text-gray-600 hover:bg-gray-100"
                }`}
              >
                {dt.has_tables ? (
                  <Table2 className="w-3.5 h-3.5" />
                ) : (
                  <Type className="w-3.5 h-3.5" />
                )}
              </button>
            </Tooltip>
            <Tooltip content="Eliminar documento y secciones">
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  handleDeleteDocType(dt.id);
                }}
                className="opacity-0 group-hover:opacity-100 p-0.5 text-gray-400 hover:text-red-500 transition-colors"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </Tooltip>
          </div>

          {/* Sections (recursive tree) */}
          {expanded[dt.id] && (
            <div className="ml-3 flex flex-col gap-0.5 mt-0.5">
              {dt.sections
                .slice()
                .sort((a, b) => a.order - b.order)
                .map((sec) => renderSection(sec, dt, 0))}

              {/* Add root section */}
              {addingSectionFor === dt.id && !addingSubsectionFor ? (
                <div className="flex flex-col gap-1.5 p-2 bg-blue-50 rounded-lg border border-blue-200 mt-1">
                  <input
                    className="text-xs border rounded px-2 py-1 focus:ring-1 focus:ring-brand-400 focus:border-brand-400 outline-none"
                    placeholder="Nombre (ej. Introduccion)"
                    value={newSec.name}
                    onChange={(e) =>
                      setNewSec((p) => ({ ...p, name: e.target.value }))
                    }
                    autoFocus
                  />
                  <div className="flex items-center gap-1.5">
                    <span className="text-[10px] text-gray-500 shrink-0">{dt.code}.</span>
                    <input
                      className="w-12 text-xs border rounded px-1.5 py-0.5 font-mono text-center focus:ring-1 focus:ring-brand-400 focus:border-brand-400 outline-none"
                      value={newSec.code}
                      onChange={(e) =>
                        setNewSec((p) => ({ ...p, code: e.target.value }))
                      }
                      title="Código auto-generado, editable"
                    />
                    <span className="text-[10px] text-gray-400 truncate flex-1">
                      {newSec.name || "Nombre..."}
                    </span>
                  </div>
                  <div className="flex gap-1">
                    <button
                      onClick={() => handleAddSection(dt.id)}
                      disabled={!newSec.name}
                      className="flex-1 text-[10px] bg-brand-600 text-white rounded py-0.5 hover:bg-brand-700 disabled:opacity-40 disabled:cursor-not-allowed transition"
                    >
                      Crear
                    </button>
                    <button
                      onClick={() => { setAddingSectionFor(null); setNewSec({ name: "", code: "" }); }}
                      className="flex-1 text-[10px] bg-gray-200 rounded py-0.5 hover:bg-gray-300 transition"
                    >
                      Cancelar
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  onClick={() => {
                    // Auto-compute next code from root siblings
                    const rootSiblings = dt.sections.filter((s) => !s.parent_section_id);
                    const auto = autoNextCode(rootSiblings);
                    setNewSec({ name: "", code: auto });
                    setAddingSectionFor(dt.id);
                    setAddingSubsectionFor(null);
                  }}
                  className="flex items-center gap-1 text-[10px] text-brand-600 hover:text-brand-700 ml-2 mt-0.5"
                >
                  <Plus className="w-3 h-3" /> Agregar sección
                </button>
              )}
            </div>
          )}
        </div>
      ))}

      {docTypes.length === 0 && !addingDocType && (
        <div className="py-4">
          <EmptyState
            icon="organize"
            title="Sin estructura"
            description="Agrega un tipo de documento manualmente o aplica una plantilla desde el icono superior."
          />
        </div>
      )}
    </div>
  );
}
