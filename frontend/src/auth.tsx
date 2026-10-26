import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, UNAUTHORIZED_EVENT } from "./api";
import type { Me, Role } from "./types";

const RANK: Record<Role, number> = { Viewer: 1, Builder: 2, Approver: 3, Admin: 4 };
const WARN_BEFORE_MS = 2 * 60 * 1000;

type Status = "loading" | "in" | "out" | "error";
interface Auth {
  status: Status; me: Me | null; error: string;
  /** True if the signed-in user holds at least this role. The server enforces it too; this only shapes the UI. */
  can: (role: Role) => boolean;
  expiringSoon: boolean;
  /** How sign-in works here when signed out: "azcli" means run `az login`, "entra" means the Microsoft sign-in page. */
  outMode: string;
  signIn: () => void; signOut: () => Promise<void>; stayAlive: () => Promise<void>;
  /** Re-reads the Azure CLI login, e.g. after the user ran `az login` or switched accounts. */
  recheck: () => Promise<void>;
}

const AuthCtx = createContext<Auth>({
  status: "loading", me: null, error: "", can: () => false, expiringSoon: false, outMode: "entra",
  signIn: () => {}, signOut: async () => {}, stayAlive: async () => {}, recheck: async () => {},
});
export const useAuth = () => useContext(AuthCtx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState("");
  const [expiringSoon, setExpiringSoon] = useState(false);
  const [outMode, setOutMode] = useState("entra");
  const timer = useRef<number | undefined>(undefined);

  const load = useCallback(async (refresh = false) => {
    try {
      const r = await api.me(refresh);
      if (r.status === "in") { setMe(r.me); setStatus("in"); } else { setMe(null); setOutMode(r.mode); setStatus("out"); }
    } catch (e) { setError((e as Error).message); setStatus("error"); }
  }, []);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const out = () => { setMe(null); setStatus("out"); };
    window.addEventListener(UNAUTHORIZED_EVENT, out);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, out);
  }, []);

  // Warn shortly before the session ends; "stay signed in" asks the server to extend it.
  useEffect(() => {
    window.clearTimeout(timer.current);
    setExpiringSoon(false);
    if (!me?.expiresAt) return;
    const ms = me.expiresAt * 1000 - Date.now() - WARN_BEFORE_MS;
    timer.current = window.setTimeout(() => setExpiringSoon(true), Math.max(ms, 0));
    return () => window.clearTimeout(timer.current);
  }, [me]);

  const value = useMemo<Auth>(() => ({
    status, me, error, expiringSoon, outMode,
    recheck: () => load(true),
    can: (role) => !!me?.role && RANK[me.role] >= RANK[role],
    signIn: () => { window.location.href = `/auth/login?next=${encodeURIComponent(window.location.pathname + window.location.hash)}`; },
    signOut: async () => {
      try { const r = await api.logout(); window.location.href = r.redirect; }
      catch { window.location.href = "/"; }
    },
    stayAlive: async () => { await api.keepalive(); await load(); },
  }), [status, me, error, expiringSoon, outMode, load]);

  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}
