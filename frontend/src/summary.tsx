import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "./api";
import { useAuth } from "./auth";
import type { Summary } from "./types";

interface Ctx { summary: Summary | null; reload: () => Promise<void> }
const SummaryCtx = createContext<Ctx>({ summary: null, reload: async () => {} });
export const useSummary = () => useContext(SummaryCtx);

/** Loads /api/summary once, and keeps polling while the server refreshes its catalog in the background. */
export function SummaryProvider({ children }: { children: ReactNode }) {
  const [summary, setSummary] = useState<Summary | null>(null);
  const timer = useRef<number | undefined>(undefined);

  const reload = useCallback(async () => {
    window.clearTimeout(timer.current);
    try {
      const s = await api.summary();
      setSummary(s);
      if (s.refreshing) timer.current = window.setTimeout(() => void reload(), 4000);
    } catch { /* the pages show their own errors */ }
  }, []);

  const { status, me } = useAuth();   // nothing is requested until the user is signed in and holds a role
  const allowed = status === "in" && !!me?.access;
  useEffect(() => {
    if (allowed) void reload(); else setSummary(null);
    return () => window.clearTimeout(timer.current);
  }, [reload, allowed]);
  return <SummaryCtx.Provider value={{ summary, reload }}>{children}</SummaryCtx.Provider>;
}
