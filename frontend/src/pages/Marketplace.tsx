import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { useUi } from "../ui";
import { AgentCard, DeploymentCard, GuardrailCard, KnowledgeCard, McpCard } from "../components/Cards";
import ChatDialog from "../components/ChatDialog";
import { PageHeader } from "../pageMeta";
import { useSummary } from "../summary";
import type { Agent, AssetType, DiscoverResponse, Kind, KindMap } from "../types";

const TABS: [Kind, string][] = [["agents", "Agents"], ["deployments", "Models"], ["mcp", "MCP servers"], ["knowledge", "Knowledge bases"], ["guardrails", "Guardrails"]];
const TAB_OF: Record<AssetType, Kind> = { agent: "agents", model: "deployments", mcp: "mcp", knowledge: "knowledge", guardrail: "guardrails" };
const TYPE_LABEL: Record<AssetType, string> = { agent: "Agent", model: "Model", mcp: "MCP server", knowledge: "Knowledge base", guardrail: "Guardrail" };

const FILTER_LABEL: Record<string, string> = {
  "no-guardrail": "Agents without a dedicated guardrail", stale: "Agents not updated recently", "no-description": "Agents with no description",
  classic: "Classic assistants", "external-tools": "Agents using MCP servers outside your corporate domains",
  "no-eval": "Agents that have never been evaluated", "failing-eval": "Agents that failed their latest evaluation",
};

