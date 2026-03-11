import { useEffect, useRef, useState } from "react";
import { Outlet, Link } from "react-router-dom";
import { FileStack, User, ChevronDown, UserPlus, LogOut } from "lucide-react";
import toast from "react-hot-toast";
import { GlassSurface } from "./glass/GlassSurface";
import { authApi } from "../api/client";

export default function Layout() {
  const [userName, setUserName] = useState("Usuario");
  const [userRole, setUserRole] = useState("Sin rol");
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let mounted = true;

    const loadUser = async () => {
      try {
        const me = await authApi.getMe();
        if (!mounted) return;
        setUserName(me.name || me.email || "Usuario");
        const firstRole = me.roles?.[0] ?? "";
        setUserRole(
          firstRole
            ? firstRole.charAt(0).toUpperCase() + firstRole.slice(1)
            : "Sin rol"
        );
      } catch {
        // Keep fallback name when auth profile is unavailable.
      }
    };

    loadUser();

    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    const onDocumentClick = (event: MouseEvent) => {
      if (!menuRef.current) return;
      if (menuRef.current.contains(event.target as Node)) return;
      setMenuOpen(false);
    };

    document.addEventListener("mousedown", onDocumentClick);
    return () => document.removeEventListener("mousedown", onDocumentClick);
  }, []);

  const handleLogout = () => {
    sessionStorage.removeItem("auth_token");
    setMenuOpen(false);
    window.location.reload();
  };

  const handleAddUser = () => {
    setMenuOpen(false);
    toast("Agregar usuario: en construccion");
  };

  return (
    <div className="min-h-screen flex flex-col relative overflow-x-hidden">
      {/* ── Top navbar ───────────────────────────────────────────── */}
      <GlassSurface
        as="header"
        filterId="glass-header"
        className="fixed top-0 left-0 right-0 z-50 rounded-none border-t-0 border-l-0 border-r-0 border-b border-glass-border shadow-glass overflow-visible"
        contentClassName="relative z-10 h-full overflow-visible"
      >
        <div className="max-w-screen-2xl mx-auto flex items-center gap-4 px-6 py-3">
          <div className="p-2.5 bg-gradient-to-tr from-brand-600 to-brand-400 rounded-xl shadow-inner text-white relative overflow-hidden group">
            <div className="absolute inset-0 bg-white/20 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700 ease-in-out"></div>
            <FileStack className="w-6 h-6 relative z-10" />
          </div>
          <Link to="/" className="flex items-baseline gap-2 hover:opacity-80 transition-opacity">
            <span className="text-2xl font-extrabold tracking-tight text-gray-900 drop-shadow-sm">NOVA</span>
            <span className="hidden sm:inline-block text-sm font-medium text-gray-500 tracking-wide uppercase">Indexacion Documental</span>
          </Link>

          <div className="ml-auto relative" ref={menuRef}>
            <div className="inline-flex items-center gap-2 text-sm text-gray-800">
              <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-gradient-to-tr from-brand-600 to-brand-400 text-white">
                <User className="h-3.5 w-3.5" />
              </span>
              <span className="max-w-[170px] truncate text-[13px] font-semibold tracking-tight">
                {userName}
              </span>
              <button
                type="button"
                aria-label="Abrir menu de usuario"
                onClick={() => setMenuOpen((prev) => !prev)}
                className="inline-flex h-7 w-7 items-center justify-center rounded-full text-gray-600 hover:bg-gray-100/80 transition-colors"
              >
                <ChevronDown className="h-4 w-4" />
              </button>
            </div>

            {menuOpen && (
              <div className="absolute right-0 mt-2 z-[70] w-52 rounded-2xl border border-gray-200 bg-white shadow-xl overflow-hidden">
                <div className="px-4 py-3 border-b border-gray-100">
                  <p className="text-sm font-semibold text-gray-900 break-words whitespace-normal">{userName}</p>
                  <p className="text-xs text-gray-500 break-words whitespace-normal">{userRole}</p>
                </div>
                <button
                  type="button"
                  onClick={handleAddUser}
                  className="w-full px-4 py-2.5 text-sm text-left text-gray-700 hover:bg-gray-100 inline-flex items-center gap-2"
                >
                  <UserPlus className="w-4 h-4" />
                  Agregar usuario
                </button>
                <button
                  type="button"
                  onClick={handleLogout}
                  className="w-full px-4 py-2.5 text-sm text-left text-red-600 hover:bg-red-50 inline-flex items-center gap-2"
                >
                  <LogOut className="w-4 h-4" />
                  Cerrar sesion
                </button>
              </div>
            )}
          </div>
        </div>
      </GlassSurface>

      {/* ── Page content ─────────────────────────────────────────── */}
      <main className="flex-1 pt-24 pb-8">
        <Outlet />
      </main>
    </div>
  );
}
