import {
  FormEvent,
  KeyboardEvent,
  ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { Link, useNavigate } from "react-router-dom";
import {
  Plus,
  Trash2,
  FileStack,
  FileText,
  CheckSquare,
  Users,
  Loader2,
  MoreVertical,
  Pencil,
  FolderOpen,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Search,
  X,
} from "lucide-react";
import toast from "react-hot-toast";
import { AnimatePresence, motion } from "framer-motion";
import { EmptyState } from "../components/ui/EmptyState";
import { LoadingSkeleton } from "../components/ui/LoadingSkeleton";
import { Tooltip } from "../components/ui/Tooltip";
import { GlassButton } from "../components/glass/GlassButton";
import { SolidCard } from "../components/ui/SolidCard";
import { CaseCard } from "../components/ui/CaseCard";
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
  updateCase,
  deleteCase,
} from "../api/client";

type DashboardCase = Case | SupervisorCase;
type DashboardRole = "admin" | "supervisor" | "casemanager" | "none";

const CASEMANAGER_ROLE_ALIASES = ["casemanager", "casemanger", "casemaneger"];
const CASES_GRID_PAGE_SIZE = 9;

const isSupervisorCase = (value: DashboardCase): value is SupervisorCase =>
  "case_manager" in value;

const getCaseUuid = (value: DashboardCase) =>
  "case_uuid" in value ? value.case_uuid : value.id;

const matchesCaseSearch = (caseItem: DashboardCase, query: string) => {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) return true;

  const searchableText = [
    caseItem.name,
    caseItem.description,
    isSupervisorCase(caseItem)
      ? caseItem.case_manager.name
      : caseItem.created_by_name,
    isSupervisorCase(caseItem) ? caseItem.team.name : "",
  ]
    .filter((value): value is string => Boolean(value?.trim()))
    .join(" ")
    .toLowerCase();

  return searchableText.includes(normalizedQuery);
};

interface CaseFormFieldsProps {
  nameId: string;
  descId: string;
  name: string;
  description: string;
  onNameChange: (value: string) => void;
  onDescriptionChange: (value: string) => void;
  onNameKeyDown?: (event: KeyboardEvent<HTMLInputElement>) => void;
}

interface CaseFormModalProps {
  open: boolean;
  title: string;
  titleId: string;
  onClose: () => void;
  closeDisabled?: boolean;
  children: ReactNode;
}

function CaseFormModal({
  open,
  title,
  titleId,
  onClose,
  closeDisabled = false,
  children,
}: CaseFormModalProps) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;

    const scrollY = window.scrollY;
    const { style } = document.body;
    const previous = {
      overflow: style.overflow,
      position: style.position,
      top: style.top,
      width: style.width,
    };
    style.overflow = "hidden";
    style.position = "fixed";
    style.top = `-${scrollY}px`;
    style.width = "100%";

    const focusFrame = requestAnimationFrame(() => {
      const nameInput =
        panelRef.current?.querySelector<HTMLInputElement>("input");
      nameInput?.focus({ preventScroll: true });
    });

    return () => {
      cancelAnimationFrame(focusFrame);
      style.overflow = previous.overflow;
      style.position = previous.position;
      style.top = previous.top;
      style.width = previous.width;
      window.scrollTo(0, scrollY);
    };
  }, [open]);

  if (!open) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center bg-nova-slate/60 p-4 sm:p-8"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      onClick={closeDisabled ? undefined : onClose}
    >
      <div
        ref={panelRef}
        className="relative max-h-[calc(100vh-2rem)] w-full max-w-lg overflow-y-auto rounded-2xl border border-gray-200 bg-white p-6 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id={titleId} className="mb-4 text-lg font-bold text-gray-800">
          {title}
        </h2>
        {children}
      </div>
    </div>,
    document.body
  );
}

