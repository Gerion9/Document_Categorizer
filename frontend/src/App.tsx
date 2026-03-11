import { Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import CaseWorkspace from "./pages/CaseWorkspace";

export default function App() {
  const token = sessionStorage.getItem("auth_token");

  if (!token) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-950 text-white">
        <div className="text-center space-y-4">
          <h1 className="text-2xl font-semibold">Acceso no autorizado</h1>
          <p className="text-gray-400">Debes ingresar desde BOS para acceder a esta aplicación.</p>
        </div>
      </div>
    );
  }

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/cases/:caseId" element={<CaseWorkspace />} />
      </Route>
    </Routes>
  );
}

