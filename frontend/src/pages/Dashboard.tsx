import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Plus,
  Trash2,
  FileStack,
  CheckSquare,
} from "lucide-react";
import toast from "react-hot-toast";
import { EmptyState } from "../components/ui/EmptyState";
import { GlassCard } from "../components/glass/GlassCard";
import { GlassButton } from "../components/glass/GlassButton";
import { GlassSurface } from "../components/glass/GlassSurface";
import type { Case } from "../types";
import { getCases, createCase, deleteCase } from "../api/client";

export default function Dashboard() {
  const navigate = useNavigate();
  const [cases, setCases] = useState<Case[]>([]);
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");

  const load = () => {
    setLoading(true);
    getCases()
      .then(setCases)
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    try {
      const c = await createCase(newName.trim(), newDesc.trim());
      toast.success("Expediente creado");
      setShowNew(false);
      setNewName("");
      setNewDesc("");
      navigate(`/cases/${c.id}`);
    } catch {
      toast.error("Error al crear expediente");
    }
  };

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm("Eliminar este expediente permanentemente?")) return;
    await deleteCase(id);
    toast.success("Expediente eliminado");
    load();
  };

  return (
    <div className="max-w-screen-lg mx-auto px-4 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Expedientes</h1>
          <p className="text-sm text-gray-500 mt-1">
            Gestiona tus casos de indexacion documental
          </p>
        </div>
        <GlassButton
          variant="primary"
          onClick={() => setShowNew(true)}
        >
          <Plus className="w-4 h-4" /> Nuevo Expediente
        </GlassButton>
      </div>

      {/* New case form */}
      {showNew && (
        <GlassSurface filterId="glass-panel" className="mb-8 p-6 rounded-2xl">
          <h2 className="font-bold text-gray-800 mb-4 text-lg">Crear Nuevo Expediente</h2>
          <div className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1 ml-1 uppercase tracking-wider">Nombre</label>
              <input
                className="w-full bg-white/50 border border-white/60 rounded-xl px-4 py-2.5 text-sm focus:bg-white focus:ring-2 focus:ring-brand-400 outline-none transition-colors shadow-sm"
                placeholder="Ej. Caso Smith vs Johnson"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                autoFocus
                onKeyDown={(e) => e.key === "Enter" && handleCreate()}
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1 ml-1 uppercase tracking-wider">Descripción (Opcional)</label>
              <textarea
                className="w-full bg-white/50 border border-white/60 rounded-xl px-4 py-2.5 text-sm focus:bg-white focus:ring-2 focus:ring-brand-400 outline-none transition-colors shadow-sm resize-none"
                placeholder="Detalles adicionales del caso..."
                value={newDesc}
                onChange={(e) => setNewDesc(e.target.value)}
                rows={2}
              />
            </div>
          </div>
          <div className="flex gap-3 mt-6">
            <GlassButton variant="primary" onClick={handleCreate}>
              Crear Expediente
            </GlassButton>
            <GlassButton variant="ghost" onClick={() => setShowNew(false)}>
              Cancelar
            </GlassButton>
          </div>
        </GlassSurface>
      )}

      {/* Loading */}
      {loading && (
        <div className="text-center py-12 text-gray-400">Cargando...</div>
      )}

      {/* Empty state */}
      {!loading && cases.length === 0 && (
        <div className="py-16">
          <EmptyState
            icon="briefcase"
            title="Sin expedientes"
            description="No hay expedientes. Crea uno para comenzar a clasificar y analizar documentos."
          />
        </div>
      )}

      {/* Case cards grid */}
      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {cases.map((c) => (
          <GlassCard
            key={c.id}
            onClick={() => navigate(`/cases/${c.id}`)}
            className="group cursor-pointer flex flex-col h-full relative"
          >
            <div className="flex items-start justify-between mb-3">
              <h3 className="font-bold text-gray-900 group-hover:text-brand-700 transition-colors text-lg leading-tight pr-8">
                {c.name}
              </h3>
              <button
                onClick={(e) => handleDelete(c.id, e)}
                className="absolute top-4 right-4 opacity-0 group-hover:opacity-100 p-2 rounded-full hover:bg-red-50 text-gray-400 hover:text-red-500 transition-all"
                title="Eliminar expediente"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
            
            <div className="flex-1">
              {c.description ? (
                <p className="text-sm text-gray-600 line-clamp-2 leading-relaxed">
                  {c.description}
                </p>
              ) : (
                <p className="text-sm text-gray-400 italic">
                  Sin descripción
                </p>
              )}
            </div>

            <div className="mt-6 pt-4 border-t border-gray-200/50 flex items-center justify-between">
              <div className="flex items-center gap-3 text-xs font-medium text-gray-600">
                <div className="flex items-center gap-1.5 bg-white/40 px-2 py-1 rounded-md">
                  <FileStack className="w-3.5 h-3.5 text-brand-500" />
                  <span>{c.classified_count}/{c.page_count}</span>
                </div>
                <div className="flex items-center gap-1.5 bg-white/40 px-2 py-1 rounded-md">
                  <CheckSquare className="w-3.5 h-3.5 text-indigo-500" />
                  <span>{c.checklist_count}</span>
                </div>
              </div>
              <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">
                {new Date(c.updated_at).toLocaleDateString("es-MX", { month: "short", day: "numeric", year: "numeric" })}
              </span>
            </div>
          </GlassCard>
        ))}
      </div>
    </div>
  );
}

