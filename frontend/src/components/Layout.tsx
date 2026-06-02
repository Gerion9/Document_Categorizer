import { useEffect, useRef, useState } from "react";
import { Outlet, Link, useNavigate } from "react-router-dom";
import { User, Users, ChevronDown, LogOut } from "lucide-react";
import { GlassSurface } from "./glass/GlassSurface";
import { useAuth } from "../contexts/AuthContext";

const HEADER_LOGO_SRC = "https://bos.manuelsolis.com/images/logo.png";

function formatUserDisplayName(raw: string): string {
  if (!raw) return "Usuario";
  const isMostlyUpper = raw === raw.toUpperCase() && /[A-ZÁÉÍÓÚÑ]/.test(raw);
  if (!isMostlyUpper) return raw;
  return raw
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function formatUserEmail(raw?: string): string {
  if (!raw) return "";
  return raw.toLowerCase();
}

export default function Layout() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const userName = user?.name || user?.email || "Usuario";
  const displayName = formatUserDisplayName(userName);
  const displayEmail = formatUserEmail(user?.email);
  const firstRole = user?.roles?.[0] ?? "";
  const normalizedRole = firstRole.toLowerCase();
  const userRole = normalizedRole === "casemanager" || normalizedRole === "casemanger" || normalizedRole === "casemaneger"
    ? "Case Manager"
    : firstRole
      ? firstRole.charAt(0).toUpperCase() + firstRole.slice(1)
      : "Sin rol";
  const isAdmin = user?.roles?.some((r) => r.toLowerCase() === "admin") ?? false;
  const isSupervisor =
    user?.roles?.some((r) => r.toLowerCase() === "supervisor") ?? false;

  useEffect(() => {
    const onDocumentClick = (event: MouseEvent) => {
      if (!menuRef.current) return;
      if (menuRef.current.contains(event.target as Node)) return;
      setMenuOpen(false);
    };

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };

    document.addEventListener("mousedown", onDocumentClick);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onDocumentClick);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  const handleLogout = () => {
    sessionStorage.removeItem("auth_token");
    setMenuOpen(false);
    window.location.href = import.meta.env.VITE_BOS_URL || "/";
  };

  const handleAddUser = () => {
    setMenuOpen(false);
    navigate("/team-members");
  };

  const handleManageTeams = () => {
    setMenuOpen(false);
    navigate("/teams");
  };

  return (
    <div className="min-h-screen flex flex-col relative overflow-x-hidden">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[100] focus:rounded-lg focus:bg-white focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:shadow-lg"
      >
        Saltar al contenido
      </a>

      <GlassSurface
        as="header"
        filterId="glass-header"
        fallbackClassName="app-header"
        className="app-header fixed top-0 left-0 right-0 z-50 rounded-none border-t-0 border-l-0 border-r-0 overflow-visible"
        contentClassName="relative z-10 h-full overflow-visible"
      >
        <div className="max-w-screen-2xl mx-auto flex items-center gap-3 sm:gap-4 px-4 sm:px-6 py-5">
          <Link
            to="/"
            className="flex items-center gap-3 min-w-0 hover:opacity-90 transition-opacity rounded-xl focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 focus-visible:ring-offset-nova-deep"
          >
            <img
              src={HEADER_LOGO_SRC}
              alt=""
              aria-hidden="true"
              className="object-contain relative z-10 h-12 w-12 shrink-0 rounded-full"
            />
            <div className="min-w-0">
              <span className="block text-xl sm:text-2xl font-heading font-bold tracking-tight text-nova-snow">
                NOVA
              </span>
              <span className="hidden sm:block text-[11px] font-medium text-nova-ice/80 tracking-wide">
                Control de expedientes legales
              </span>
            </div>
          </Link>

          <div className="ml-auto relative" ref={menuRef}>
            <button
              type="button"
              aria-label={`Menú de ${displayName}`}
              aria-expanded={menuOpen}
              aria-haspopup="menu"
              onClick={() => setMenuOpen((prev) => !prev)}
              className={`group inline-flex items-center gap-2.5 rounded-2xl border bg-white/[0.12] pl-1.5 pr-2 py-1.5 text-left text-nova-snow shadow-glass backdrop-blur-md transition-all duration-200 hover:bg-white/[0.18] focus-visible:ring-2 focus-visible:ring-white/35 focus-visible:ring-offset-2 focus-visible:ring-offset-transparent active:scale-[0.98] ${
                menuOpen
                  ? "border-white/40 bg-white/[0.2] shadow-glass-lg"
                  : "border-white/20 hover:border-white/30"
              }`}
            >
              <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-bl from-white to-nova-ice border border-white/60 text-brand-600 shadow-glass-inner">
                <User className="h-4 w-4" aria-hidden="true" />
              </span>
              <span className="hidden md:flex min-w-0 flex-col gap-0.5 pr-0.5">
                <span className="text-[13px] font-semibold leading-none tracking-tight max-w-[152px] truncate">
                  {displayName}
                </span>
                <span className="text-[11px] font-medium leading-none text-nova-ice/75 max-w-[152px] truncate">
                  {userRole}
                </span>
              </span>
              <ChevronDown
                className={`h-4 w-4 shrink-0 text-nova-ice/80 transition-transform duration-200 group-hover:text-nova-snow ${
                  menuOpen ? "rotate-180" : ""
                }`}
                aria-hidden="true"
              />
            </button>

            {menuOpen && (
              <div
                role="menu"
                className="absolute right-0 mt-2.5 z-[70] w-72 rounded-2xl border border-white/50 bg-white/[0.97] backdrop-blur-lg shadow-glass-lg overflow-hidden animate-fade-in"
              >
                <div className="px-4 py-4 border-b border-brand-100/70 bg-gradient-to-br from-nova-ice/80 to-white/90">
                  <div className="flex items-start gap-3">
                    <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-bl from-white to-nova-ice border border-brand-100 text-brand-600 shadow-glass-inner">
                      <User className="h-4 w-4" aria-hidden="true" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <p
                          className="text-sm font-semibold text-brand-800 leading-snug"
                          title={displayName}
                        >
                          {displayName}
                        </p>
                        <span className="inline-flex items-center rounded-full bg-brand-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-brand-700 border border-brand-100">
                          {userRole}
                        </span>
                      </div>
                      {displayEmail && (
                        <p
                          className="mt-1.5 text-xs font-medium text-brand-500 break-all leading-relaxed"
                          title={displayEmail}
                        >
                          {displayEmail}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
                <div className="p-1.5">
                {(isSupervisor || isAdmin) && (
                  <button
                    type="button"
                    role="menuitem"
                    onClick={handleManageTeams}
                    className="w-full px-3 py-2.5 text-sm text-left text-brand-700 hover:bg-brand-50/80 inline-flex items-center gap-2.5 rounded-xl transition-colors"
                  >
                    <Users className="w-4 h-4 shrink-0 text-brand-500" aria-hidden="true" />
                    Administrar equipos
                  </button>
                )}
                {isAdmin && (
                  <button
                    type="button"
                    role="menuitem"
                    onClick={handleAddUser}
                    className="w-full px-3 py-2.5 text-sm text-left text-brand-700 hover:bg-brand-50/80 inline-flex items-center gap-2.5 rounded-xl transition-colors"
                  >
                    <User className="w-4 h-4 shrink-0 text-brand-500" aria-hidden="true" />
                    Administrar usuarios
                  </button>
                )}
                </div>
                <div className="border-t border-brand-100/80 p-1.5">
                <button
                  type="button"
                  role="menuitem"
                  onClick={handleLogout}
                  className="w-full px-3 py-2.5 text-sm text-left text-red-600 hover:bg-red-50 inline-flex items-center gap-2.5 rounded-xl transition-colors"
                >
                  <LogOut className="w-4 h-4 shrink-0" aria-hidden="true" />
                  Cerrar sesión
                </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </GlassSurface>

      <main
        id="main-content"
        className="app-main relative z-[1] flex-1 pt-[var(--app-header-height)] pb-6"
      >
        <Outlet />
      </main>

      <footer
        role="contentinfo"
        className="relative z-[1] shrink-0 border-t border-brand-100/60 px-4 py-3 text-center"
      >
        <p className="mx-auto max-w-3xl text-[11px] leading-relaxed text-brand-400/90">
          Los contenidos generados por IA pueden contener errores. Revise siempre
          la información con supervisión humana.
        </p>
      </footer>
    </div>
  );
}
