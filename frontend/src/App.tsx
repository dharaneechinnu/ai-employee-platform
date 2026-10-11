import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { Spinner } from "./components/ui";
import { useAuth, useIsAdmin } from "./lib/auth";
import Approvals from "./pages/Approvals";
import Employees from "./pages/Employees";
import Login from "./pages/Login";
import Members from "./pages/Members";
import Memory from "./pages/Memory";
import PlatformAdmin from "./pages/PlatformAdmin";
import Policies from "./pages/Policies";
import Providers from "./pages/Providers";
import Tasks from "./pages/Tasks";

/** Admin-only screens redirect rather than render an empty page. */
function AdminOnly({ children }: { children: React.ReactNode }) {
  return useIsAdmin() ? <>{children}</> : <Navigate to="/tasks" replace />;
}

export default function App() {
  const { me, loading } = useAuth();

  // Wait for the refresh attempt before deciding. Rendering the login
  // page first would flash it at every signed-in user on reload.
  if (loading) return <Spinner />;

  if (!me) {
    return (
      <Routes>
        <Route path="/platform" element={<PlatformAdmin />} />
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return (
    <Routes>
      {/* Outside the company layout: separate session, separate token. */}
      <Route path="/platform" element={<PlatformAdmin />} />
      <Route element={<Layout />}>
        <Route path="/tasks" element={<Tasks />} />
        <Route path="/employees" element={<Employees />} />
        <Route path="/memory" element={<Memory />} />
        <Route path="/members" element={<Members />} />
        <Route
          path="/approvals"
          element={
            <AdminOnly>
              <Approvals />
            </AdminOnly>
          }
        />
        <Route
          path="/providers"
          element={
            <AdminOnly>
              <Providers />
            </AdminOnly>
          }
        />
        <Route
          path="/policies"
          element={
            <AdminOnly>
              <Policies />
            </AdminOnly>
          }
        />
        <Route path="*" element={<Navigate to="/tasks" replace />} />
      </Route>
    </Routes>
  );
}
