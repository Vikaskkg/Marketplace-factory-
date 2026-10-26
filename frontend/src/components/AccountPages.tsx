import { useEffect, useRef, useState } from "react";
import { useAuth } from "../auth";

const Logo = () => (
  <span className="logo">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" /><circle cx="5" cy="6" r="1.6" /><circle cx="19" cy="6" r="1.6" /><circle cx="12" cy="20" r="1.6" />
      <path d="M6.3 7.2 10 10.5M17.7 7.2 14 10.5M12 15v3.4" />
    </svg>
  </span>
);

const REASONS: Record<string, string> = {
  expired: "Your sign-in attempt took too long. Please try again.",
  invalid: "We could not verify that sign-in. Please try again.",
  failed: "Sign-in was not completed. Please try again or contact your administrator.",
};

export function SignIn() {
  const { signIn, outMode, recheck } = useAuth();
  const [checking, setChecking] = useState(false);
  const reason = REASONS[new URLSearchParams(window.location.search).get("auth_error") ?? ""];
  if (outMode === "azcli") {
    return (
      <div className="gate">
        <div className="gate-card">
          <div className="gate-brand"><Logo /> <strong>Agent Hub</strong></div>
          <h1>Sign in with the Azure CLI</h1>
          <p>Agent Hub uses the account you sign in with in the Azure CLI. Open a terminal and run:</p>
          <pre className="cmd">az login</pre>
          <p className="meta">Then come back here. If you use several tenants, add <code>--tenant &lt;tenant id&gt;</code>.</p>
          <button className="primary big" disabled={checking} onClick={async () => { setChecking(true); try { await recheck(); } finally { setChecking(false); } }}>
            {checking ? "Checking…" : "I've signed in, check again"}
          </button>
        </div>
      </div>
    );
  }
  return (
    <div className="gate">
      <div className="gate-card">
        <div className="gate-brand"><Logo /> <strong>Agent Hub</strong></div>
        <h1>Sign in</h1>
        <p>Discover, build and govern AI agents across your Azure AI Foundry projects.</p>
        {reason && <div className="banner-warn" role="alert">{reason}</div>}
        <button className="primary big" onClick={signIn}>Sign in with Microsoft</button>
        <p className="meta">Use your company account. Access is based on the role assigned to you in your directory.</p>
      </div>
    </div>
  );
}

export function NoAccess() {
  const { me, signOut } = useAuth();
  return (
    <div className="gate">
      <div className="gate-card">
        <div className="gate-brand"><Logo /> <strong>Agent Hub</strong></div>
        <h1>Access not granted</h1>
        <p>You are signed in as <b>{me?.name}</b> ({me?.email}), but no Agent Hub role has been assigned to your account.</p>
        <p className="meta">Ask your administrator for the Viewer, Builder, Approver or Admin role, then sign in again.</p>
        <button onClick={() => void signOut()}>Sign out</button>
      </div>
    </div>
  );
}

export function Loading({ text = "Loading…" }: { text?: string }) {
  return <div className="gate"><div className="gate-card" role="status">{text}</div></div>;
}

export function Unavailable({ message }: { message: string }) {
  return (
    <div className="gate"><div className="gate-card">
      <h1>Agent Hub is unavailable</h1><p>{message}</p>
      <button onClick={() => window.location.reload()}>Try again</button>
    </div></div>
  );
}

const initials = (n: string) => n.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]!.toUpperCase()).join("") || "?";

export function UserMenu() {
  const { me, signOut, expiringSoon, stayAlive, recheck } = useAuth();
  const [open, setOpen] = useState(false);
  const [rechecking, setRechecking] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const off = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", off); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", off); document.removeEventListener("keydown", esc); };
  }, [open]);
  if (!me) return null;
  return (
    <div className="usermenu" ref={box}>
      {expiringSoon && (
        <div className="banner-warn expiry" role="alert">
          Your session is about to expire. <button onClick={() => void stayAlive()}>Stay signed in</button>
        </div>
      )}
      <button className="avatar" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)} aria-label={`Account menu for ${me.name}`}>
        {initials(me.name)}
      </button>
      {open && (
        <div className="menu" role="menu">
          <div className="who">
            <strong>{me.name}</strong><span className="meta">{me.email}</span>
            <span className="chip">{me.role}</span>
            {me.mode === "azcli" && <span className="meta">Signed in through the Azure CLI{me.tenant ? ` · tenant ${me.tenant.slice(0, 8)}…` : ""}</span>}
          </div>
          {me.mode === "entra" && <button role="menuitem" onClick={() => void signOut()}>Sign out</button>}
          {me.mode === "azcli" && (
            <>
              <button role="menuitem" disabled={rechecking} onClick={async () => { setRechecking(true); try { await recheck(); } finally { setRechecking(false); setOpen(false); } }}>
                {rechecking ? "Checking…" : "Switch account (after az login)"}
              </button>
              <span className="meta pad">To sign out, run <code>az logout</code> in a terminal.</span>
            </>
          )}
          {me.mode === "off" && <span className="meta pad">Local mode: sign-in is switched off.</span>}
        </div>
      )}
    </div>
  );
}
