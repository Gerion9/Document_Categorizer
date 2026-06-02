import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Plus, Users, UserPlus } from "lucide-react";
import toast from "react-hot-toast";
import {
  createTeam,
  getTeamUsers,
  getTeams,
  getUsers,
  updateTeam,
  type UserDetail,
} from "../api/client";
import type { TeamDetail, TeamSummary } from "../types";
import { LoadingButton } from "../components/ui/LoadingButton";

const ALLOWED_MEMBER_ROLES = new Set(["supervisor", "admin"]);

interface DraftMember {
  id: number;
  name: string;
  email: string;
  uuid_team_user?: string;
}

export default function TeamsPage() {
  const [teams, setTeams] = useState<TeamSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [teamName, setTeamName] = useState("");
  const [creating, setCreating] = useState(false);
  const [selectedTeam, setSelectedTeam] = useState<TeamSummary | null>(null);
  const [membersModalOpen, setMembersModalOpen] = useState(false);
  const [membersLoading, setMembersLoading] = useState(false);
  const [membersSaving, setMembersSaving] = useState(false);
  const [availableUsers, setAvailableUsers] = useState<UserDetail[]>([]);
  const [draftMembers, setDraftMembers] = useState<DraftMember[]>([]);

  const loadTeams = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getTeams();
      setTeams(data);
    } catch {
      toast.error("No se pudieron cargar los teams.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTeams();
  }, [loadTeams]);

  const closeModal = () => {
    setShowCreateModal(false);
    setTeamName("");
  };

  const closeMembersModal = () => {
    setMembersModalOpen(false);
    setSelectedTeam(null);
    setAvailableUsers([]);
    setDraftMembers([]);
  };

  const hasEligibleRole = (user: UserDetail) =>
    user.roles.some((role) =>
      ALLOWED_MEMBER_ROLES.has(role.name.toLowerCase())
    );

  const openMembersModal = async (team: TeamSummary) => {
    setSelectedTeam(team);
    setMembersModalOpen(true);
    setMembersLoading(true);
    try {
      const [teamDetail, users] = await Promise.all([
        getTeamUsers(team.uuid),
        getUsers(),
      ]);
      setDraftMembers(
        teamDetail.members.map((member) => ({
          id: member.id,
          name: member.name,
          email: member.email,
          uuid_team_user: member.uuid_team_user,
        }))
      );
      setAvailableUsers(users.filter(hasEligibleRole));
    } catch {
      toast.error("No se pudo cargar la configuracion de miembros.");
      closeMembersModal();
    } finally {
      setMembersLoading(false);
    }
  };

  const memberOptions = useMemo(() => {
    const byId = new Map<number, { id: number; name: string; email: string }>();
    for (const user of availableUsers) {
      byId.set(user.id, { id: user.id, name: user.name, email: user.email });
    }
    for (const member of draftMembers) {
      if (!byId.has(member.id)) {
        byId.set(member.id, {
          id: member.id,
          name: member.name,
          email: member.email,
        });
      }
    }
    return Array.from(byId.values()).sort((a, b) =>
      a.name.localeCompare(b.name, "es", { sensitivity: "base" })
    );
  }, [availableUsers, draftMembers]);

  const toggleMember = (
    option: { id: number; name: string; email: string },
    checked: boolean
  ) => {
    setDraftMembers((previous) => {
      if (checked) {
        if (previous.some((member) => member.id === option.id)) return previous;
        const next = [
          ...previous,
          {
            id: option.id,
            name: option.name,
            email: option.email,
          },
        ];
        return next;
      }

      return previous.filter((member) => member.id !== option.id);
    });
  };

  const handleSaveMembers = async () => {
    if (!selectedTeam) return;
    setMembersSaving(true);
    try {
      const payload = {
        name: selectedTeam.name,
        users: draftMembers.map((member) => ({
          id: member.id,
          uuid_team_user: member.uuid_team_user,
          is_primary: false,
        })),
      };
      const updated: TeamDetail = await updateTeam(selectedTeam.uuid, payload);
      setDraftMembers(
        updated.members.map((member) => ({
          id: member.id,
          name: member.name,
          email: member.email,
          uuid_team_user: member.uuid_team_user,
        }))
      );
      toast.success("Miembros actualizados.");
      await loadTeams();
      closeMembersModal();
    } catch {
      toast.error("No se pudieron actualizar los miembros.");
    } finally {
      setMembersSaving(false);
    }
  };

  const handleCreateTeam = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const name = teamName.trim();
    if (!name) {
      toast.error("El nombre del team es obligatorio.");
      return;
    }

    setCreating(true);
    try {
      await createTeam({ name, users: [] });
      toast.success("Team creado.");
      closeModal();
      await loadTeams();
    } catch {
      toast.error("No se pudo crear el team. Intenta nuevamente.");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="page-container">
      <div className="mb-8 flex items-center justify-between gap-4">
        <div>
          <h1 className="page-title">Equipos</h1>
          <p className="page-subtitle">
            Gestiona los equipos asignados a tus case managers.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowCreateModal(true)}
          className="inline-flex items-center gap-2 rounded-full bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-brand-700"
        >
          <Plus className="h-4 w-4" />
          Nuevo Team
        </button>
      </div>

      <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm">
        <div className="border-b border-gray-100 px-5 py-4">
          <h2 className="text-base font-semibold text-gray-900">Listado de teams</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="bg-gray-50/70 text-gray-600">
                <th className="border-b border-gray-100 px-5 py-3 text-left font-semibold">
                  Nombre
                </th>
                <th className="border-b border-gray-100 px-5 py-3 text-left font-semibold">
                  Miembros
                </th>
                <th className="border-b border-gray-100 px-5 py-3 text-left font-semibold">
                  Acciones
                </th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={3} className="px-5 py-8 text-center text-gray-500">
                    Cargando teams…
                  </td>
                </tr>
              ) : teams.length === 0 ? (
                <tr>
                  <td colSpan={3} className="px-5 py-10 text-center text-gray-500">
                    <div className="inline-flex flex-col items-center gap-2">
                      <Users className="h-5 w-5" />
                      <span>No hay teams creados todavia.</span>
                    </div>
                  </td>
                </tr>
              ) : (
                teams.map((team) => (
                  <tr key={team.uuid} className="border-b border-gray-100 last:border-b-0">
                    <td className="px-5 py-3 text-gray-900">{team.name}</td>
                    <td className="px-5 py-3 text-gray-700">{team.members_count}</td>
                    <td className="px-5 py-3">
                      <button
                        type="button"
                        onClick={() => openMembersModal(team)}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
                      >
                        <UserPlus className="h-3.5 w-3.5" />
                        Gestionar miembros
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {showCreateModal && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/35 px-4">
          <div className="w-full max-w-md rounded-xl border border-gray-200 bg-white shadow-2xl">
            <div className="border-b border-gray-100 px-5 py-4">
              <h2 className="text-base font-semibold text-gray-900">Nuevo Team</h2>
            </div>
            <form onSubmit={handleCreateTeam} className="space-y-4 px-5 py-4">
              <label className="block space-y-1.5">
                <span className="text-xs font-medium text-gray-600">Nombre</span>
                <input
                  value={teamName}
                  onChange={(e) => setTeamName(e.target.value)}
                  placeholder="Ej. Team Migracion"
                  autoFocus
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-brand-300 focus:ring-2 focus:ring-brand-200"
                />
              </label>

              <div className="flex items-center justify-end gap-2 pt-2">
                <LoadingButton
                  type="button"
                  onClick={closeModal}
                  disabled={creating}
                  className="inline-flex items-center justify-center gap-2 rounded-full border border-gray-200 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                >
                  Cancelar
                </LoadingButton>
                <LoadingButton
                  type="submit"
                  disabled={creating || teamName.trim().length === 0}
                  loading={creating}
                  loadingLabel="Creando…"
                  className="inline-flex items-center justify-center gap-2 rounded-full bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
                >
                  Crear team
                </LoadingButton>
              </div>
            </form>
          </div>
        </div>
      )}

      {membersModalOpen && selectedTeam && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/35 px-4">
          <div className="w-full max-w-2xl rounded-xl border border-gray-200 bg-white shadow-2xl">
            <div className="border-b border-gray-100 px-5 py-4">
              <h2 className="text-base font-semibold text-gray-900">
                Gestionar miembros - {selectedTeam.name}
              </h2>
            </div>

            {membersLoading ? (
              <div className="px-5 py-10 text-center text-sm text-gray-500">
                Cargando miembros…
              </div>
            ) : (
              <>
                <div className="max-h-[55vh] overflow-y-auto px-5 py-4">
                  <p className="mb-3 text-xs font-medium uppercase tracking-wide text-gray-500">
                    Usuarios elegibles (roles supervisor/admin)
                  </p>
                  <div className="space-y-2">
                    {memberOptions.length === 0 ? (
                      <div className="rounded-lg border border-dashed border-gray-200 px-3 py-4 text-sm text-gray-500">
                        No hay usuarios elegibles para agregar.
                      </div>
                    ) : (
                      memberOptions.map((option) => {
                        const selected = draftMembers.find(
                          (member) => member.id === option.id
                        );
                        return (
                          <label
                            key={option.id}
                            className="flex items-center justify-between gap-3 rounded-lg border border-gray-200 px-3 py-2.5"
                          >
                            <span className="inline-flex items-center gap-3">
                              <input
                                type="checkbox"
                                checked={Boolean(selected)}
                                onChange={(event) =>
                                  toggleMember(option, event.target.checked)
                                }
                                className="h-4 w-4 rounded border-gray-300 text-brand-600 focus:ring-brand-500"
                              />
                              <span className="text-sm text-gray-800">
                                {option.name}
                                <span className="ml-1 text-xs text-gray-500">
                                  ({option.email})
                                </span>
                              </span>
                            </span>

                            <span className="text-xs text-gray-400">-</span>
                          </label>
                        );
                      })
                    )}
                  </div>
                </div>

                <div className="flex items-center justify-end gap-2 border-t border-gray-100 px-5 py-4">
                  <LoadingButton
                    type="button"
                    onClick={closeMembersModal}
                    disabled={membersSaving}
                    className="inline-flex items-center justify-center gap-2 rounded-full border border-gray-200 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                  >
                    Cancelar
                  </LoadingButton>
                  <LoadingButton
                    type="button"
                    onClick={handleSaveMembers}
                    disabled={membersSaving}
                    loading={membersSaving}
                    loadingLabel="Guardando…"
                    className="inline-flex items-center justify-center gap-2 rounded-full bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
                  >
                    Guardar miembros
                  </LoadingButton>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
