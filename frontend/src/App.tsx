/// <reference types="vite/client" />
import { Navigate, Route, Routes, useLocation, useSearchParams } from "react-router-dom";
import Layout from "./components/Layout";
import { Spinner } from "./components/ui";
import { useAuth } from "./lib/auth";
import { lazy, Suspense } from "react";

// Each page is its own chunk, so the first visit downloads only the page
// it lands on rather than the whole app.
const ApproveLink = lazy(() => import("./pages/ApproveLink"));
const Approvals = lazy(() => import("./pages/Approvals"));
const Connections = lazy(() => import("./pages/Connections"));
const FilmStage = lazy(() => import("./pages/FilmStage"));
const Login = lazy(() => import("./pages/Login"));
const Register = lazy(() => import("./pages/Register"));
const Memory = lazy(() => import("./pages/Memory"));
const Notifications = lazy(() => import("./pages/Notifications"));
const PlatformAdmin = lazy(() => import("./pages/PlatformAdmin"));
const Policies = lazy(() => import("./pages/Policies"));
const Product = lazy(() => import("./pages/Product"));
const Providers = lazy(() => import("./pages/Providers"));
const Agents = lazy(() => import("./pages/Agents"));
const Chat = lazy(() => import("./pages/Chat"));

/** The promo film stage is a recording tool, so it only exists in development. */
const FILM = import.meta.env.DEV ? <FilmStage /> : <Navigate to="/" replace />;

/** After signing in, go where the person was heading (an approval
 * link, say), but only to a path inside this app. */
function AfterSignIn() {
  const [params] = useSearchParams();
  const next = params.get("next");
  const safe = next && next.startsWith("/") && !next.startsWith("//") ? next : "/chat";
  return <Navigate to={safe} replace />;
}

/** Signed out on a page that needs an account: sign in, then come back
 * to that page rather than to Chat. */
function ToSignIn() {
  const { pathname, search } = useLocation();
  const here = pathname + search;
  const to = pathname === "/" || pathname === "/login" ? "/login" : `/login?next=${encodeURIComponent(here)}`;
  return <Navigate to={to} replace />;
}

export default function App() {
  const { me, loading } = useAuth();

  // Wait for the refresh attempt before deciding. Rendering the login
  // page first would flash it at every signed-in user on reload.
  if (loading) return <Spinner />;

  if (!me) {
    return (
      <Suspense fallback={<Spinner />}>
        <Routes>
          <Route path="/" element={<Product />} />
          <Route path="/product" element={<Product />} />
          <Route path="/film" element={FILM} />
          <Route path="/platform" element={<PlatformAdmin />} />
          <Route path="/approve/:token" element={<ApproveLink />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="*" element={<ToSignIn />} />
        </Routes>
      </Suspense>
    );
  }

  return (
    <Suspense fallback={<Spinner />}>
      <Routes>
        {/* Outside the app layout: separate session, separate token. */}
        <Route path="/platform" element={<PlatformAdmin />} />
        <Route path="/approve/:token" element={<ApproveLink />} />
        <Route path="/product" element={<Product />} />
        <Route path="/film" element={FILM} />
        <Route path="/login" element={<AfterSignIn />} />
        <Route path="/register" element={<AfterSignIn />} />
        <Route element={<Layout />}>
          <Route path="/connections" element={<Connections />} />
          <Route path="/chat" element={<Chat />} />
          <Route path="/chat/:id" element={<Chat />} />
          <Route path="/agents" element={<Agents />} />
          {/* Old bookmarks and links. Tasks and the old helper list were folded
              into the assistant, which lives in chat. */}
          <Route path="/tasks" element={<Navigate to="/chat" replace />} />
          <Route path="/employees" element={<Navigate to="/chat" replace />} />
          <Route path="/memory" element={<Memory />} />
          <Route path="/usage" element={<Navigate to="/agents?tab=cost" replace />} />
          <Route path="/approvals" element={<Approvals />} />
          <Route path="/providers" element={<Providers />} />
          <Route path="/notifications" element={<Notifications />} />
          <Route path="/policies" element={<Policies />} />
          <Route path="*" element={<Navigate to="/chat" replace />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
