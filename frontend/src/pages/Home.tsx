import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { PAGES, type PageKey } from "../pageMeta";
import type { Portfolio } from "../types";

const ICON: Record<PageKey, string> = {
  marketplace: "M3 9l1.5-5h15L21 9M3 9h18M3 9v11h18V9M9 20v-6h6v6",
  factory: "M12 3l1.8 4.6L18.5 9l-4.7 1.4L12 15l-1.8-4.6L5.5 9l4.7-1.4zM18 15l.9 2.1L21 18l-2.1.9L18 21l-.9-2.1L15 18l2.1-.9z",
  guardrails: "M12 3l8 3v6c0 4.5-3.2 8-8 9-4.8-1-8-4.5-8-9V6zM9 12l2.2 2.2L15.5 10",
  evals: "M9 11l3 3 8-8M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h9",
  playground: "M8 5v14l11-7z",
};
const FOOT: Record<PageKey, string> = {
  marketplace: "Browse the catalog", factory: "Create an agent", guardrails: "Manage guardrails",
  evals: "See evaluation results", playground: "Open the playground",
};

export default function Home() {
  const [p, setP] = useState<Portfolio | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.portfolio().then(setP).catch((e: Error) => setError(e.message)); }, []);

  const k = p?.kpis, g = p?.governance;
  const stat = (v: number | undefined, label: string) => <div className="stat" key={label}><b>{v ?? "…"}</b><span>{label}</span></div>;
  const maxModel = Math.max(1, ...(p?.byModel ?? []).map(([, n]) => n));

  return (
    <main>
      <section className="banner">
        <h2>AI agent portfolio</h2>
        <p>Everything built on your Azure AI Foundry projects, and how well it is governed.</p>
        <div className="stats">
          {stat(k?.agents, "Agents")}{stat(k?.projects, "Projects")}{stat(k?.models, "Model deployments")}
          {stat(k?.mcp, "MCP servers")}{stat(k?.knowledge, "Knowledge bases")}{stat(k?.guardrails, "Guardrails")}
        </div>
      </section>

      {error && <div className="err">{error}</div>}

      {p && g && (
        <>
          <div className="row3">
          <section className="card panel" aria-labelledby="gov-h">
            <h3 id="gov-h">Guardrail coverage</h3>
            {g.coveragePct === null ? <p>No managed agents yet.</p> : (
              <>
                <div className="bignum">{g.coveragePct}<small>%</small></div>
                <div className="bar-track" role="progressbar" aria-valuenow={g.coveragePct} aria-valuemin={0} aria-valuemax={100} aria-label="Agents with a dedicated guardrail">
                  <div className="bar-fill" style={{ width: `${g.coveragePct}%` }} />
                </div>
                <p className="meta">{g.withGuardrail} of {g.managedAgents} managed agents have a dedicated guardrail.
                  {g.classicAgents > 0 && ` ${g.classicAgents} classic assistant${g.classicAgents > 1 ? "s are" : " is"} not counted.`}</p>
              </>
            )}
          </section>

          <section className="card panel" aria-labelledby="eval-h">
            <h3 id="eval-h">Evaluation health</h3>
            {g.managedAgents === 0 ? <p className="meta">No managed agents yet.</p> : (
              <>
                <div className="evalbar" role="img" aria-label={`${g.evalsPassing} passing, ${g.evalsFailing} failing, ${g.managedAgents - g.evaluated} not evaluated`}>
                  <span className="seg pass" style={{ flex: g.evalsPassing }} />
                  <span className="seg fail" style={{ flex: g.evalsFailing }} />
                  <span className="seg none" style={{ flex: g.managedAgents - g.evaluated }} />
                </div>
                <ul className="legend">
                  <li><span className="sw pass" /> <b>{g.evalsPassing}</b> passing</li>
                  <li><span className="sw fail" /> <b>{g.evalsFailing}</b> failing</li>
                  <li><span className="sw none" /> <b>{g.managedAgents - g.evaluated}</b> not evaluated</li>
                </ul>
                <Link to="/evals" className="meta">Open evaluations &rarr;</Link>
              </>
            )}
          </section>

          <section className="card panel" aria-labelledby="mod-h">
            <h3 id="mod-h">Models in use by agents</h3>
            {p.byModel.length === 0 ? <p className="meta">No agents yet.</p> : (
              <ul className="bars">
                {p.byModel.map(([name, n]) => (
                  <li key={name}><span className="lbl">{name}</span>
                    <span className="bar-track thin"><span className="bar-fill" style={{ width: `${(100 * n) / maxModel}%` }} /></span>
                    <span className="num">{n}</span></li>
                ))}
              </ul>
            )}
          </section>

          <section className="card panel" aria-labelledby="rail-h">
            <h3 id="rail-h">Guardrails in use</h3>
            {p.byGuardrail.length === 0 ? <p className="meta">No agent uses a dedicated guardrail yet.</p> : (
              <ul className="bars">
                {p.byGuardrail.map(([name, n]) => (
                  <li key={name}><span className="lbl">{name}</span>
                    <span className="bar-track thin"><span className="bar-fill" style={{ width: `${(100 * n) / Math.max(1, ...p.byGuardrail.map(([, c]) => c))}%` }} /></span>
                    <span className="num">{n}</span></li>
                ))}
              </ul>
            )}
          </section>
          </div>

          <section className="card panel wide2" aria-labelledby="att-h">
            <h3 id="att-h">Needs attention</h3>
            {p.attention.length === 0 ? <p className="ok">Nothing needs attention right now.</p> : (
              <ul className="attention">
                {p.attention.map((a) => (
                  <li key={a.title} className={a.severity}>
                    <span className="dot" aria-hidden="true" />
                    <div>
                      <div>
                        {a.filter
                          ? <Link to={`/marketplace?filter=${a.filter}`}><b>{a.count}</b> {a.title}</Link>
                          : <span><b>{a.count}</b> {a.title}</span>}
                      </div>
                      <div className="meta">{a.examples.map((e) => e.name).join(", ")}{a.count > a.examples.length ? ", …" : ""}</div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            {!p.corpDomainsSet && <p className="meta">Set <code>CORP_DOMAINS</code> to also flag MCP servers outside your company.</p>}
          </section>
        </>
      )}

      <h2 className="section">Explore</h2>
      <div className="row5">
      {(Object.keys(PAGES) as PageKey[]).map((key) => (
        <Link key={key} className="card hero" to={`/${key}`}>
          <span className="ico">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d={ICON[key]} /></svg>
          </span>
          <h3>{PAGES[key][0]}</h3>
          <p>{PAGES[key][1]}</p>
          <span className="go">{FOOT[key]} &rarr;</span>
        </Link>
      ))}
      </div>
    </main>
  );
}
