import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "../api";
import { PageHeader } from "../pageMeta";
import type { Agent, Deployment, Turn } from "../types";

interface Line { cls: string; text: string }

export default function Playground() {
  const [deps, setDeps] = useState<Deployment[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [target, setTarget] = useState("");
  const [system, setSystem] = useState("");
  const [temp, setTemp] = useState("0.7");
  const [lines, setLines] = useState<Line[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const history = useRef<Turn[]>([]);
  const prev = useRef<string | null>(null);
  const log = useRef<HTMLDivElement>(null);

  useEffect(() => {
    Promise.all([api.list("deployments"), api.list("agents")])
      .then(([d, a]) => {
        const chatModels = d.filter((x) => !/embed/i.test(x.name + (x.model ?? "")));
        const newAgents = a.filter((x) => x.generation === "new");
        setDeps(chatModels); setAgents(newAgents);
        setTarget(chatModels.length ? "m0" : newAgents.length ? "a0" : "");
        setState("ready");
      })
      .catch((e: Error) => { setError(e.message); setState("error"); });
  }, []);
  useEffect(() => { if (log.current) log.current.scrollTop = log.current.scrollHeight; }, [lines]);

  const isModel = target.startsWith("m");
  const reset = () => { history.current = []; prev.current = null; setLines([]); };

  async function send(e: FormEvent) {
    e.preventDefault();
    const message = text.trim();
    if (!message || !target) return;
    setText(""); setBusy(true);
    setLines((l) => [...l, { cls: "u", text: `You: ${message}` }]);
    try {
      if (isModel) {
        const d = deps[Number(target.slice(1))];
        history.current.push({ role: "user", content: message });
        const r = await api.chatModel({
          account: d.account ?? "", deployment: d.name, temperature: Number(temp) || 0,
          messages: [...(system.trim() ? [{ role: "system" as const, content: system.trim() }] : []), ...history.current],
        });
        history.current.push({ role: "assistant", content: r.text });
        setLines((l) => [...l, { cls: "", text: r.text + (r.finish && r.finish !== "stop" ? `\n[${r.finish}]` : "") }]);
      } else {
        const a = agents[Number(target.slice(1))];
        const r = await api.chatAgent({ project: a.project ?? "", account: a.account ?? "", name: a.name, message, previous: prev.current });
        prev.current = r.id ?? null;
        setLines((l) => [...l, { cls: "", text: r.text }]);
      }
    } catch (err) {
      if (isModel) history.current.pop();
      setLines((l) => [...l, { cls: "bad", text: (err as Error).message }]);
    } finally { setBusy(false); }
  }

  return (
    <>
      <PageHeader page="playground" />
      <main>
        {state === "loading" && <div className="empty">Loading…</div>}
        {state === "error" && <div className="err">{error}</div>}
        {state === "ready" && !target && <div className="empty">No chat models or agents found.</div>}
        {state === "ready" && target && (
          <div className="card form wide">
            <h3>Playground</h3>
            <label>Target
              <select value={target} onChange={(e) => { setTarget(e.target.value); reset(); }}>
                {deps.length > 0 && <optgroup label="Models">{deps.map((d, i) => <option key={d.id} value={`m${i}`}>{d.name} ({d.account})</option>)}</optgroup>}
                {agents.length > 0 && <optgroup label="Agents">{agents.map((a, i) => <option key={a.id} value={`a${i}`}>{a.name} ({a.project})</option>)}</optgroup>}
              </select>
            </label>
            {isModel && (
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <label style={{ flex: 1, minWidth: 240 }}>System prompt
                  <input value={system} onChange={(e) => setSystem(e.target.value)} placeholder="You are a helpful assistant." />
                </label>
                <label>Temperature
                  <input type="number" min={0} max={2} step={0.1} value={temp} onChange={(e) => setTemp(e.target.value)} style={{ width: 90 }} />
                </label>
              </div>
            )}
            <div id="clog" ref={log} style={{ height: 320 }}>{lines.map((l, i) => <p key={i} className={l.cls}>{l.text}</p>)}</div>
            <form onSubmit={send} style={{ display: "flex", gap: 6 }}>
              <input value={text} onChange={(e) => setText(e.target.value)} required maxLength={4000} placeholder="Type a message…" autoComplete="off" aria-label="Message" />
              <button className="primary" disabled={busy}>Send</button>
              <button type="button" onClick={reset}>Clear</button>
            </form>
          </div>
        )}
      </main>
    </>
  );
}
