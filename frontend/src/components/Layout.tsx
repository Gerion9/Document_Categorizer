import { Outlet, Link } from "react-router-dom";
import { FileStack } from "lucide-react";
import { GlassSurface } from "./glass/GlassSurface";

export default function Layout() {
  return (
    <div className="min-h-screen flex flex-col relative overflow-x-hidden">
      {/* ── Top navbar ───────────────────────────────────────────── */}
      <GlassSurface
        as="header"
        filterId="glass-header"
        className="fixed top-0 left-0 right-0 z-50 rounded-none border-t-0 border-l-0 border-r-0 border-b border-glass-border shadow-glass"
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
        </div>
      </GlassSurface>

      {/* ── Page content ─────────────────────────────────────────── */}
      <main className="flex-1 pt-24 pb-8">
        <Outlet />
      </main>
    </div>
  );
}
