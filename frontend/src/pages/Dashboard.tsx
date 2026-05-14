import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Plus,
  Trash2,
  FileStack,
  CheckSquare,
  Users,
  Loader2,
} from "lucide-react";
import toast from "react-hot-toast";
import { EmptyState } from "../components/ui/EmptyState";
import { GlassCard } from "../components/glass/GlassCard";
import { GlassButton } from "../components/glass/GlassButton";
import { GlassSurface } from "../components/glass/GlassSurface";
import { useAuth } from "../contexts/AuthContext";
import { formatLongDate } from "../utils/dateFormat";
import type { Case, SupervisorCase, TeamMember, TeamSummary } from "../types";
import {
  getCases,
  getSupervisorCases,
  getSupervisorTeamCases,
  getTeams,
  getTeamUsers,
  createCase,
  deleteCase,
} from "../api/client";

type DashboardCase = Case | SupervisorCase;
type DashboardRole = "admin" | "supervisor" | "casemanager" | "none";

const CASEMANAGER_ROLE_ALIASES = ["casemanager", "casemanger", "casemaneger"];

const isSupervisorCase = (value: DashboardCase): value is SupervisorCase =>
  "case_manager" in value;

const getCaseUuid = (value: DashboardCase) =>
  "case_uuid" in value ? value.case_uuid : value.id;

