import { useEffect, useState } from "react";
import { Pencil, Trash2, Users } from "lucide-react";
import toast from "react-hot-toast";
import {
  getUsers,
  getRoles,
  updateUserRoles,
  deleteUser,
  type UserDetail,
  type RoleDetail,
} from "../api/client";
import { useAuth } from "../contexts/AuthContext";
import { LoadingButton } from "../components/ui/LoadingButton";

export default function TeamMembersPage() {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<UserDetail[]>([]);
  const [roles, setRoles] = useState<RoleDetail[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<UserDetail | null>(null);
  const [selectedRoleId, setSelectedRoleId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [userToDelete, setUserToDelete] = useState<UserDetail | null>(null);
  const [deleting, setDeleting] = useState(false);

  const loadUsers = async () => {
    try {
      const data = await getUsers();
      setUsers(data);
    } catch {
      toast.error("No se pudo cargar la lista de usuarios.");
    } finally {
      setLoading(false);
    }
  };

  const loadRoles = async () => {
    try {
      const data = await getRoles();
      setRoles(data);
    } catch {
      toast.error("No se pudo cargar la lista de roles.");
    }
  };

  useEffect(() => {
    loadUsers();
    loadRoles();
  }, []);

  const openEditModal = (user: UserDetail) => {
    setEditingUser(user);
    const currentRoleId = user.roles?.[0]?.id ?? null;
    setSelectedRoleId(currentRoleId);
    setModalOpen(true);
  };

  const closeModal = () => {
    setModalOpen(false);
    setEditingUser(null);
    setSelectedRoleId(null);
  };

  const handleSaveRole = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingUser || selectedRoleId == null) return;
    setSaving(true);
    try {
      const updated = await updateUserRoles(editingUser.id, [selectedRoleId]);
      setUsers((prev) =>
        prev.map((u) => (u.id === updated.id ? updated : u))
      );
      toast.success("Rol actualizado.");
      closeModal();
    } catch {
      toast.error("No se pudo actualizar el rol.");
    } finally {
      setSaving(false);
    }
  };

  const openDeleteConfirm = (user: UserDetail) => {
    const isSelf = currentUserId !== null && user.id === currentUserId;
    const isAdmin = user.roles.some((r) => r.id === adminRoleId);
    const adminCountForUser = users.filter((u) =>
      u.roles.some((r) => r.id === adminRoleId)
    ).length;
    if (isSelf && isAdmin && adminCountForUser <= 1) {
      toast.error("No puedes eliminarte: debes dejar al menos otro admin.");
      return;
    }
    setUserToDelete(user);
  };

  const closeDeleteConfirm = () => setUserToDelete(null);

  const handleConfirmDelete = async () => {
    if (!userToDelete) return;
    setDeleting(true);
    try {
      await deleteUser(userToDelete.id);
      setUsers((prev) => prev.filter((u) => u.id !== userToDelete.id));
      toast.success("Usuario eliminado.");
      closeDeleteConfirm();
    } catch {
      toast.error("No se pudo eliminar el usuario.");
    } finally {
      setDeleting(false);
    }
  };

  const currentUserId = currentUser?.id ?? null;
  const adminRoleId = roles.find((r) => r.name.toLowerCase() === "admin")?.id;
  const adminCount = users.filter((u) =>
    u.roles.some((r) => r.id === adminRoleId)
  ).length;

  return (
    <div className="max-w-screen-2xl mx-auto px-6">
      <div className="rounded-2xl border border-gray-200 bg-white shadow-sm overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between gap-4">
          <div className="inline-flex items-center gap-2">
            <Users className="w-5 h-5 text-gray-700" />
            <h1 className="text-lg font-semibold text-gray-900">
              Miembros del equipo
            </h1>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="bg-gray-50/70 text-gray-600">
                <th className="text-left font-semibold px-5 py-3 border-b border-gray-100">
                  Nombre
                </th>
                <th className="text-left font-semibold px-5 py-3 border-b border-gray-100">
                  Email
                </th>
                <th className="text-left font-semibold px-5 py-3 border-b border-gray-100">
                  Rol
                </th>
                <th className="text-left font-semibold px-5 py-3 border-b border-gray-100">
                  Acciones
                </th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={4} className="px-5 py-8 text-center text-gray-500">
                    Cargando…
                  </td>
                </tr>
              ) : users.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-5 py-8 text-center text-gray-500">
                    No hay usuarios en el sistema.
                  </td>
                </tr>
              ) : (
                users.map((user) => {
                  const isSelf = currentUserId !== null && user.id === currentUserId;
                  const isAdmin = user.roles.some((r) => r.id === adminRoleId);
                  const blockSelfDelete =
                    isSelf && isAdmin && adminCount <= 1;

                  return (
                    <tr key={user.id} className="border-b border-gray-100">
                      <td className="px-5 py-3 text-gray-900">{user.name}</td>
                      <td className="px-5 py-3 text-gray-700">{user.email}</td>
                      <td className="px-5 py-3 text-gray-700">
                        {user.roles?.map((r) => r.name).join(", ") || "—"}
                      </td>
                      <td className="px-5 py-3">
                        <div className="inline-flex items-center gap-2">
                          <button
                            type="button"
                            onClick={() => openEditModal(user)}
                            className="inline-flex items-center gap-1 rounded-md border border-gray-200 px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
                          >
                            <Pencil className="w-3.5 h-3.5" />
                            Editar
                          </button>
                          <button
                            type="button"
                            onClick={() => openDeleteConfirm(user)}
                            disabled={blockSelfDelete}
                            title={
                              blockSelfDelete
                                ? "No puedes eliminarte si eres el único admin."
                                : "Eliminar usuario"
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

      {modalOpen && editingUser && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/35 px-4">
          <div className="w-full max-w-md rounded-xl bg-white shadow-2xl border border-gray-200">
            <div className="px-5 py-4 border-b border-gray-100">
              <h2 className="text-base font-semibold text-gray-900">
                Editar rol — {editingUser.name}
              </h2>
            </div>

            <form onSubmit={handleSaveRole} className="px-5 py-4 space-y-4">
              <label className="block space-y-1.5">
                <span className="text-xs font-medium text-gray-600">Rol</span>
                <select
                  value={selectedRoleId ?? ""}
                  onChange={(e) =>
                    setSelectedRoleId(
                      e.target.value === ""
                        ? null
                        : Number(e.target.value)
                    )
                  }
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-brand-200 focus:border-brand-300"
                >
                  {roles.map((role) => (
                    <option key={role.id} value={role.id}>
                      {role.name}
                    </option>
                  ))}
                </select>
              </label>

              <div className="pt-2 flex items-center justify-end gap-2">
                <LoadingButton
                  type="button"
                  onClick={closeModal}
                  disabled={saving}
                  className="inline-flex items-center justify-center gap-2 rounded-full border border-gray-200 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                >
                  Cancelar
                </LoadingButton>
                <LoadingButton
                  type="submit"
                  disabled={saving || selectedRoleId == null}
                  loading={saving}
                  loadingLabel="Guardando…"
                  className="inline-flex items-center justify-center gap-2 rounded-full bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
                >
                  Guardar cambios
                </LoadingButton>
              </div>
            </form>
          </div>
        </div>
      )}

      {userToDelete && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/35 px-4">
          <div className="w-full max-w-md rounded-xl bg-white shadow-2xl border border-gray-200">
            <div className="px-5 py-4 border-b border-gray-100">
              <h2 className="text-base font-semibold text-gray-900">
                Confirmar eliminación
              </h2>
            </div>
            <div className="px-5 py-4">
              <p className="text-sm text-gray-700">
                ¿Estás seguro de eliminar al usuario{" "}
                <span className="font-medium text-gray-900">
                  &quot;{userToDelete.name}&quot;
                </span>
                ?
              </p>
            </div>
            <div className="px-5 py-4 flex items-center justify-end gap-2 border-t border-gray-100">
              <LoadingButton
                type="button"
                onClick={closeDeleteConfirm}
                disabled={deleting}
                className="inline-flex items-center justify-center gap-2 rounded-full border border-gray-200 px-4 py-2 text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50"
              >
                Cancelar
              </LoadingButton>
              <LoadingButton
                type="button"
                onClick={handleConfirmDelete}
                disabled={deleting}
                loading={deleting}
                loadingLabel="Eliminando…"
                className="inline-flex items-center justify-center gap-2 rounded-full px-4 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-700 disabled:opacity-50"
              >
                Eliminar
              </LoadingButton>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