export default function Marketplace() {
  const { summary, reload } = useSummary();
  const { can } = useAuth();
  const { toast, confirm } = useUi();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const filter = params.get("filter") ?? "";          // set by the dashboard's attention list
  const showSystem = params.get("system") === "1";
  const setParam = (k: string, v: string | null) => setParams((p) => { const n = new URLSearchParams(p); if (v) n.set(k, v); else n.delete(k); return n; }, { replace: true });
  const [tab, setTab] = useState<Kind>("agents");
  const [q, setQ] = useState("");
  const [project, setProject] = useState("");
  const [items, setItems] = useState<KindMap[Kind][]>([]);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [nonce, setNonce] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [ask, setAsk] = useState("");
  const [asked, setAsked] = useState<{ query: string; res: DiscoverResponse } | null>(null);
  const [askBusy, setAskBusy] = useState(false);
  const [chat, setChat] = useState<Agent | null>(null);

  // Load the current tab, debounced while typing in the search box.
  useEffect(() => {
    let live = true;
    setState("loading");
    const t = window.setTimeout(() => {
      api.list(tab, q, project, tab === "agents" ? { filter, system: showSystem } : {})
        .then((r) => { if (live) { setItems(r); setState("ready"); } })
        .catch((e: Error) => { if (live) { setError(e.message); setState("error"); } });
    }, q ? 250 : 0);
    return () => { live = false; window.clearTimeout(t); };
  }, [tab, q, project, nonce, filter, showSystem]);

  const projects = useMemo(() => {
    const names = new Set(summary?.projects ?? []);
    items.forEach((i) => { if ("project" in i && i.project) names.add(i.project); });
    return [...names].sort();
  }, [summary, items]);

  async function refresh() {
    setRefreshing(true);
    try { await api.refresh(); await reload(); setNonce((n) => n + 1); }
    catch (err) { toast("bad", (err as Error).message); }
    finally { setRefreshing(false); }
  }

  async function submitAsk(e: FormEvent) {
    e.preventDefault();
    const query = ask.trim();
    setAskBusy(true);
    try { setAsked({ query, res: await api.discover(query) }); }
    catch (err) { setAsked({ query, res: { mode: "keyword", note: (err as Error).message, results: [] } }); }
    finally { setAskBusy(false); }
  }

  function openResult(type: AssetType, name: string) {
    setTab(TAB_OF[type]); setQ(name); setProject(""); setAsked(null);
  }

  async function remove(a: Agent) {
    const ok = await confirm({ title: `Delete "${a.name}"?`, body: "This removes the agent and all of its versions. It cannot be undone.", confirmLabel: "Delete agent", danger: true });
    if (!ok) return;
    try {
      await api.deleteAgent({ project: a.project ?? "", account: a.account ?? "", name: a.name });
      toast("ok", `Deleted "${a.name}".`);
      setNonce((n) => n + 1);
    } catch (err) { toast("bad", (err as Error).message); }
  }

  const card = (i: KindMap[Kind]) => {
    switch (tab) {
      case "agents": {
        const a = i as Agent;
        return <AgentCard key={a.id} a={a} canEdit={can("Builder")} canDelete={can("Approver")} onChat={() => setChat(a)}
                          onEvaluate={can("Builder") ? () => navigate(`/evals?agent=${encodeURIComponent(`${a.account}/${a.project}/${a.name}`)}`) : undefined}
                          onEdit={() => navigate("/factory", { state: { agent: a } })} onDelete={() => void remove(a)} />;
      }
      case "deployments": return <DeploymentCard key={i.id} d={i as KindMap["deployments"]} />;
      case "mcp": return <McpCard key={i.id} m={i as KindMap["mcp"]} />;
      case "knowledge": return <KnowledgeCard key={i.id} k={i as KindMap["knowledge"]} />;
      case "guardrails": return <GuardrailCard key={i.id} g={i as KindMap["guardrails"]} />;
    }
  };

  return (
    <>
      <PageHeader page="marketplace">
        <form className="ask" onSubmit={submitAsk}>
          <input value={ask} onChange={(e) => setAsk(e.target.value)} required minLength={3} maxLength={500} autoComplete="off" aria-label="Ask in plain English"
            placeholder="Ask in plain English, e.g. “an agent that reviews supplier contracts” or “which tools can read GitHub?”" />
          <button className="primary" disabled={askBusy}>Ask</button>
        </form>
        <div className="bar">
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name, model, project, tool..." aria-label="Search" />
          <select value={project} onChange={(e) => setProject(e.target.value)} aria-label="Project">
            <option value="">All projects</option>
            {projects.map((p) => <option key={p}>{p}</option>)}
          </select>
          {tab === "agents" && (
            <label className="check"><input type="checkbox" checked={showSystem} onChange={(e) => setParam("system", e.target.checked ? "1" : null)} /> Show system agents</label>
          )}
          <button className="primary" onClick={() => void refresh()} disabled={refreshing || !can("Builder")}
            title={can("Builder") ? "" : "Requires the Builder role"}>{refreshing ? "Scanning…" : "Refresh from Azure"}</button>
        </div>
        {filter && tab === "agents" && (
          <div className="filterchip">
            Showing: <b>{FILTER_LABEL[filter] ?? filter}</b>
            <button onClick={() => setParam("filter", null)} aria-label="Clear filter">✕</button>
          </div>
        )}
        <nav className="tabs" aria-label="Catalog sections">
          {TABS.map(([k, label]) => (
            <button key={k} className={k === tab ? "on" : ""} onClick={() => { setTab(k); setAsked(null); }}>
              {label}<span className="n">{summary?.counts[k] ?? "…"}</span>
            </button>
          ))}
        </nav>
      </PageHeader>

      <main>
        {asked ? (
          <>
            <div className="note">
              <span><b>{asked.res.mode === "ai" ? "AI-ranked" : "Keyword"} results</b> for “{asked.query}”</span>
              {asked.res.note && <span className="bad">{asked.res.note}</span>}
              <button type="button" onClick={() => setAsked(null)}>Back to catalog</button>
            </div>
            {asked.res.results.length === 0 && <div className="empty">Nothing matched. Try different words, or browse the tabs.</div>}
            {asked.res.results.map((r) => (
              <div className="card" key={`${r.type}/${r.account}/${r.project}/${r.name}`}>
                <span className="badge">{TYPE_LABEL[r.type]}</span>
                <h3>{r.name}</h3>
                <p className="why">{r.reason}</p>
                <div className="meta">{[r.account, r.project].filter(Boolean).join(" / ")}</div>
                <div className="acts"><button onClick={() => openResult(r.type, r.name)}>Open in catalog</button></div>
              </div>
            ))}
          </>
        ) : state === "loading" ? <div className="empty">Loading…</div>
          : state === "error" ? <div className="err">{error}</div>
          : items.length === 0 ? (
            <div className="empty">Nothing found.{summary?.errors?.length ? <><br /><small>Discovery errors:<br />{summary.errors.map((e, i) => <span key={i}>{e}<br /></span>)}</small></> : null}</div>
          ) : items.map(card)}
      </main>
      <ChatDialog agent={chat} onClose={() => setChat(null)} />
    </>
  );
}
