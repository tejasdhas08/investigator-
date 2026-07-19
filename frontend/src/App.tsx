import { Navigate, Route, Routes } from "react-router-dom";
import AdminPage from "./pages/AdminPage";
import CaseDashboard from "./pages/CaseDashboard";
import CaseList from "./pages/CaseList";
import Login from "./pages/Login";
import NewCase from "./pages/NewCase";
import Processing from "./pages/Processing";
import { useAuth } from "./state/auth";

function Guard({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="p-10 text-center text-slate-500">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/cases" element={<Guard><CaseList /></Guard>} />
      <Route path="/cases/new" element={<Guard><NewCase /></Guard>} />
      <Route path="/cases/:caseId/processing" element={<Guard><Processing /></Guard>} />
      <Route path="/cases/:caseId/*" element={<Guard><CaseDashboard /></Guard>} />
      <Route path="/admin" element={<Guard><AdminPage /></Guard>} />
      <Route path="*" element={<Navigate to="/cases" replace />} />
    </Routes>
  );
}
