import { lazy, Suspense } from "react";
import { Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import { RequireRole } from "./components/RequireRole";
import { AuthProvider } from "./contexts/AuthContext";

const Dashboard = lazy(() => import("./pages/Dashboard"));
const CaseWorkspace = lazy(() => import("./pages/CaseWorkspace"));
const TeamMembersPage = lazy(() => import("./pages/TeamMembersPage"));
const TeamsPage = lazy(() => import("./pages/TeamsPage"));

function RouteFallback() {
  return (
    <div className="flex min-h-[40vh] items-center justify-center text-sm text-brand-500">
      Loading...
    </div>
  );
}

export default function App() {
  const token = sessionStorage.getItem("auth_token");

  if (!token) {
    window.location.href = import.meta.env.VITE_BOS_URL || "/";
    return null;
  }

  return (
    <AuthProvider>
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/cases/:caseId" element={<CaseWorkspace />} />
            <Route element={<RequireRole roles={["supervisor", "admin"]} />}>
              <Route path="/teams" element={<TeamsPage />} />
            </Route>
            <Route element={<RequireRole role="admin" />}>
              <Route path="/team-members" element={<TeamMembersPage />} />
            </Route>
          </Route>
        </Routes>
      </Suspense>
    </AuthProvider>
  );
}