export default function Dashboard() {
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();
  const [cases, setCases] = useState<DashboardCase[]>([]);
  const [deletingCaseIds, setDeletingCaseIds] = useState<Set<string>>(
    () => new Set()
  );
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [roleMode, setRoleMode] = useState<DashboardRole>("none");
  const [teams, setTeams] = useState<TeamSummary[]>([]);
  const [teamMembers, setTeamMembers] = useState<TeamMember[]>([]);
  const [showMemberFilter, setShowMemberFilter] = useState(false);
  const [selectedTeamUuid, setSelectedTeamUuid] = useState("");
  const [selectedMemberId, setSelectedMemberId] = useState("all");

  const loadTeamMembers = useCallback(async (teamUuid: string) => {
    try {
      const detail = await getTeamUsers(teamUuid);
      setTeamMembers(detail.members);
    } catch {
      setTeamMembers([]);
      toast.error("No se pudieron cargar los miembros del equipo.");
    }
  }, []);

  const load = useCallback(async () => {
    if (authLoading) return;
    setLoading(true);
    const roles = (user?.roles ?? []).map((role) => role.toLowerCase());
    const isAdmin = roles.includes("admin");
    const isSupervisor = roles.includes("supervisor");
    const isCaseManager = roles.some((role) =>
      CASEMANAGER_ROLE_ALIASES.includes(role)
    );

    try {
      if (isAdmin) {
        setRoleMode("admin");
        setTeams([]);
        setTeamMembers([]);
        setSelectedTeamUuid("");
        setSelectedMemberId("all");
        const adminCases = await getCases();
        setCases(adminCases);
        return;
      }

      if (isSupervisor) {
        setRoleMode("supervisor");
        const supervisorTeams = await getTeams();
        setTeams(supervisorTeams);
        const currentUserId = user?.id ?? null;
        if (supervisorTeams.length === 0) {
          setSelectedTeamUuid("");
          setTeamMembers([]);
          setSelectedMemberId("all");
          if (currentUserId !== null) {
            const allSupervisorCases = await getSupervisorCases();
            setCases(
              allSupervisorCases.filter(
                (caseItem) => caseItem.case_manager.id === currentUserId
              )
            );
          } else {
            setCases([]);
          }
        } else {
          const initialTeamUuid =
            selectedTeamUuid &&
            supervisorTeams.some((team) => team.uuid === selectedTeamUuid)
              ? selectedTeamUuid
              : supervisorTeams[0].uuid;
          setSelectedTeamUuid(initialTeamUuid);
          setSelectedMemberId("all");
        }
        return;
      }

      if (isCaseManager) {
        setRoleMode("casemanager");
        setTeams([]);
        setTeamMembers([]);
        setSelectedTeamUuid("");
        setSelectedMemberId("all");
        const managerCases = await getCases();
        setCases(managerCases);
        return;
      }

      setRoleMode("none");
      setCases([]);
      setTeams([]);
      setTeamMembers([]);
      setSelectedTeamUuid("");
      setSelectedMemberId("all");
    } catch {
      setCases([]);
      toast.error("No se pudieron cargar los expedientes.");
    } finally {
      setLoading(false);
    }
  }, [authLoading, user]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (roleMode !== "supervisor" || !selectedTeamUuid) return;
    loadTeamMembers(selectedTeamUuid);
  }, [roleMode, selectedTeamUuid, loadTeamMembers]);

  useEffect(() => {
    if (roleMode !== "supervisor" || !selectedTeamUuid) return;
    const loadTeamCases = async () => {
      setLoading(true);
      try {
        const [teamCases, allSupervisorCases] = await Promise.all([
          getSupervisorTeamCases(selectedTeamUuid),
          getSupervisorCases(),
        ]);
        const currentUserId = user?.id ?? null;
        const ownCases =
          currentUserId === null
            ? []
            : allSupervisorCases.filter(
                (caseItem) => caseItem.case_manager.id === currentUserId
              );
        const mergedByUuid = new Map<string, SupervisorCase>();
        [...teamCases, ...ownCases].forEach((caseItem) => {
          mergedByUuid.set(caseItem.case_uuid, caseItem);
        });
        setCases(Array.from(mergedByUuid.values()));
      } catch {
        setCases([]);
        toast.error("No se pudieron cargar los expedientes del equipo.");
      } finally {
        setLoading(false);
      }
    };
    loadTeamCases();
  }, [roleMode, selectedTeamUuid, user?.id]);

  const handleCreate = async () => {
    if (
      roleMode !== "admin" &&
      roleMode !== "casemanager" &&
      roleMode !== "supervisor"
    ) {
      return;
    }
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
    if (roleMode !== "admin") return;
    e.stopPropagation();
    if (deletingCaseIds.has(id)) return;
    if (!confirm("Eliminar este expediente permanentemente?")) return;
    setDeletingCaseIds((prev) => new Set(prev).add(id));
    try {
      await deleteCase(id);
      setCases((current) =>
        current.filter((caseItem) => getCaseUuid(caseItem) !== id)
      );
      toast.success("Expediente eliminado");
      await load();
    } catch {
      toast.error("No se pudo eliminar el expediente.");
    } finally {
      setDeletingCaseIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  };

  const filteredCases =
    roleMode === "supervisor" && selectedMemberId !== "all"
      ? cases.filter(
          (caseItem) =>
            isSupervisorCase(caseItem) &&
            String(caseItem.case_manager.id) === selectedMemberId
        )
      : cases;

  const memberFilterOptions = useMemo(() => {
    if (roleMode !== "supervisor" || !user?.id) return teamMembers;
    const alreadyInTeam = teamMembers.some((member) => member.id === user.id);
    if (alreadyInTeam) return teamMembers;
    return [
      {
        uuid_team_user: `self-${user.id}`,
        id: user.id,
        name: user.name || user.email || "Supervisor",
        email: user.email || "",
        is_primary: false,
      },
      ...teamMembers,
    ];
  }, [roleMode, teamMembers, user?.id, user?.name, user?.email]);

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
        <div className="flex items-center gap-2">
          {roleMode === "supervisor" && (
            <GlassButton
              variant="ghost"
              onClick={() => setShowMemberFilter((prev) => !prev)}
            >
              <Users className="w-4 h-4" />
              {showMemberFilter ? "Ocultar miembros" : "Filtrar por miembro"}
            </GlassButton>
          )}
          {(roleMode === "admin" ||
            roleMode === "casemanager" ||
            roleMode === "supervisor") && (
            <GlassButton
              variant="primary"
              onClick={() => setShowNew(true)}
            >
              <Plus className="w-4 h-4" /> Nuevo Expediente
            </GlassButton>
          )}
        </div>
      </div>

      {roleMode === "supervisor" && showMemberFilter && (
        <GlassSurface filterId="glass-panel" className="mb-6 p-4 rounded-2xl">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1">
              <span className="text-xs font-semibold text-gray-600 uppercase tracking-wider">
                Equipo
              </span>
              <select
                className="w-full bg-white/60 border border-white/60 rounded-xl px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-brand-400"
                value={selectedTeamUuid}
                onChange={(e) => {
                  setSelectedTeamUuid(e.target.value);
                  setSelectedMemberId("all");
                }}
              >
                {teams.map((team) => (
                  <option key={team.uuid} value={team.uuid}>
                    {team.name} ({team.members_count})
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1">
              <span className="text-xs font-semibold text-gray-600 uppercase tracking-wider">
                Miembro
              </span>
              <select
                className="w-full bg-white/60 border border-white/60 rounded-xl px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-brand-400"
                value={selectedMemberId}
                onChange={(e) => setSelectedMemberId(e.target.value)}
              >
                <option value="all">Todos</option>
                {memberFilterOptions.map((member) => (
                  <option key={member.uuid_team_user} value={member.id}>
                    {member.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </GlassSurface>
      )}

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
                placeholder="Detalles adicionales del caso…"
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
        <div className="text-center py-12 text-gray-400">Cargando…</div>
      )}

      {/* Empty state */}
      {!loading && filteredCases.length === 0 && (
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
        {filteredCases.map((c) => {
          const caseId = getCaseUuid(c);
          const isDeleting = deletingCaseIds.has(caseId);

          return (
            <GlassCard
              key={caseId}
              onClick={
                isDeleting ? undefined : () => navigate(`/cases/${caseId}`)
              }
              aria-disabled={isDeleting}
              className={`group flex flex-col h-full relative transition-all duration-200 ${
                isDeleting
                  ? "cursor-progress border-red-200/80 bg-red-50/35 opacity-70"
                  : "cursor-pointer"
              }`}
            >
              <div className="flex items-start justify-between mb-3">
                <div className="pr-10">
                  <h3
                    className={`font-bold text-lg leading-tight transition-colors ${
                      isDeleting
                        ? "text-red-700"
                        : "text-gray-900 group-hover:text-brand-700"
                    }`}
                  >
                    {c.name}
                  </h3>
                  {isDeleting && (
                    <div
                      role="status"
                      aria-live="polite"
                      className="mt-2 inline-flex items-center gap-2 rounded-full bg-red-100/90 px-3 py-1 text-xs font-semibold text-red-700"
                    >
                      <span>Eliminando expediente...</span>
                    </div>
                  )}
                </div>
                {roleMode === "admin" && (
                  <button
                    type="button"
                    onClick={(e) => handleDelete(caseId, e)}
                    disabled={isDeleting}
                    aria-label={
                      isDeleting ? "Eliminando expediente" : "Eliminar expediente"
                    }
                    aria-busy={isDeleting}
                    className={`absolute top-4 right-4 rounded-full p-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-300 ${
                      isDeleting
                        ? "bg-red-100 text-red-600 cursor-not-allowed opacity-100"
                        : "opacity-0 group-hover:opacity-100 text-gray-400 hover:bg-red-50 hover:text-red-500 transition-[opacity,background-color,color]"
                    }`}
                    title={
                      isDeleting ? "Eliminando expediente" : "Eliminar expediente"
                    }
                  >
                    {isDeleting ? (
                      <Loader2
                        aria-hidden="true"
                        className="h-4 w-4 animate-spin"
                      />
                    ) : (
                      <Trash2 className="w-4 h-4" />
                    )}
                  </button>
                )}
              </div>

              <div className="flex-1">
                {c.description ? (
                  <p
                    className={`line-clamp-2 text-sm leading-relaxed ${
                      isDeleting ? "text-red-700/80" : "text-gray-600"
                    }`}
                  >
                    {c.description}
                  </p>
                ) : (
                  <p
                    className={`text-sm italic ${
                      isDeleting ? "text-red-500/80" : "text-gray-400"
                    }`}
                  >
                    Sin descripción
                  </p>
                )}

                {!isSupervisorCase(c) && (
                  <p
                    className={`mt-3 text-xs ${
                      isDeleting ? "text-red-700/70" : "text-gray-500"
                    }`}
                  >
                    Creado por: {c.created_by_name?.trim() || "No especificado"}
                  </p>
                )}

                {isSupervisorCase(c) && (
                  <p
                    className={`mt-3 text-xs ${
                      isDeleting ? "text-red-700/70" : "text-gray-500"
                    }`}
                  >
                    Responsable: {c.case_manager.name} · Equipo: {c.team.name}
                  </p>
                )}
              </div>

              <div
                className={`mt-6 flex items-center justify-between border-t pt-4 ${
                  isDeleting ? "border-red-200/60" : "border-gray-200/50"
                }`}
              >
                <div
                  className={`flex items-center gap-3 text-xs font-medium ${
                    isDeleting ? "text-red-700/80" : "text-gray-600"
                  }`}
                >
                  {isSupervisorCase(c) ? (
                    <div
                      className={`flex items-center gap-1.5 rounded-md px-2 py-1 ${
                        isDeleting ? "bg-red-100/80" : "bg-white/40"
                      }`}
                    >
                      <Users
                        className={`w-3.5 h-3.5 ${
                          isDeleting ? "text-red-500" : "text-brand-500"
                        }`}
                      />
                      <span>{c.case_manager.name}</span>
                    </div>
                  ) : (
                    <>
                      <div
                        className={`flex items-center gap-1.5 rounded-md px-2 py-1 ${
                          isDeleting ? "bg-red-100/80" : "bg-white/40"
                        }`}
                      >
                        <FileStack
                          className={`w-3.5 h-3.5 ${
                            isDeleting ? "text-red-500" : "text-brand-500"
                          }`}
                        />
                        <span>{c.classified_count}/{c.page_count}</span>
                      </div>
                      <div
                        className={`flex items-center gap-1.5 rounded-md px-2 py-1 ${
                          isDeleting ? "bg-red-100/80" : "bg-white/40"
                        }`}
                      >
                        <CheckSquare
                          className={`w-3.5 h-3.5 ${
                            isDeleting ? "text-red-500" : "text-indigo-500"
                          }`}
                        />
                        <span>{c.checklist_count}</span>
                      </div>
                    </>
                  )}
                </div>
                <span
                  className={`text-[10px] font-semibold uppercase tracking-wider ${
                    isDeleting ? "text-red-400" : "text-gray-400"
                  }`}
                >
                  {formatLongDate(c.updated_at)}
                </span>
              </div>
            </GlassCard>
          );
        })}
      </div>
    </div>
  );
}

