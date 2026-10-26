import { useEffect, useState, type FormEvent } from "react";
import { Link, useLocation } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { useUi } from "../ui";
import RiskPanel from "../components/RiskPanel";
import { PageHeader } from "../pageMeta";
import type { Agent, Assessment, DraftResponse, Facts, ProjectInfo } from "../types";

interface Form { name: string; description: string; instructions: string; model: string; guardrail: string; mcp: string[]; kb: string[] }
const EMPTY: Form = { name: "", description: "", instructions: "", model: "", guardrail: "", mcp: [], kb: [] };
const toggle = (xs: string[], x: string) => (xs.includes(x) ? xs.filter((y) => y !== x) : [...xs, x]);

export default function Factory() {
  const pre = (useLocation().state as { agent?: Agent } | null)?.agent;
  const { can, me } = useAuth();
  const { toast } = useUi();
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [pi, setPi] = useState(0);
  const [form, setForm] = useState<Form>(EMPTY);
  const [facts, setFacts] = useState<Facts>({});
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [override, setOverride] = useState("");
  const [query, setQuery] = useState("");
  const [drafting, setDrafting] = useState(false);
  const [draftInfo, setDraftInfo] = useState<DraftResponse | { error: string } | null>(null);
  const [guardBusy, setGuardBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string; created?: string } | null>(null);

  const set = (patch: Partial<Form>) => setForm((f) => ({ ...f, ...patch }));
  const project = projects[pi];

  useEffect(() => {
    api.projects()
      .then((ps) => {
        setProjects(ps);
        const i = pre ? Math.max(0, ps.findIndex((p) => p.name === pre.project && p.account === pre.account)) : 0;
        setPi(i);
        const p = ps[i];
        if (pre && p) {
          const mcp = pre.toolDefs.filter((t) => t.type === "mcp").map((t) => t.server_url ?? "");
          const kb = pre.toolDefs.filter((t) => t.type === "azure_ai_search").flatMap((t) => t.azure_ai_search?.indexes?.map((x) => x.index_name) ?? []);
          setForm({ name: pre.name, description: pre.description ?? "", instructions: pre.instructions ?? "", model: pre.model ?? p.models[0] ?? "",
                    guardrail: pre.guardrail ?? "", mcp, kb });
        } else if (p) setForm({ ...EMPTY, model: p.models[0] ?? "" });
        setState("ready");
      })
      .catch((e: Error) => { setError(e.message); setState("error"); });
  }, [pre]);

  // Re-run the risk rubric whenever something that affects it changes (it is a local calculation, so this is cheap).
  useEffect(() => {
    if (!project) return;
    let live = true;
    const t = window.setTimeout(() => {
      api.assess({ account: project.account, project: project.name, description: form.description, instructions: form.instructions,
                   mcp: form.mcp, knowledge: form.kb, guardrail: form.guardrail || null, facts })
        .then((a) => { if (live) setAssessment(a); })
        .catch(() => { if (live) setAssessment(null); });
    }, 400);
    return () => { live = false; window.clearTimeout(t); };
  }, [project, form.description, form.instructions, form.mcp, form.kb, form.guardrail, facts]);

  function changeProject(i: number) {
    setPi(i); setAssessment(null); setDraftInfo(null);
    setForm({ ...EMPTY, name: form.name, description: form.description, instructions: form.instructions, model: projects[i].models[0] ?? "" });
  }

  async function runDraft() {
    if (!project || query.trim().length < 3) { setDraftInfo({ error: "Describe the agent first." }); return; }
    setDrafting(true); setDraftInfo(null);
    try {
      const r = await api.draft(query.trim(), project.account, project.name);
      setDraftInfo(r);
      if (r.draft) {
        const d = r.draft;
        setForm({ name: d.name, description: d.description, instructions: d.instructions,
                  model: project.models.includes(d.model) ? d.model : project.models[0] ?? "", guardrail: d.guardrail ?? "", mcp: d.mcp, kb: d.knowledge });
        setFacts(r.facts ?? {});
        setOverride("");
      }
    } catch (e) { setDraftInfo({ error: (e as Error).message }); }
    finally { setDrafting(false); }
  }

  async function createRecommended() {
    if (!project || !assessment) return;
    const tier = assessment.guardrail.tier;
    if (tier !== "Medium" && tier !== "High" && tier !== "Critical") return;
    setGuardBusy(true); setMsg(null);
    try {
      const r = await api.createGuardrailFromTemplate({ account: project.account, tier });
      setProjects(await api.projects());
      set({ guardrail: r.name });
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
    finally { setGuardBusy(false); }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!project) return;
    setSaving(true); setMsg(null);
    try {
      const r = await api.createAgent({
        project: project.name, account: project.account, name: form.name.trim(), model: form.model, instructions: form.instructions,
        description: form.description, mcp: form.mcp, knowledge: form.kb, keep_tools: !!pre, guardrail: form.guardrail || null,
        facts, override_reason: override.trim() || null,
      });
      setMsg({ ok: true, created: r.name, text: `${r.version ? ` (version ${r.version})` : ""}${r.tier ? `, ${r.tier} risk` : ""}.` });
      toast("ok", `Created "${r.name}"${r.tier ? ` (${r.tier} risk)` : ""}.`);
    } catch (err) { setMsg({ ok: false, text: (err as Error).message }); toast("bad", (err as Error).message); }
    finally { setSaving(false); }
  }

  const info = draftInfo && "error" in draftInfo ? draftInfo : null;
  const draft = draftInfo && !("error" in draftInfo) ? draftInfo : null;

  return (
    <>
      <PageHeader page="factory" />
      <main>
        {state === "loading" && <div className="empty">Loading…</div>}
        {state === "error" && <div className="err">{error}</div>}
        {state === "ready" && !can("Builder") && (
          <div className="card form">
            <h3>You can look, but not build</h3>
            <p>Your role is <b>{me?.role}</b>. Creating or editing agents needs the <b>Builder</b> role. Ask your administrator if you need it.</p>
          </div>
        )}
        {state === "ready" && can("Builder") && !project && <div className="empty">No Foundry projects found to create an agent in.</div>}
        {state === "ready" && can("Builder") && project && (
          <form className="card form" onSubmit={submit}>
            <h3>{pre ? "Edit agent (saves a new version)" : "Create a prompt agent"}</h3>

            {!pre && (
              <div className="draft">
                <label>Describe the agent you want, in plain English
                  <textarea value={query} onChange={(e) => setQuery(e.target.value)} maxLength={500}
                    placeholder="e.g. An agent that answers employee questions about engineering docs and can look at GitHub issues" />
                </label>
                <div>
                  <button type="button" className="primary" onClick={() => void runDraft()} disabled={drafting}>{drafting ? "Drafting…" : "Draft with AI"}</button>{" "}
                  <span className="meta">Fills the form below for you to review. Nothing is created until you press Create.</span>
                </div>
                <div id="dnote">
                  {info && <span className="warn">{info.error}</span>}
                  {draft && !draft.draft && <span className="warn">{draft.note || "No draft produced."}</span>}
                  {draft?.draft && (
                    <>
                      <b>{draft.mode === "ai" ? "AI draft" : "Basic draft"} ready.</b> Review every field before creating.
                      {draft.note && <div className="warn">{draft.note}</div>}
                      {draft.reasons && Object.keys(draft.reasons).length > 0 && (
                        <ul>{Object.entries(draft.reasons).map(([k, v]) => <li key={k}><b>{k}</b>: {v}</li>)}</ul>
                      )}
                      {draft.missing && draft.missing.length > 0 && <div className="warn">Not available in this project: {draft.missing.join("; ")}</div>}
                    </>
                  )}
                </div>
              </div>
            )}

            <div className="split">
            <div className="col">
            <div className="formgrid">
              <label>Project
                <select value={pi} disabled={!!pre} onChange={(e) => changeProject(Number(e.target.value))}>
                  {projects.map((p, i) => <option key={`${p.account}/${p.name}`} value={i}>{p.account} / {p.name}</option>)}
                </select>
              </label>
              <label>Name (letters, digits, hyphens)
                <input value={form.name} readOnly={!!pre} onChange={(e) => set({ name: e.target.value })} required maxLength={63} pattern="[A-Za-z0-9][A-Za-z0-9\-]*" placeholder="my-first-agent" />
              </label>
              <label>Model deployment
                <select value={form.model} onChange={(e) => set({ model: e.target.value })} required>
                  {project.models.length ? project.models.map((m) => <option key={m}>{m}</option>) : <option value="">No deployments in this account</option>}
                </select>
              </label>
              <label>Guardrail (content filter)
                <select value={form.guardrail} onChange={(e) => set({ guardrail: e.target.value })}>
                  <option value="">None (model default)</option>
                  {project.guardrails.map((g) => <option key={g}>{g}</option>)}
                </select>
              </label>
            </div>
            <label>Description (optional)
              <input value={form.description} onChange={(e) => set({ description: e.target.value })} maxLength={500} />
            </label>
            <label>Instructions
              <textarea value={form.instructions} onChange={(e) => set({ instructions: e.target.value })} required placeholder="You are a helpful assistant that…" />
            </label>
            <label>Knowledge bases (project indexes, via Azure AI Search)
              <div>
                {project.knowledge.length === 0 && <span className="meta">No indexes found in this project</span>}
                {project.knowledge.map((k) => (
                  <div key={k.name}>
                    <input type="checkbox" checked={form.kb.includes(k.name)} onChange={() => set({ kb: toggle(form.kb, k.name) })} /> {k.name} <span className="meta">via {k.connection}</span>
                  </div>
                ))}
              </div>
            </label>
            <label>MCP servers (from this project)
              <div>
                {project.mcp.length === 0 && <span className="meta">None found</span>}
                {project.mcp.map((m) => (
                  <div key={m.target}>
                    <input type="checkbox" checked={form.mcp.includes(m.target)} onChange={() => set({ mcp: toggle(form.mcp, m.target) })} /> {m.name} <span className="meta">{m.target}</span>
                  </div>
                ))}
              </div>
            </label>
            </div>

            <div className="col sticky">
              {assessment ? (
                <RiskPanel assessment={assessment} facts={facts} selectedGuardrail={form.guardrail} busy={guardBusy} overrideReason={override}
                  onFact={(k, v) => setFacts((f) => { const n = { ...f }; if (v) n[k] = v; else delete n[k]; return n; })}
                  onUseGuardrail={(n) => set({ guardrail: n })}
                  onCreateRecommended={() => void createRecommended()}
                  onAddSnippet={(s) => set({ instructions: form.instructions.includes(s) ? form.instructions : `${form.instructions.trim()}\n\n${s}` })}
                  onOverrideReason={setOverride} />
              ) : (
                <div className="placeholder">The risk profile and guardrail recommendation appear here and update as you fill in the form.</div>
              )}
            </div>
            </div>

            <div>
              <button className="primary" type="submit" disabled={saving || !!assessment?.blocked}>{saving ? "Saving…" : pre ? "Save new version" : "Create agent"}</button>{" "}
              {msg && (msg.ok
                ? <span className="ok">Created "{msg.created}"{msg.text} Next: <Link to={`/evals?agent=${encodeURIComponent(`${project.account}/${project.name}/${msg.created}`)}`}>create an evaluation for it</Link>,
                    or find it in the <Link to="/marketplace">Marketplace</Link> after a refresh.</span>
                : <span className="bad">{msg.text}</span>)}
            </div>
          </form>
        )}
      </main>
    </>
  );
}
