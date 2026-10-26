import type { ReactNode } from "react";
import { ago } from "../format";
import type { Agent, Deployment, Guardrail, Knowledge, McpServer } from "../types";

const where = (i: { account?: string; project?: string | null }) => [i.account, i.project].filter(Boolean).join(" / ");
export const Chips = ({ items }: { items: (string | false | null | undefined)[] }) => {
  const xs = items.filter((x): x is string => Boolean(x));
  return xs.length ? <div className="chips">{xs.map((x) => <span className="chip" key={x}>{x}</span>)}</div> : null;
};
const PortalLink = ({ url }: { url?: string }) =>
  url && /^https:\/\//.test(url) ? <a href={url} target="_blank" rel="noopener noreferrer">Open in Foundry</a> : null;
const Card = ({ children }: { children: ReactNode }) => <div className="card">{children}</div>;

interface AgentCardProps {
  a: Agent; onChat: () => void; onEdit: () => void; onDelete: () => void;
  /** Roles shape the UI only; the server enforces them. */
  canEdit?: boolean; canDelete?: boolean;
  /** When given, an unevaluated agent offers a one-click way to set up its first evaluation. */
  onEvaluate?: () => void;
}

export function AgentCard({ a, onChat, onEdit, onDelete, onEvaluate, canEdit = true, canDelete = true }: AgentCardProps) {
  const managed = a.generation === "new";
  return (
    <Card>
      <h3>{a.name} {a.system && <span className="badge sys">System</span>}</h3>
      <p>{a.description || "No description"}</p>
      <div className="meta">{where(a)} · {a.model || "no model"} · {managed ? "managed" : "classic"} · updated {ago(a.created)}</div>
      <div className="chips">
        {(a.tools || []).map((t) => <span className="chip" key={t}>{t}</span>)}
        {a.guardrail && <span className="chip good">Guardrail: {a.guardrail}</span>}
        {managed && !a.guardrail && <span className="chip warn" title="Only the model's default content filter applies">No dedicated guardrail</span>}
        {managed && a.eval && (
          <span className={`chip ${a.eval.gate === "pass" ? "good" : "bad"}`}
            title={`${a.eval.passRate}% of checks passed in the latest evaluation (${ago(a.eval.at)}). Ready to release needs the pass-rate target and every safety check to pass.`}>
            {a.eval.passRate}% checks passed · {a.eval.gate === "pass" ? "ready" : "not ready"}
          </span>
        )}
        {managed && !a.eval && (onEvaluate
          ? <button className="chip muted linkchip" onClick={onEvaluate} title="Build a test set for this agent and run it">Create evaluation</button>
          : <span className="chip muted" title="No evaluation has been run">Not evaluated</span>)}
      </div>
      {a.mcpServers?.length > 0 && <div className="meta">MCP: {a.mcpServers.join(", ")}</div>}
      {a.knowledge?.length > 0 && <div className="meta">Knowledge: {a.knowledge.join(", ")}</div>}
      <PortalLink url={a.portalUrl} />
      {managed && (
        <div className="acts">
          <button onClick={onChat}>Chat</button>
          {canEdit && <button onClick={onEdit}>Edit</button>}
          {canDelete && <button className="del" onClick={onDelete}>Delete</button>}
        </div>
      )}
    </Card>
  );
}

export const DeploymentCard = ({ d }: { d: Deployment }) => (
  <Card>
    <h3>{d.name}</h3>
    <p>{d.publisher} {d.model} {d.version}</p>
    <div className="meta">{where(d)} · {d.location}</div>
    <Chips items={[d.sku, d.capacity != null && `capacity ${d.capacity}`, d.state, d.guardrail && `guardrail: ${d.guardrail}`]} />
  </Card>
);

export const McpCard = ({ m }: { m: McpServer }) => (
  <Card>
    <h3>{m.name}</h3>
    <p>{m.target || "No endpoint"}</p>
    <div className="meta">{where(m)}</div>
    <Chips items={[m.category, m.authType, m.source]} />
    <PortalLink url={m.portalUrl} />
  </Card>
);

export const KnowledgeCard = ({ k }: { k: Knowledge }) => (
  <Card>
    <h3>{k.name}</h3>
    <p>{k.type}{k.target ? ` · ${k.target}` : ""}</p>
    <div className="meta">{where(k)}</div>
    <Chips items={[k.category, k.source]} />
    <PortalLink url={k.portalUrl} />
  </Card>
);

export const GuardrailCard = ({ g }: { g: Guardrail }) => {
  const levels: Record<string, string> = {};
  (g.filters || []).filter((f) => f.source !== "Completion" && f.severityThreshold).forEach((f) => { levels[f.name] = f.severityThreshold!; });
  const extras = [...new Set((g.filters || []).filter((f) => !f.severityThreshold).map((f) => f.name))];
  return (
    <Card>
      <h3>{g.name}</h3>
      <p>{g.type || ""}{g.basePolicy ? ` · based on ${g.basePolicy}` : ""}</p>
      <div className="meta">{where(g)}</div>
      <Chips items={[...Object.entries(levels).map(([k, v]) => `${k}: ${v}`), ...extras]} />
      <div className="meta">{g.usedBy?.length ? `Used by: ${g.usedBy.join(", ")}` : "Not assigned to any deployment"}</div>
    </Card>
  );
};
