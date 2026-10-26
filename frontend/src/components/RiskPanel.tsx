import type { Assessment, Facts } from "../types";

interface Props {
  assessment: Assessment;
  facts: Facts;
  selectedGuardrail: string;
  busy: boolean;
  overrideReason: string;
  onFact: (key: string, value: string) => void;
  onUseGuardrail: (name: string) => void;
  onCreateRecommended: () => void;
  onAddSnippet: (snippet: string) => void;
  onOverrideReason: (v: string) => void;
}

/** Shows the risk tier with its evidence, the questions behind it, the guardrail recommendation and the controls. */
export default function RiskPanel(p: Props) {
  const a = p.assessment;
  const g = a.guardrail;
  const canCreate = g.suggestNew && (g.tier === "Medium" || g.tier === "High");
  return (
    <section className="risk" aria-label="Risk assessment">
      <h4>Risk profile</h4>
      <span className={`tier ${a.tier}`}>{a.tier} risk <small>score {a.score}</small></span>
      {a.floorNote && <div className="meta">{a.floorNote}</div>}
      {a.blocked && <div className="banner-warn">This is a Critical-risk agent. It needs review-board approval and cannot be created from here.</div>}

      <table>
        <thead><tr><th>Factor</th><th>Value</th><th>Why</th><th className="pts">Points</th></tr></thead>
        <tbody>
          {a.factors.map((f) => (
            <tr key={f.key}>
              <td>{f.label}</td>
              <td>{f.value} {f.assumed && <span className="assumed" title="Not stated; a cautious assumption is used">assumed</span>}</td>
              <td className="meta">{f.evidence}</td>
              <td className="pts">{f.points}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div>
        <strong>Tell us more (answers change the score)</strong>
        <div className="qgrid">
          {a.questions.map((q) => (
            <label key={q.key}>{q.text}
              <select value={typeof p.facts[q.key] === "string" ? (p.facts[q.key] as string) : ""} onChange={(e) => p.onFact(q.key, e.target.value)}>
                <option value="">Not sure (cautious default)</option>
                {Object.entries(q.options).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>
          ))}
        </div>
      </div>

      <div className={`rec ${g.selectedOk ? "" : "bad"}`}>
        <strong>Recommended guardrail ({a.tier})</strong>
        <div>
          {g.selectedOk
            ? `The selected guardrail${g.selected ? ` (${g.selected})` : " (model default)"} meets this recommendation.`
            : `The selected guardrail${g.selected ? ` (${g.selected})` : " (model default)"} is weaker than recommended.`}
          {g.extras.length > 0 && ` Also turns on: ${g.extras.join(", ")}.`}
        </div>
        {!g.selectedOk && (
          <div className="acts">
            {g.satisfying.slice(0, 3).map((n) => <button type="button" key={n} onClick={() => p.onUseGuardrail(n)}>Use {n}</button>)}
            {g.satisfying.length === 0 && canCreate && (
              <button type="button" className="primary" disabled={p.busy} onClick={p.onCreateRecommended}>
                {p.busy ? "Creating…" : `Create ${g.suggestNew} and use it`}
              </button>
            )}
          </div>
        )}
      </div>

      <div>
        <strong>Controls to apply</strong>
        <ul className="checklist">
          {a.controls.map((c) => (
            <li key={c.id}>
              {c.text}
              {c.snippet && <> <button type="button" onClick={() => p.onAddSnippet(c.snippet!)}>Add to instructions</button></>}
            </li>
          ))}
        </ul>
      </div>

      {!g.selectedOk && !a.blocked && (
        <label>Reason for keeping the weaker guardrail (recorded in the audit log)
          <textarea value={p.overrideReason} onChange={(e) => p.onOverrideReason(e.target.value)} maxLength={500} style={{ minHeight: 60 }} />
        </label>
      )}
    </section>
  );
}
