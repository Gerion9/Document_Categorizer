import { Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import { RequireRole } from "./components/RequireRole";
import { AuthProvider } from "./contexts/AuthContext";
import Dashboard from "./pages/Dashboard";
import CaseWorkspace from "./pages/CaseWorkspace";
import TeamMembersPage from "./pages/TeamMembersPage";
import TeamsPage from "./pages/TeamsPage";

export default function App() {
  const token = sessionStorage.getItem("auth_token");

  if (!token) {
    window.location.href = import.meta.env.VITE_BOS_URL || "/";
    return null;
  }

  return (
    <AuthProvider>
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
    </AuthProvider>
  );
}

