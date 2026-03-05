import { Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import CaseWorkspace from "./pages/CaseWorkspace";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/cases/:caseId" element={<CaseWorkspace />} />
      </Route>
    </Routes>
  );
}

