import { useEffect, useMemo, useState } from "react";
import { Pencil, Plus, Trash2, Users } from "lucide-react";
import toast from "react-hot-toast";
import { authApi } from "../api/client";

interface RoleCatalogItem {
  id: string;
  name: "Admin" | "Supervisor" | "Manager";
}

interface TeamMember {
  id: string;
  name: string;
  roleId: string;
  authUserId?: string;
}

const STATIC_ROLE_CATALOG: RoleCatalogItem[] = [
  { id: "1", name: "Admin" },
  { id: "2", name: "Supervisor" },
  { id: "3", name: "Manager" },
];

const INITIAL_CACHE_MEMBERS: TeamMember[] = [
  { id: "m-3", name: "José Luis Loredo Hernández", roleId: "3" },
  { id: "m-2", name: "Annis Salma", roleId: "2" },
];

type ModalMode = "add" | "edit";

export default function TeamMembersPage() {
  const [members, setMembers] = useState<TeamMember[]>(INITIAL_CACHE_MEMBERS);
  const [currentAuthUserId, setCurrentAuthUserId] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [modalMode, setModalMode] = useState<ModalMode>("add");
  const [editingMemberId, setEditingMemberId] = useState<string | null>(null);
  const [nameInput, setNameInput] = useState("");
  const [roleInput, setRoleInput] = useState(STATIC_ROLE_CATALOG[0].id);

  const roleNameById = useMemo(() => {
    return STATIC_ROLE_CATALOG.reduce<Record<string, string>>((acc, role) => {
      acc[role.id] = role.name;
      return acc;
    }, {});
  }, []);

  const roleIdByName = useMemo(() => {
    return STATIC_ROLE_CATALOG.reduce<Record<string, string>>((acc, role) => {
      acc[role.name.toLowerCase()] = role.id;
      return acc;
    }, {});
  }, []);

  useEffect(() => {
    let mounted = true;

    const loadCurrentUser = async () => {
      try {
        const me = await authApi.getMe();
        if (!mounted) return;

        const authId = String(me.id);
        setCurrentAuthUserId(authId);

        const roleName = (me.roles?.[0] ?? "manager").toLowerCase();
        const mappedRoleId = roleIdByName[roleName] ?? STATIC_ROLE_CATALOG[2].id;

        setMembers((prev) => {
          const existingIdx = prev.findIndex((item) => item.authUserId === authId);
          if (existingIdx >= 0) {
            const copy = [...prev];
            copy[existingIdx] = {
              ...copy[existingIdx],
              name: me.name || copy[existingIdx].name,
              roleId: mappedRoleId,
            };
            return copy;
          }

          return [
            ...prev,
            {
              id: `m-current-${authId}`,
              name: me.name || me.email || "Usuario actual",
              roleId: mappedRoleId,
              authUserId: authId,
            },
          ];
        });
      } catch {
        // If auth profile fails, keep page functional with local cache only.
      }
    };

    loadCurrentUser();

    return () => {
      mounted = false;
    };
  }, [roleIdByName]);

  const openAddModal = () => {
    setModalMode("add");
    setEditingMemberId(null);
    setNameInput("");
    setRoleInput(STATIC_ROLE_CATALOG[0].id);
    setModalOpen(true);
  };

  const openEditModal = (member: TeamMember) => {
    setModalMode("edit");
    setEditingMemberId(member.id);
    setNameInput(member.name);
    setRoleInput(member.roleId);
    setModalOpen(true);
  };

  const closeModal = () => {
    setModalOpen(false);
  };

  const handleDeleteMember = (memberId: string) => {
    const member = members.find((item) => item.id === memberId);
    if (!member) return;

    const adminRoleId = roleIdByName.admin;
    const adminCount = members.filter((item) => item.roleId === adminRoleId).length;
    const isSelf = !!currentAuthUserId && member.authUserId === currentAuthUserId;
    const isAdmin = member.roleId === adminRoleId;

    if (isSelf && isAdmin && adminCount <= 1) {
      toast.error("No puedes eliminarte: debes dejar al menos otro admin.");
      return;
    }

    const confirmed = window.confirm(
      `Estas seguro de eliminar al usuario "${member.name}"?`
    );
    if (!confirmed) return;

    setMembers((prev) => prev.filter((item) => item.id !== memberId));
  };

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const cleanName = nameInput.trim();
    if (!cleanName) return;

    // Future API contract (not used yet while data remains in local cache):
    // { rol: "id_catalogo_de_roles", name: "nombre" }
    const futurePostBody = {
      rol: roleInput,
      name: cleanName,
    };
    void futurePostBody;

    if (modalMode === "add") {
      setMembers((prev) => [
        ...prev,
        {
          id: `m-${Date.now()}`,
          name: cleanName,
          roleId: roleInput,
        },
      ]);
    } else if (editingMemberId) {
      setMembers((prev) =>
        prev.map((item) =>
          item.id === editingMemberId
            ? { ...item, name: cleanName, roleId: roleInput }
            : item
        )
      );
    }

    closeModal();
  };

  return (
    <div className="max-w-screen-2xl mx-auto px-6">
      <div className="rounded-2xl border border-gray-200 bg-white shadow-sm overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between gap-4">
          <div className="inline-flex items-center gap-2">
            <Users className="w-5 h-5 text-gray-700" />
            <h1 className="text-lg font-semibold text-gray-900">Team members</h1>
          </div>

          <button
            type="button"
            onClick={openAddModal}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-800 hover:bg-gray-50"
          >
            <Plus className="w-4 h-4" />
            Agregar usuario
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="bg-gray-50/70 text-gray-600">
                <th className="text-left font-semibold px-5 py-3 border-b border-gray-100">Nombre</th>
                <th className="text-left font-semibold px-5 py-3 border-b border-gray-100">Rol</th>
                <th className="text-left font-semibold px-5 py-3 border-b border-gray-100">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {members.length === 0 ? (
                <tr>
                  <td colSpan={3} className="px-5 py-8 text-center text-gray-500">
                    No members in cache yet.
                  </td>
                </tr>
              ) : (
                members.map((member) => {
                  const adminRoleId = roleIdByName.admin;
                  const adminCount = members.filter((item) => item.roleId === adminRoleId).length;
                  const isSelf = !!currentAuthUserId && member.authUserId === currentAuthUserId;
                  const isAdmin = member.roleId === adminRoleId;
                  const blockSelfDelete = isSelf && isAdmin && adminCount <= 1;

                  return (
                    <tr key={member.id} className="border-b border-gray-100">
                      <td className="px-5 py-3 text-gray-900">{member.name}</td>
                      <td className="px-5 py-3 text-gray-700">{roleNameById[member.roleId] ?? "Unknown"}</td>
                      <td className="px-5 py-3">
                        <div className="inline-flex items-center gap-2">
                          <button
                            type="button"
                            onClick={() => openEditModal(member)}
                            className="inline-flex items-center gap-1 rounded-md border border-gray-200 px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
                          >
                            <Pencil className="w-3.5 h-3.5" />
                            Editar
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDeleteMember(member.id)}
                            disabled={blockSelfDelete}
                            title={
                              blockSelfDelete
                                ? "No puedes eliminarte si eres el unico admin."
                                : "Eliminar miembro"
                            }
                            className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs font-medium border ${
                              blockSelfDelete
                                ? "border-gray-200 text-gray-400 cursor-not-allowed bg-gray-50"
                                : "border-red-200 text-red-600 hover:bg-red-50"
                            }`}
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                            Eliminar
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {modalOpen && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/35 px-4">
          <div className="w-full max-w-md rounded-xl bg-white shadow-2xl border border-gray-200">
            <div className="px-5 py-4 border-b border-gray-100">
              <h2 className="text-base font-semibold text-gray-900">
                {modalMode === "add" ? "Agregar miembro" : "Editar miembro"}
              </h2>
            </div>

            <form onSubmit={handleSubmit} className="px-5 py-4 space-y-4">
              <label className="block space-y-1.5">
                <span className="text-xs font-medium text-gray-600">Nombre</span>
                <input
                  value={nameInput}
                  onChange={(e) => setNameInput(e.target.value)}
                  placeholder="Nombre del miembro"
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-brand-200 focus:border-brand-300"
                />
              </label>

              <label className="block space-y-1.5">
                <span className="text-xs font-medium text-gray-600">Rol</span>
                <select
                  value={roleInput}
                  onChange={(e) => setRoleInput(e.target.value)}
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-brand-200 focus:border-brand-300"
                >
                  {STATIC_ROLE_CATALOG.map((role) => (
                    <option key={role.id} value={role.id}>
                      {role.name}
                    </option>
                  ))}
                </select>
              </label>

              <div className="pt-2 flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={closeModal}
                  className="rounded-lg border border-gray-200 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  className="rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700"
                >
                  {modalMode === "add" ? "Agregar" : "Guardar cambios"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

