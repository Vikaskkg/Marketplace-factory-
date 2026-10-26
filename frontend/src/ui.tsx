import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

/* Toasts and confirmation dialogs, replacing the browser's alert() and confirm(). */

interface Toast { id: number; kind: "ok" | "bad"; text: string }
interface ConfirmOpts { title: string; body?: string; confirmLabel?: string; danger?: boolean }
interface Ctx {
  toast: (kind: "ok" | "bad", text: string) => void;
  confirm: (o: ConfirmOpts) => Promise<boolean>;
}
const UiCtx = createContext<Ctx>({ toast: () => {}, confirm: async () => false });
export const useUi = () => useContext(UiCtx);

export function UiProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [ask, setAsk] = useState<(ConfirmOpts & { resolve: (v: boolean) => void }) | null>(null);
  const dlg = useRef<HTMLDialogElement>(null);
  const next = useRef(1);

  const toast = useCallback((kind: "ok" | "bad", text: string) => {
    const id = next.current++;
    setToasts((t) => [...t, { id, kind, text }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "bad" ? 8000 : 4500);
  }, []);

  const confirm = useCallback((o: ConfirmOpts) => new Promise<boolean>((resolve) => setAsk({ ...o, resolve })), []);
  useEffect(() => { if (ask && dlg.current && !dlg.current.open) dlg.current.showModal(); }, [ask]);
  const close = (v: boolean) => { ask?.resolve(v); setAsk(null); dlg.current?.close(); };

  return (
    <UiCtx.Provider value={{ toast, confirm }}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>
            <span>{t.text}</span>
            <button aria-label="Dismiss" onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))}>×</button>
          </div>
        ))}
      </div>
      <dialog ref={dlg} className="confirm" onCancel={(e) => { e.preventDefault(); close(false); }} aria-labelledby="confirm-title">
        {ask && (
          <>
            <h3 id="confirm-title">{ask.title}</h3>
            {ask.body && <p>{ask.body}</p>}
            <div className="row">
              <button onClick={() => close(false)} autoFocus>Cancel</button>
              <button className={ask.danger ? "danger" : "primary"} onClick={() => close(true)}>{ask.confirmLabel ?? "Confirm"}</button>
            </div>
          </>
        )}
      </dialog>
    </UiCtx.Provider>
  );
}
