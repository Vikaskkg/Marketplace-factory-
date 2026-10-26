import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, type AgentId } from "../api";
import { useAuth } from "../auth";
import { ago } from "../format";
import { PageHeader } from "../pageMeta";
import { useUi } from "../ui";
import type { Agent, EvalCase, EvalCategory, EvalRun } from "../types";

const idOf = (a: Agent): AgentId => ({ account: a.account ?? "", project: a.project ?? "", name: a.name });
const keyOf = (a: Agent) => `${a.account}/${a.project}/${a.name}`;
const CATS: EvalCategory[] = ["quality", "safety", "grounding"];

export function GateBadge({ gate }: { gate: "pass" | "fail" }) {
  return <span className={`chip ${gate === "pass" ? "good" : "bad"}`}>{gate === "pass" ? "Ready to release" : "Not ready"}</span>;
}

/** Pass rate per run over time, with the release threshold as a dashed line. */
export function Trend({ runs, threshold }: { runs: EvalRun[]; threshold: number }) {
  const pts = runs.filter((r) => r.summary).slice(0, 12).reverse();
  if (pts.length < 2) return <p className="meta">The trend appears after two or more runs.</p>;
  const w = 360, h = 90, pad = 8;
  const x = (i: number) => pad + (i * (w - 2 * pad)) / (pts.length - 1);
  const y = (v: number) => h - pad - (v / 100) * (h - 2 * pad);
  const d = pts.map((r, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(r.summary!.passRate).toFixed(1)}`).join(" ");
  return (
    <svg className="trend" viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`Pass rate over the last ${pts.length} runs: ${pts.map((r) => r.summary!.passRate + "%").join(", ")}`}>
      <line x1={pad} x2={w - pad} y1={y(threshold)} y2={y(threshold)} className="thr" />
      <text x={w - pad} y={y(threshold) - 3} textAnchor="end" className="thrlbl">release threshold {threshold}%</text>
      <path d={d} className="line" fill="none" />
      {pts.map((r, i) => <circle key={r.id} cx={x(i)} cy={y(r.summary!.passRate)} r="3.5" className={r.summary!.gate === "pass" ? "dot-pass" : "dot-fail"} />)}
    </svg>
  );
}

function Tiles({ run }: { run: EvalRun }) {
  const s = run.summary;
  if (!s) return null;
  return (
    <div className="tiles">
      <div className="tile"><b>{s.passRate}%</b><span>Pass rate ({s.passed} of {s.total})</span></div>
      {CATS.map((c) => s.byCategory[c] && <div className="tile" key={c}><b>{s.byCategory[c]!.pct}%</b><span className="cap">{c} ({s.byCategory[c]!.passed}/{s.byCategory[c]!.total})</span></div>)}
      <div className="tile"><b>{s.avgScore ?? "n/a"}</b><span>Avg judge score (1–5)</span></div>
      <div className="tile"><b>{(s.avgMs / 1000).toFixed(1)}s</b><span>Avg response time</span></div>
    </div>
  );
}

function Results({ run }: { run: EvalRun }) {
  const [open, setOpen] = useState<string | null>(null);
  const s = run.summary;
  if (!s || !run.results) return null;
  return (
    <>
      <Tiles run={run} />
      {!s.safetyAllPassed && <div className="banner-warn" role="alert">At least one safety check failed, so this agent is not ready to release whatever its overall score.</div>}
      {s.judged === 0 && <div className="meta">No judge model was available, so quality answers were checked only for being present, not rated.</div>}
      {s.errors > 0 && (
        <div className="banner-warn" role="alert">
          <b>{s.errors} of {s.total} checks could not run because the agent itself failed.</b>
          {[...new Set(run.results.filter((r) => r.error).flatMap((r) => r.reasons))].map((m) => <div key={m}>{m}</div>)}
        </div>
      )}
      <table className="restable">
        <thead><tr><th>Result</th><th>Type</th><th>Check</th><th>Score</th><th>Why</th></tr></thead>
        <tbody>
          {run.results.map((r) => (
            <Fragment key={r.id}>
              <tr className={r.passed ? "" : "failrow"}>
                <td><span className={`chip ${r.passed ? "good" : "bad"}`}>{r.passed ? "Pass" : "Fail"}</span></td>
                <td className="cap">{r.category}</td>
                <td>
                  <button className="linkbtn" aria-expanded={open === r.id} onClick={() => setOpen(open === r.id ? null : r.id)}>{r.title || r.prompt}</button>
                </td>
                <td>{r.score ?? "–"}</td>
                <td className="meta">{r.reasons.join(" ")}{r.blocked ? " (blocked by content filter)" : ""}</td>
              </tr>
              {open === r.id && (
                <tr className="detailrow"><td colSpan={5}>
                  <div className="qa"><b>Prompt</b><p>{r.prompt}</p><b>Agent's answer</b><p>{r.response || "(no answer)"}</p></div>
                </td></tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </>
  );
}

function CaseEditor({ agent, canEdit }: { agent: Agent; canEdit: boolean }) {
  const { toast } = useUi();
  const [cases, setCases] = useState<EvalCase[] | null>(null);
  const [isDefault, setIsDefault] = useState(false);
  const [threshold, setThreshold] = useState(80);
  const [busy, setBusy] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    setCases(null);
    api.evalSuite(idOf(agent)).then((s) => { setCases(s.cases); setIsDefault(s.isDefault); setThreshold(s.threshold); }).catch((e: Error) => setError(e.message));
  }, [agent]);
  if (error) return <div className="err">{error}</div>;
  if (!cases) return <p className="meta">Loading the test set…</p>;
  const patch = (i: number, p: Partial<EvalCase>) => setCases(cases.map((c, j) => (j === i ? { ...c, ...p } : c)));
  async function save() {
    setBusy(true);
    try { const r = await api.saveEvalSuite(idOf(agent), cases!); setCases(r.cases); setIsDefault(false); toast("ok", "Test set saved."); }
    catch (e) { toast("bad", (e as Error).message); }
    finally { setBusy(false); }
  }
  async function suggest() {
    setSuggesting(true);
    try {
      const r = await api.suggestEval(idOf(agent));
      if (r.cases.length === 0) { toast("ok", "Nothing to add: this test set already covers what we would suggest."); return; }
      setCases([...cases!, ...r.cases].slice(0, 25));
      toast("ok", `Added ${r.cases.length} suggested check${r.cases.length > 1 ? "s" : ""}. Review them, then save.`);
    } catch (e) { toast("bad", (e as Error).message); }
    finally { setSuggesting(false); }
  }
  return (
    <div className="editor">
      <p className="meta">
        {isDefault ? "This is the starter set. It is saved when you save it or run an evaluation. " : ""}
        Safety checks pass only if the agent refuses or deflects. An agent is ready to release at {threshold}% overall <b>and</b> every safety check passed.
      </p>
      {cases.map((c, i) => (
        <fieldset key={c.id} className="casebox" disabled={!canEdit}>
          <legend className="cap">{c.category}</legend>
          {c.why && <div className="meta why">Why this check: {c.why}</div>}
          <div className="formgrid">
            <label>Type
              <select value={c.category} onChange={(e) => patch(i, { category: e.target.value as EvalCategory, expect: { ...c.expect, refuse: e.target.value === "safety" ? true : c.expect.refuse } })}>
                {CATS.map((k) => <option key={k}>{k}</option>)}
              </select>
            </label>
            <label className="full">Prompt sent to the agent
              <textarea value={c.prompt} onChange={(e) => patch(i, { prompt: e.target.value })} maxLength={1000} style={{ minHeight: 56 }} />
            </label>
            <label className="full">What a good answer does (the judge uses this)
              <input value={c.criteria} onChange={(e) => patch(i, { criteria: e.target.value })} maxLength={300} />
            </label>
            <label className="check"><input type="checkbox" checked={!!c.expect.refuse} onChange={(e) => patch(i, { expect: { ...c.expect, refuse: e.target.checked } })} /> Agent should refuse</label>
            <button type="button" className="del" onClick={() => setCases(cases.filter((_, j) => j !== i))}>Remove</button>
          </div>
        </fieldset>
      ))}
      {canEdit && (
        <div className="acts">
          <button type="button" onClick={() => setCases([...cases, { id: Math.random().toString(16).slice(2, 10), category: "quality", title: "", prompt: "", criteria: "", expect: {} }])} disabled={cases.length >= 25}>Add a check</button>
          <button type="button" onClick={() => void suggest()} disabled={suggesting || cases.length >= 25}
            title="Adds checks this agent's description, tools and data suggest it needs">{suggesting ? "Looking…" : "Suggest more checks"}</button>
          <button type="button" className="primary" onClick={() => void save()} disabled={busy || cases.length === 0 || cases.some((c) => !c.prompt.trim())}>{busy ? "Saving…" : "Save test set"}</button>
        </div>
      )}
    </div>
  );
}

/** Shown for an agent that has never been evaluated: previews the checks we would create for it, and offers to create and run them. */
function SetupPanel({ agent, onStarted, onReview }: { agent: Agent; onStarted: (r: EvalRun) => void; onReview: () => void }) {
  const { can } = useAuth();
  const { toast } = useUi();
  const [cases, setCases] = useState<EvalCase[] | null>(null);
  const [busy, setBusy] = useState<"run" | "save" | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    setCases(null);
    api.evalSuite(idOf(agent)).then((s) => setCases(s.cases)).catch((e: Error) => setError(e.message));
  }, [agent]);

  async function create(run: boolean) {
    setBusy(run ? "run" : "save");
    try {
      const r = await api.createEval(idOf(agent), run);
      if (r.run) onStarted(r.run);
      else { toast("ok", `Created a test set with ${r.cases.length} checks.`); onReview(); }
    } catch (e) { toast("bad", (e as Error).message); }
    finally { setBusy(null); }
  }

  const count = (cat: EvalCategory) => cases?.filter((c) => c.category === cat).length ?? 0;
  return (
    <div className="setup" aria-label="Create an evaluation">
      <h4>Create an evaluation for {agent.name}</h4>
      <p>This agent has not been tested yet. We will build a test set from what it does, run it, and show whether it is ready to release.</p>
      {error && <div className="err">{error}</div>}
      {!cases && !error && <p className="meta">Preparing checks…</p>}
      {cases && (
        <>
          <p className="meta">{cases.length} checks: {count("safety")} safety, {count("quality")} quality{count("grounding") ? `, ${count("grounding")} grounding` : ""}.</p>
          <ul className="why-list">
            {cases.map((c) => <li key={c.id}><span className={`chip ${c.category === "safety" ? "warn" : "muted"}`}>{c.category}</span> <b>{c.title}</b>{c.why ? <span className="meta"> · {c.why}</span> : null}</li>)}
          </ul>
        </>
      )}
      {can("Builder") ? (
        <div className="acts">
          <button className="primary" disabled={!cases || !!busy} onClick={() => void create(true)}>{busy === "run" ? "Starting…" : "Create and run evaluation"}</button>
          <button disabled={!cases || !!busy} onClick={() => void create(false)}>{busy === "save" ? "Saving…" : "Create without running"}</button>
          <button disabled={!cases} onClick={onReview}>Review and edit first</button>
        </div>
      ) : <p className="meta">Creating an evaluation needs the Builder role.</p>}
    </div>
  );
}

function AgentEval({ agent }: { agent: Agent }) {
  const { can } = useAuth();
  const { toast } = useUi();
  const [runs, setRuns] = useState<EvalRun[] | null>(null);
  const [shown, setShown] = useState<EvalRun | null>(null);
  const [live, setLive] = useState<EvalRun | null>(null);
  const [tab, setTab] = useState<"results" | "history" | "tests">("results");
  const [error, setError] = useState("");
  const timer = useRef<number | undefined>(undefined);
  const id = idOf(agent);

  const load = useCallback(async () => {
    try {
      const rs = await api.evalRuns(id);
      setRuns(rs);
      const done = rs.find((r) => r.status === "done");
      setShown(done ? await api.evalRun(done.id) : null);
      const running = rs.find((r) => r.status === "running");
      if (running) { setLive(running); poll(running.id); }
    } catch (e) { setError((e as Error).message); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agent.account, agent.project, agent.name]);

  function poll(runId: string) {
    window.clearInterval(timer.current);
    timer.current = window.setInterval(async () => {
      try {
        const r = await api.evalRun(runId);
        if (r.status === "running") { setLive(r); return; }
        window.clearInterval(timer.current);
        setLive(null);
        toast(r.status === "done" && r.summary?.gate === "pass" ? "ok" : "bad",
          r.status === "failed" ? `Evaluation failed: ${r.error ?? "unknown error"}` : `Evaluation finished: ${r.summary?.passRate}% (${r.summary?.gate === "pass" ? "ready to release" : "not ready"}).`);
        await load();
        setTab("results");
      } catch { window.clearInterval(timer.current); setLive(null); }
    }, 1500);
  }

  useEffect(() => { setRuns(null); setShown(null); setLive(null); setError(""); setTab("results"); void load(); return () => window.clearInterval(timer.current); }, [load]);

  async function start() {
    try { const r = await api.runEval(id); setLive(r); poll(r.id); }
    catch (e) { toast("bad", (e as Error).message); }
  }
  async function view(runId: string) { setShown(await api.evalRun(runId)); setTab("results"); }

  const threshold = shown?.threshold ?? runs?.[0]?.threshold ?? 80;
  return (
    <section className="card evalpanel" aria-label={`Evaluation of ${agent.name}`}>
      <div className="evalhead">
        <div>
          <h3>{agent.name}</h3>
          <div className="meta">{agent.account} / {agent.project} · {agent.model}</div>
        </div>
        <div className="evalactions">
          {shown?.summary && <GateBadge gate={shown.summary.gate} />}
          <button className="primary" onClick={() => void start()} disabled={!!live || !can("Builder")} title={can("Builder") ? "" : "Requires the Builder role"}>
            {live ? "Running…" : "Run evaluation"}
          </button>
        </div>
      </div>

      {live && (
        <div className="progress" role="status">
          <div className="bar-track"><div className="bar-fill" style={{ width: `${(100 * live.progress.done) / Math.max(1, live.progress.total)}%` }} /></div>
          <span className="meta">Checking {live.progress.done} of {live.progress.total}… each check asks the agent a question and grades the answer.</span>
        </div>
      )}
      {error && <div className="err">{error}</div>}

      <div className="tabs" role="tablist">
        {([["results", "Results"], ["history", "History"], ["tests", "Test set"]] as const).map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>

      {tab === "results" && (shown
        ? <><div className="meta">Run {ago(shown.finishedAt)} by {shown.actor}</div><Results run={shown} /></>
        : runs && !live && (runs.length === 0
          ? <SetupPanel agent={agent} onStarted={(r) => { setLive(r); poll(r.id); }} onReview={() => setTab("tests")} />
          : <p className="empty">No finished evaluation yet. The latest run did not complete; press <b>Run evaluation</b> to try again.</p>))}
      {tab === "history" && runs && (
        <>
          <Trend runs={runs} threshold={threshold} />
          <table className="restable">
            <thead><tr><th>When</th><th>Pass rate</th><th>Outcome</th><th>By</th><th /></tr></thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id}>
                  <td>{ago(r.startedAt)}</td>
                  <td>{r.summary ? `${r.summary.passRate}% (${r.summary.passed}/${r.summary.total})` : r.status}</td>
                  <td>{r.summary ? <GateBadge gate={r.summary.gate} /> : <span className="meta">{r.status}</span>}</td>
                  <td className="meta">{r.actor}</td>
                  <td>{r.status === "done" && <button className="linkbtn" onClick={() => void view(r.id)}>View</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {tab === "tests" && <CaseEditor agent={agent} canEdit={can("Builder")} />}
    </section>
  );
}

export default function Evaluations() {
  const [params, setParams] = useSearchParams();
  const { can } = useAuth();
  const { toast, confirm } = useUi();
  const [agents, setAgents] = useState<Agent[] | null>(null);
  const [error, setError] = useState("");
  const [nonce, setNonce] = useState(0);
  const [bulk, setBulk] = useState(false);
  useEffect(() => {
    api.list("agents")
      .then((a) => setAgents(a.filter((x) => x.generation === "new")))
      .catch((e: Error) => setError(e.message));
  }, [nonce]);
  const sel = agents?.find((a) => keyOf(a) === params.get("agent")) ?? agents?.[0];
  const missing = agents?.filter((a) => !a.eval) ?? [];

  /** Creates and runs the first evaluation for every agent that has none. */
  async function setUpAll() {
    const todo = missing.slice(0, 10);
    const ok = await confirm({
      title: `Evaluate ${todo.length} agent${todo.length > 1 ? "s" : ""}?`,
      body: `This creates a test set for each and runs it now. Every check asks the agent a question, so it uses model capacity. ${missing.length > todo.length ? `Only the first ${todo.length} are started.` : ""}`,
      confirmLabel: "Create and run",
    });
    if (!ok) return;
    setBulk(true);
    let started = 0;
    const problems: string[] = [];
    for (const a of todo) {
      try { await api.createEval(idOf(a), true); started++; } catch (e) { problems.push(`${a.name}: ${(e as Error).message}`); }
    }
    setBulk(false);
    toast(problems.length ? "bad" : "ok", `Started ${started} evaluation${started === 1 ? "" : "s"}.${problems.length ? ` ${problems[0]}` : " Results appear as each one finishes."}`);
    setNonce((n) => n + 1);
  }

  return (
    <>
      <PageHeader page="evals" />
      <main className="evalpage">
        {error && <div className="err">{error}</div>}
        {!agents && !error && <div className="empty">Loading…</div>}
        {agents && agents.length === 0 && <div className="empty">No managed agents to evaluate yet.</div>}
        {agents && agents.length > 0 && sel && (
          <>
            <nav className="agentlist" aria-label="Agents">
              {can("Builder") && missing.length > 0 && (
                <button className="setupall" disabled={bulk} onClick={() => void setUpAll()}>
                  {bulk ? "Starting…" : `Evaluate the ${missing.length} unevaluated`}
                </button>
              )}
              {agents.map((a) => (
                <button key={keyOf(a)} className={keyOf(a) === keyOf(sel) ? "on" : ""} aria-current={keyOf(a) === keyOf(sel)}
                  onClick={() => setParams({ agent: keyOf(a) }, { replace: true })}>
                  <span className="nm">{a.name}</span>
                  {a.eval ? <span className={`chip ${a.eval.gate === "pass" ? "good" : "bad"}`}>{a.eval.passRate}%</span> : <span className="chip muted">not set up</span>}
                </button>
              ))}
            </nav>
            <AgentEval agent={sel} />
          </>
        )}
      </main>
    </>
  );
}
