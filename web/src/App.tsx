import type { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { can } from "./api";
import { useApp } from "./app-state";
import Layout from "./components/Layout";
import { Spinner } from "./components/ui";
import { AcceptInvite, Login, Setup } from "./pages/Auth";
import ChartBuilder from "./pages/ChartBuilder";
import DashboardView from "./pages/DashboardView";
import DatasetDetail from "./pages/DatasetDetail";
import Datasets from "./pages/Datasets";
import ImportReview from "./pages/ImportReview";
import { Charts, Dashboards, Imports } from "./pages/Lists";
import { ApiKeys, Audit, License, Members, SettingsHome } from "./pages/Settings";

function RequireAuth({ children }: { children: ReactNode }) {
  const { me, needsSetup } = useApp();
  const loc = useLocation();
  if (needsSetup) return <Navigate to="/setup" replace />;
  if (!me) return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  return <>{children}</>;
}

function Home() {
  const { me } = useApp();
  return <Navigate to={can.read(me?.role) ? "/datasets" : "/settings/audit"} replace />;
}

function NotFound() {
  return (
    <div className="card card-pad stack" style={{ alignItems: "flex-start" }}>
      <h1>Page not found</h1>
      <p className="muted">The page you're looking for doesn't exist or you don't have access.</p>
      <a className="btn" href="/">Go home</a>
    </div>
  );
}

export default function App() {
  const { loading, me, needsSetup } = useApp();
  if (loading)
    return (
      <div className="center-page">
        <Spinner label="Loading Prism…" />
      </div>
    );
  return (
    <Routes>
      <Route path="/setup" element={needsSetup ? <Setup /> : <Navigate to="/" replace />} />
      <Route path="/login" element={me ? <Navigate to="/" replace /> : needsSetup ? <Navigate to="/setup" replace /> : <Login />} />
      <Route path="/invite/:token" element={<AcceptInvite />} />
      <Route element={<RequireAuth><Layout /></RequireAuth>}>
        <Route index element={<Home />} />
        <Route path="/datasets" element={<Datasets />} />
        <Route path="/datasets/:id" element={<DatasetDetail />} />
        <Route path="/imports" element={<Imports />} />
        <Route path="/imports/:id" element={<ImportReview />} />
        <Route path="/charts" element={<Charts />} />
        <Route path="/charts/new" element={<ChartBuilder key="new" />} />
        <Route path="/charts/:id" element={<ChartBuilder />} />
        <Route path="/dashboards" element={<Dashboards />} />
        <Route path="/dashboards/:id" element={<DashboardView />} />
        <Route path="/settings" element={<SettingsHome />} />
        <Route path="/settings/members" element={<Members />} />
        <Route path="/settings/api-keys" element={<ApiKeys />} />
        <Route path="/settings/license" element={<License />} />
        <Route path="/settings/audit" element={<Audit />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
