import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { useUi } from "../ui";
import { GuardrailCard } from "../components/Cards";
import { PageHeader } from "../pageMeta";
import type { AccountInfo, Guardrail } from "../types";

const CATS = ["Hate", "Sexual", "Violence", "Selfharm"] as const;

export default function Guardrails() {
  const { can } = useAuth();
  const { toast } = useUi();
  const [guardrails, setGuardrails] = useState<Guardrail[]>([]);
  const [accounts, setAccounts] = useState<AccountInfo[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [account, setAccount] = useState("");
  const [name, setName] = useState("");
  const [levels, setLevels] = useState<Record<string, string>>(Object.fromEntries(CATS.map((c) => [c, "Medium"])));
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setState("loading");
    Promise.all([api.list("guardrails"), api.accounts()])
      .then(([g, a]) => { setGuardrails(g); setAccounts(a); setAccount((cur) => cur || a[0]?.name || ""); setState("ready"); })
      .catch((e: Error) => { setError(e.message); setState("error"); });
  }, []);
  useEffect(load, [load]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setMsg(null);
    try {
      const d = await api.createGuardrail({ account, name: name.trim(), thresholds: levels });
      setMsg({ ok: true, text: `Created "${d.name}".` });
      toast("ok", `Created guardrail "${d.name}".`);
      window.setTimeout(load, 800);
    } catch (err) { setMsg({ ok: false, text: (err as Error).message }); toast("bad", (err as Error).message); }
    finally { setBusy(false); }
  }

  return (
    <>
      <PageHeader page="guardrails" />
      <main>
        {state === "loading" && <div className="empty">Loading…</div>}
        {state === "error" && <div className="err">{error}</div>}
        {state === "ready" && (
          <>
            {!can("Approver") && (
              <div className="card form"><h3>Custom guardrails</h3>
                <p>Creating a custom guardrail needs the <b>Approver</b> role. Builders get recommended guardrails automatically when they create an agent.</p></div>
            )}
            {can("Approver") && <form className="card form" onSubmit={submit}>
              <h3>Create a guardrail (content filter)</h3>
              <div className="formgrid">
                <label>Account
                  <select value={account} onChange={(e) => setAccount(e.target.value)}>{accounts.map((a) => <option key={a.name}>{a.name}</option>)}</select>
                </label>
                <label>Name
                  <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={64} pattern="[A-Za-z0-9][A-Za-z0-9_.\-]*" placeholder="strict-internal" />
                </label>
                {CATS.map((c) => (
                  <label key={c}>{c}
                    <select value={levels[c]} onChange={(e) => setLevels({ ...levels, [c]: e.target.value })}>
                      <option>Low</option><option>Medium</option><option>High</option>
                    </select>
                  </label>
                ))}
              </div>
              <div className="meta">Block content at this severity and above (applied to both prompts and completions). Low is strictest.</div>
              <div>
                <button className="primary" disabled={busy}>Create guardrail</button>{" "}
                {msg && <span className={msg.ok ? "ok" : "bad"}>{msg.text}</span>}
              </div>
              <div className="meta">Assigning it to a model deployment is done in the Foundry portal (Models + endpoints &rarr; deployment &rarr; Content filter).</div>
            </form>}
            {guardrails.length ? guardrails.map((g) => <GuardrailCard key={g.id} g={g} />) : <div className="empty">No guardrails found.</div>}
          </>
        )}
      </main>
    </>
  );
}