function CaseFormFields({
  nameId,
  descId,
  name,
  description,
  onNameChange,
  onDescriptionChange,
  onNameKeyDown,
}: CaseFormFieldsProps) {
  return (
    <div className="space-y-4">
      <div>
        <label className="label-caps" htmlFor={nameId}>
          Nombre
        </label>
        <input
          id={nameId}
          className="input-glass"
          placeholder="Ej. Juan Pérez"
          value={name}
          onChange={(event) => onNameChange(event.target.value)}
          onKeyDown={onNameKeyDown}
        />
      </div>
      <div>
        <label className="label-caps" htmlFor={descId}>
          Descripción (opcional)
        </label>
        <textarea
          id={descId}
          className="input-glass resize-none"
          placeholder="Detalles adicionales del caso…"
          value={description}
          onChange={(event) => onDescriptionChange(event.target.value)}
          rows={2}
        />
      </div>
    </div>
  );
}

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
  const [openMenuCaseId, setOpenMenuCaseId] = useState<string | null>(null);
  const [editingCase, setEditingCase] = useState<DashboardCase | null>(null);
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [savingEdit, setSavingEdit] = useState(false);
  const [creatingCase, setCreatingCase] = useState(false);
  const [casesGridPage, setCasesGridPage] = useState(1);
  const [showCasesSearchPanel, setShowCasesSearchPanel] = useState(false);
  const [casesSearchQuery, setCasesSearchQuery] = useState("");

  const canEditCases =
    roleMode === "admin" || roleMode === "casemanager";
  const canDeleteCases = roleMode === "admin";
  const showCaseMenu = canEditCases || canDeleteCases;

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
    if (!openMenuCaseId && !editingCase && !showNew) return;
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpenMenuCaseId(null);
      if (savingEdit) return;
      if (editingCase) {
        setEditingCase(null);
        setEditName("");
        setEditDesc("");
      }
      if (showNew) closeCreateModal();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [openMenuCaseId, editingCase, savingEdit, showNew]);

  useEffect(() => {
    if (!openMenuCaseId) return;
    const closeMenu = () => setOpenMenuCaseId(null);
    document.addEventListener("click", closeMenu);
    return () => document.removeEventListener("click", closeMenu);
  }, [openMenuCaseId]);

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
    if (!newName.trim() || creatingCase) return;
    setCreatingCase(true);
    try {
      const c = await createCase(newName.trim(), newDesc.trim());
      toast.success("Expediente creado");
      setShowNew(false);
      setNewName("");
      setNewDesc("");
      navigate(`/cases/${c.id}`);
    } catch {
      toast.error("Error al crear expediente");
    } finally {
      setCreatingCase(false);
    }
  };

  const openEditModal = (caseItem: DashboardCase) => {
    setShowNew(false);
    setNewName("");
    setNewDesc("");
    setEditingCase(caseItem);
    setEditName(caseItem.name);
    setEditDesc(caseItem.description ?? "");
    setOpenMenuCaseId(null);
  };

  const closeCreateModal = () => {
    if (creatingCase) return;
    setShowNew(false);
    setNewName("");
    setNewDesc("");
  };

  const closeEditModal = () => {
    if (savingEdit) return;
    setEditingCase(null);
    setEditName("");
    setEditDesc("");
  };

  const handleSaveEdit = async (event: FormEvent) => {
    event.preventDefault();
    if (!editingCase || !editName.trim()) return;
    const caseId = getCaseUuid(editingCase);
    setSavingEdit(true);
    try {
      const updated = await updateCase(caseId, {
        name: editName.trim(),
        description: editDesc.trim(),
      });
      setCases((current) =>
        current.map((item) => {
          if (getCaseUuid(item) !== caseId) return item;
          if (isSupervisorCase(item)) {
            return {
              ...item,
              name: updated.name,
              description: updated.description,
              updated_at: updated.updated_at,
            };
          }
          return { ...item, ...updated };
        })
      );
      toast.success("Expediente actualizado");
      closeEditModal();
    } catch {
      toast.error("No se pudo actualizar el expediente.");
    } finally {
      setSavingEdit(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (roleMode !== "admin") return;
    setOpenMenuCaseId(null);
    if (deletingCaseIds.has(id)) return;
    if (!confirm("¿Eliminar este expediente permanentemente?")) return;
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

  const memberFilteredCases =
    roleMode === "supervisor" && selectedMemberId !== "all"
      ? cases.filter(
          (caseItem) =>
            isSupervisorCase(caseItem) &&
            String(caseItem.case_manager.id) === selectedMemberId
        )
      : cases;

  const filteredCases = useMemo(
    () =>
      memberFilteredCases.filter((caseItem) =>
        matchesCaseSearch(caseItem, casesSearchQuery)
      ),
    [memberFilteredCases, casesSearchQuery]
  );

  const hasActiveCaseSearch = casesSearchQuery.trim().length > 0;

  const casesGridTotalPages = useMemo(
    () => Math.max(1, Math.ceil(filteredCases.length / CASES_GRID_PAGE_SIZE)),
    [filteredCases.length]
  );

  const safeCasesGridPage = Math.min(casesGridPage, casesGridTotalPages);

  const paginatedCases = useMemo(() => {
    const start = (safeCasesGridPage - 1) * CASES_GRID_PAGE_SIZE;
    return filteredCases.slice(start, start + CASES_GRID_PAGE_SIZE);
  }, [filteredCases, safeCasesGridPage]);

  const casesGridRangeStart =
    filteredCases.length === 0
      ? 0
      : (safeCasesGridPage - 1) * CASES_GRID_PAGE_SIZE + 1;
  const casesGridRangeEnd = Math.min(
    safeCasesGridPage * CASES_GRID_PAGE_SIZE,
    filteredCases.length
  );

  const goToCasesGridPage = useCallback((page: number) => {
    setCasesGridPage(Math.min(Math.max(page, 1), casesGridTotalPages));
  }, [casesGridTotalPages]);

  useEffect(() => {
    setCasesGridPage(1);
  }, [selectedTeamUuid, selectedMemberId, roleMode, casesSearchQuery]);

  useEffect(() => {
    if (casesGridPage > casesGridTotalPages) {
      setCasesGridPage(casesGridTotalPages);
    }
  }, [casesGridPage, casesGridTotalPages]);

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
    <div className="page-container">
      <header className="dashboard-section-header">
        <div>
          <h1 className="page-title">Expedientes</h1>
          <p className="page-subtitle">
            Gestiona y organiza tus expedientes
          </p>
        </div>
        <div className="flex items-center gap-2">
          {roleMode === "supervisor" && (
            <Tooltip
              content={
                showMemberFilter
                  ? "Ocultar filtro de miembros"
                  : "Filtrar por miembro"
              }
            >
              <GlassButton
                variant="ghost"
                iconOnly
                onClick={() => setShowMemberFilter((prev) => !prev)}
                aria-pressed={showMemberFilter}
                aria-label={
                  showMemberFilter
                    ? "Ocultar filtro de miembros"
                    : "Filtrar por miembro"
                }
                isActive={showMemberFilter}
              >
                <Users className="w-4 h-4" aria-hidden="true" />
              </GlassButton>
            </Tooltip>
          )}
          {!loading && cases.length > 0 && (
            <Tooltip content="Buscar por nombre, descripción o responsable">
              <GlassButton
                variant="ghost"
                iconOnly
                type="button"
                onClick={() => setShowCasesSearchPanel((prev) => !prev)}
                aria-pressed={showCasesSearchPanel}
                aria-label="Buscar expedientes"
                isActive={showCasesSearchPanel}
              >
                <Search className="w-4 h-4" aria-hidden="true" />
              </GlassButton>
            </Tooltip>
          )}
          {(roleMode === "admin" ||
            roleMode === "casemanager" ||
            roleMode === "supervisor") && (
            <Tooltip content="Nuevo expediente">
              <GlassButton
                variant="primary"
                iconOnly
                aria-label="Nuevo expediente"
                onClick={() => {
                  closeEditModal();
                  setShowNew(true);
                }}
              >
                <Plus className="w-4 h-4" aria-hidden="true" />
              </GlassButton>
            </Tooltip>
          )}
        </div>
      </header>

      {roleMode === "supervisor" && showMemberFilter && (
        <SolidCard className="mb-6 p-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1">
              <span className="text-xs font-semibold text-gray-600 uppercase tracking-wider">
                Equipo
              </span>
              <select
                className="input-glass py-2"
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
                className="input-glass py-2"
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
        </SolidCard>
      )}

      <AnimatePresence>
        {!loading && showCasesSearchPanel && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="mb-6 overflow-hidden"
          >
            <SolidCard className="rounded-xl p-4">
              <div className="mb-3 flex items-center gap-2">
                <Search className="h-4 w-4 text-brand-600" aria-hidden="true" />
                <h2 className="text-sm font-semibold text-brand-800">
                  Buscar expedientes
                </h2>
              </div>
              <div className="flex gap-2">
                <input
                  type="search"
                  className="input-glass flex-1 py-2 text-sm"
                  placeholder="Nombre, descripción o responsable…"
                  value={casesSearchQuery}
                  onChange={(event) => setCasesSearchQuery(event.target.value)}
                  aria-label="Buscar expedientes"
                />
                {hasActiveCaseSearch && (
                  <Tooltip content="Limpiar búsqueda">
                    <GlassButton
                      type="button"
                      variant="secondary"
                      size="sm"
                      iconOnly
                      aria-label="Limpiar búsqueda"
                      onClick={() => setCasesSearchQuery("")}
                    >
                      <X className="h-3.5 w-3.5" aria-hidden="true" />
                    </GlassButton>
                  </Tooltip>
                )}
              </div>
            </SolidCard>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Loading */}
      {loading && <LoadingSkeleton />}

      {/* Empty state */}
      {!loading && memberFilteredCases.length === 0 && (
        <div className="py-16">
          <EmptyState
            icon="briefcase"
            title="Sin expedientes"
            description="No hay expedientes. Crea uno para comenzar a clasificar y analizar documentos."
          />
        </div>
      )}

      {!loading &&
        memberFilteredCases.length > 0 &&
        filteredCases.length === 0 &&
        hasActiveCaseSearch && (
          <div className="py-16">
            <EmptyState
              icon="briefcase"
              title="Sin resultados"
              description={`No hay expedientes que coincidan con "${casesSearchQuery.trim()}".`}
            />
          </div>
        )}

      {/* Case cards grid */}
      {!loading && filteredCases.length > 0 && (
        <>
      <div id="cases-grid" className="grid auto-rows-fr gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {paginatedCases.map((c) => {
          const caseId = getCaseUuid(c);
          const isDeleting = deletingCaseIds.has(caseId);
          const casePath = `/cases/${caseId}`;
          const pagesLabel = isSupervisorCase(c)
            ? null
            : `${c.page_count} página${c.page_count === 1 ? "" : "s"}`;
          const formsLabel = isSupervisorCase(c)
            ? null
            : `${c.generated_form_count} formulario${
                c.generated_form_count === 1 ? "" : "s"
              } generado${c.generated_form_count === 1 ? "" : "s"}`;
          const checklistsLabel = isSupervisorCase(c)
            ? null
            : `${c.checklist_count} checklist${c.checklist_count === 1 ? "" : "s"}`;

          const cardMenu =
            showCaseMenu && !isDeleting ? (
              <div
                className="relative shrink-0 -mt-0.5"
                onClick={(event) => event.stopPropagation()}
                onMouseDown={(event) => event.stopPropagation()}
              >
                <button
                  type="button"
                  onMouseDown={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                  }}
                  onClick={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    setOpenMenuCaseId((prev) =>
                      prev === caseId ? null : caseId
                    );
                  }}
                  aria-label={`Acciones para ${c.name}`}
                  aria-expanded={openMenuCaseId === caseId}
                  aria-haspopup="menu"
                  className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-brand-500 transition-colors hover:bg-brand-50 hover:text-brand-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300"
                >
                  <MoreVertical className="h-4 w-4" aria-hidden="true" />
                </button>
                {openMenuCaseId === caseId && (
                  <div
                    role="menu"
                    className="absolute right-0 top-full z-[60] mt-1 flex w-56 flex-col rounded-lg border border-brand-100 bg-white py-1 shadow-xl"
                  >
                    <button
                      type="button"
                      role="menuitem"
                      onMouseDown={(event) => event.stopPropagation()}
                      onClick={(event) => {
                        event.stopPropagation();
                        setOpenMenuCaseId(null);
                        navigate(casePath);
                      }}
                      className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-gray-700 transition-colors hover:bg-brand-50 hover:text-brand-800"
                    >
                      <FolderOpen className="h-3.5 w-3.5" aria-hidden="true" />
                      Abrir
                    </button>
                    {canEditCases && (
                      <button
                        type="button"
                        role="menuitem"
                        onMouseDown={(event) => event.stopPropagation()}
                        onClick={(event) => {
                          event.stopPropagation();
                          openEditModal(c);
                        }}
                        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-gray-700 transition-colors hover:bg-brand-50 hover:text-brand-800"
                      >
                        <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                        Editar
                      </button>
                    )}
                    {canDeleteCases && (
                      <>
                        <div className="my-1 h-px bg-gray-100" />
                        <button
                          type="button"
                          role="menuitem"
                          onMouseDown={(event) => event.stopPropagation()}
                          onClick={(event) => {
                            event.stopPropagation();
                            handleDelete(caseId);
                          }}
                          className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-red-600 transition-colors hover:bg-red-50"
                        >
                          <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                          Eliminar
                        </button>
                      </>
                    )}
                  </div>
                )}
              </div>
            ) : null;

          const cardTitle = (
            <>
              <h3
                className={`font-heading font-bold text-xl leading-snug transition-colors ${
                  isDeleting
                    ? "text-red-700"
                    : "text-brand-800 group-hover/card:text-brand-700"
                }`}
              >
                {c.name}
              </h3>
              {isDeleting && (
                <div
                  role="status"
                  aria-live="polite"
                  className="mt-1.5 inline-flex items-center gap-1.5 rounded-full bg-red-100/90 px-2.5 py-0.5 text-xs font-semibold text-red-700"
                >
                  <Loader2
                    aria-hidden="true"
                    className="h-3.5 w-3.5 animate-spin"
                  />
                  <span>Eliminando expediente...</span>
                </div>
              )}
            </>
          );

          const cardContent = (
            <>
              <div className="min-h-0 flex-1">
                {c.description?.trim() ? (
                  <p
                    className={`line-clamp-2 text-sm leading-snug ${
                      isDeleting ? "text-red-700/80" : "text-brand-600"
                    }`}
                  >
                    {c.description.trim()}
                  </p>
                ) : null}
              </div>

              <div className="mt-auto flex shrink-0 flex-col gap-1.5 pt-3">
                {!isSupervisorCase(c) && (
                  <p
                    className={`case-card-meta leading-snug ${
                      isDeleting ? "text-red-700/70" : ""
                    }`}
                  >
                    Creado por: {c.created_by_name?.trim() || "No especificado"}
                  </p>
                )}

                {isSupervisorCase(c) && (
                  <p
                    className={`case-card-meta leading-snug ${
                      isDeleting ? "text-red-700/70" : ""
                    }`}
                  >
                    Responsable: {c.case_manager.name} · Equipo: {c.team.name}
                  </p>
                )}

                <div
                  className={`flex items-center justify-between border-t pt-3 ${
                    isDeleting ? "border-red-200/60" : "border-brand-100/80"
                  }`}
                >
                <div
                  className={`flex items-center gap-3 ${
                    isDeleting ? "text-red-700/80" : ""
                  }`}
                >
                  {isSupervisorCase(c) ? (
                    <div
                      className="case-card-stat"
                      title={`Responsable: ${c.case_manager.name}`}
                      aria-label={`Responsable: ${c.case_manager.name}`}
                    >
                      <Users aria-hidden="true" className="w-3.5 h-3.5 text-brand-600" />
                      <span>{c.case_manager.name}</span>
                    </div>
                  ) : (
                    <>
                      <Tooltip content={pagesLabel ?? ""}>
                        <div className="case-card-stat" aria-label={pagesLabel ?? undefined}>
                          <FileStack aria-hidden="true" className="w-3.5 h-3.5 text-brand-600" />
                          <span>{c.page_count}</span>
                        </div>
                      </Tooltip>
                      <Tooltip content={formsLabel ?? ""}>
                        <div className="case-card-stat" aria-label={formsLabel ?? undefined}>
                          <FileText aria-hidden="true" className="w-3.5 h-3.5 text-brand-600" />
                          <span>{c.generated_form_count}</span>
                        </div>
                      </Tooltip>
                      <Tooltip content={checklistsLabel ?? ""}>
                        <div className="case-card-stat" aria-label={checklistsLabel ?? undefined}>
                          <CheckSquare aria-hidden="true" className="w-3.5 h-3.5 text-brand-600" />
                          <span>{c.checklist_count}</span>
                        </div>
                      </Tooltip>
                    </>
                  )}
                </div>
                <time
                  dateTime={c.updated_at}
                  className={`text-[10px] font-medium uppercase tracking-wider ${
                    isDeleting ? "text-red-400" : "text-brand-400"
                  }`}
                  title={`Última actualización: ${formatLongDate(c.updated_at)}`}
                >
                  {formatLongDate(c.updated_at).toUpperCase()}
                </time>
                </div>
              </div>
            </>
          );

          const linkClassName =
            "block min-w-0 rounded-2xl text-inherit no-underline focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 focus-visible:ring-offset-2";

          return (
            <CaseCard
              key={caseId}
              aria-disabled={isDeleting}
              className={`relative flex h-full flex-col px-6 py-5 transition-[box-shadow,border-color] duration-200 ${
                isDeleting ? "border-red-200/80 bg-red-50/35 opacity-70" : ""
              }`}
            >
              {isDeleting ? (
                <div className="flex min-h-0 flex-1 cursor-progress flex-col">
                  <div className="mb-1.5">{cardTitle}</div>
                  {cardContent}
                </div>
              ) : (
                <>
                  <div className="relative z-10 mb-1.5 flex shrink-0 items-start gap-1">
                    <Link
                      to={casePath}
                      className={`${linkClassName} flex-1`}
                      aria-label={`Abrir expediente ${c.name}`}
                    >
                      {cardTitle}
                    </Link>
                    {cardMenu}
                  </div>
                  <Link
                    to={casePath}
                    className={`${linkClassName} flex min-h-0 flex-1 flex-col`}
                    aria-label={`Abrir expediente ${c.name}`}
                  >
                    {cardContent}
                  </Link>
                </>
              )}
            </CaseCard>
          );
        })}
      </div>

      {filteredCases.length > CASES_GRID_PAGE_SIZE && (
        <nav
          aria-label="Paginación de expedientes"
          className="mt-6 flex flex-col items-center justify-center gap-3 sm:flex-row sm:justify-between"
        >
          <p className="text-xs font-medium text-brand-600">
            Mostrando {casesGridRangeStart}&ndash;{casesGridRangeEnd} de{" "}
            {filteredCases.length} expedientes
          </p>
          <div className="inline-flex items-center gap-1">
            <Tooltip content="Primera página">
              <GlassButton
                type="button"
                variant="secondary"
                size="xs"
                iconOnly
                onClick={() => goToCasesGridPage(1)}
                disabled={safeCasesGridPage === 1}
                aria-label="Ir a la primera página"
                className="bg-white/75"
              >
                <ChevronsLeft className="h-4 w-4" aria-hidden="true" />
              </GlassButton>
            </Tooltip>
            <Tooltip content="Página anterior">
              <GlassButton
                type="button"
                variant="secondary"
                size="xs"
                iconOnly
                onClick={() => goToCasesGridPage(safeCasesGridPage - 1)}
                disabled={safeCasesGridPage === 1}
                aria-label="Página anterior"
                className="bg-white/75"
              >
                <ChevronLeft className="h-4 w-4" aria-hidden="true" />
              </GlassButton>
            </Tooltip>
            <span className="min-w-[5.5rem] px-2 text-center text-sm font-semibold text-brand-800">
              {safeCasesGridPage} / {casesGridTotalPages}
            </span>
            <Tooltip content="Página siguiente">
              <GlassButton
                type="button"
                variant="secondary"
                size="xs"
                iconOnly
                onClick={() => goToCasesGridPage(safeCasesGridPage + 1)}
                disabled={safeCasesGridPage === casesGridTotalPages}
                aria-label="Página siguiente"
                className="bg-white/75"
              >
                <ChevronRight className="h-4 w-4" aria-hidden="true" />
              </GlassButton>
            </Tooltip>
            <Tooltip content="Última página">
              <GlassButton
                type="button"
                variant="secondary"
                size="xs"
                iconOnly
                onClick={() => goToCasesGridPage(casesGridTotalPages)}
                disabled={safeCasesGridPage === casesGridTotalPages}
                aria-label="Ir a la última página"
                className="bg-white/75"
              >
                <ChevronsRight className="h-4 w-4" aria-hidden="true" />
              </GlassButton>
            </Tooltip>
          </div>
        </nav>
      )}
        </>
      )}

      <CaseFormModal
        open={showNew}
        title="Crear nuevo expediente"
        titleId="new-case-title"
        onClose={closeCreateModal}
        closeDisabled={creatingCase}
      >
        <CaseFormFields
          nameId="new-case-name"
          descId="new-case-desc"
          name={newName}
          description={newDesc}
          onNameChange={setNewName}
          onDescriptionChange={setNewDesc}
          onNameKeyDown={(event) => event.key === "Enter" && handleCreate()}
        />
        <div className="mt-6 flex gap-3">
          <GlassButton
            variant="primary"
            onClick={handleCreate}
            disabled={!newName.trim()}
            loading={creatingCase}
            loadingLabel="Creando…"
          >
            Crear Expediente
          </GlassButton>
          <GlassButton variant="ghost" onClick={closeCreateModal} disabled={creatingCase}>
            Cancelar
          </GlassButton>
        </div>
      </CaseFormModal>

      <CaseFormModal
        open={!!editingCase}
        title="Editar expediente"
        titleId="edit-case-title"
        onClose={closeEditModal}
        closeDisabled={savingEdit}
      >
        <form onSubmit={handleSaveEdit}>
          <CaseFormFields
            nameId="edit-case-name"
            descId="edit-case-desc"
            name={editName}
            description={editDesc}
            onNameChange={setEditName}
            onDescriptionChange={setEditDesc}
          />
          <div className="mt-6 flex gap-3">
            <GlassButton
              variant="primary"
              type="submit"
              disabled={savingEdit || !editName.trim()}
              loading={savingEdit}
              loadingLabel="Guardando…"
            >
              Guardar cambios
            </GlassButton>
            <GlassButton
              variant="ghost"
              type="button"
              onClick={closeEditModal}
              disabled={savingEdit}
            >
              Cancelar
            </GlassButton>
          </div>
        </form>
      </CaseFormModal>
    </div>
  );
}

