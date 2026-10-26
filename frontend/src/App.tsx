import { useEffect } from "react";
import { Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { Loading, NoAccess, SignIn, Unavailable, UserMenu } from "./components/AccountPages";
import { useAuth } from "./auth";
import { PAGES, type PageKey } from "./pageMeta";
import Evaluations from "./pages/Evaluations";
import Factory from "./pages/Factory";
import Guardrails from "./pages/Guardrails";
import Home from "./pages/Home";
import Marketplace from "./pages/Marketplace";
import Playground from "./pages/Playground";
import { useSummary } from "./summary";

function Stamp() {
  const { summary: s } = useSummary();
  if (!s) return <span id="stamp" />;
  const when = new Date(s.fetchedAt * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  const title = s.refreshError ? `Last refresh failed, showing saved data: ${s.refreshError}` : s.fromDisk ? "Loaded from the saved local cache" : "";
  return <span id="stamp" title={title}>Scanned {when}{s.refreshing ? " · refreshing…" : ""}</span>;
}

export default function App() {
  const { pathname } = useLocation();
  const { summary } = useSummary();
  const { status, me, error } = useAuth();
  useEffect(() => { if (pathname === "/") document.title = "Agent Hub"; }, [pathname]);
  if (status === "loading") return <Loading />;
  if (status === "error") return <Unavailable message={error} />;
  if (status === "out") return <SignIn />;
  if (me && !me.access) return <NoAccess />;
  return (
    <>
      {/* Pages use hash routes, so the skip link focuses <main> in script instead of changing the hash. */}
      <a className="skip" href="#/" onClick={(e) => { e.preventDefault(); const m = document.querySelector("main"); m?.setAttribute("tabindex", "-1"); m?.focus(); }}>Skip to content</a>
      {summary?.demo && <div className="demo">Demo mode: showing sample data, not your Azure resources.</div>}
      <div className="topbar"><div className="topbar-in">
        <Link className="brand" to="/">
          <span className="logo">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="3" /><circle cx="5" cy="6" r="1.6" /><circle cx="19" cy="6" r="1.6" /><circle cx="12" cy="20" r="1.6" />
              <path d="M6.3 7.2 10 10.5M17.7 7.2 14 10.5M12 15v3.4" />
            </svg>
          </span>
          Agent Hub
        </Link>
        <nav className="topnav" aria-label="Main">
          {(Object.keys(PAGES) as PageKey[]).map((k) => (
            <NavLink key={k} to={`/${k}`} className={({ isActive }) => (isActive ? "on" : "")}>{PAGES[k][0]}</NavLink>
          ))}
        </nav>
        <Stamp />
        <UserMenu />
      </div></div>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/marketplace" element={<Marketplace />} />
        <Route path="/factory" element={<Factory />} />
        <Route path="/guardrails" element={<Guardrails />} />
        <Route path="/evals" element={<Evaluations />} />
        <Route path="/playground" element={<Playground />} />
        <Route path="*" element={<Home />} />
      </Routes>
      <footer>Agent Hub &middot; Azure AI Foundry</footer>
    </>
  );
}
