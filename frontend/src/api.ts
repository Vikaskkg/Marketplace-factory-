import type {
  AccountInfo, AgentDraft, Assessment, ChatReply, DiscoverResponse, DraftResponse, EvalCase, EvalRun, Facts, Kind, KindMap, Me,
  Portfolio, ProjectInfo, Summary, Turn,
} from "./types";

/** Identifies one agent across accounts and projects. */
export interface AgentId { account: string; project: string; name: string }

/** Raised (as an event) when the server says the session is gone, so the app can show the sign-in page. */
export const UNAUTHORIZED_EVENT = "hub:unauthorized";

/** Error text from the API's {detail} body, or a generic message for validation errors. */
async function parse<T>(r: Response): Promise<T> {
  let body: unknown = null;
  try { body = await r.json(); } catch { /* empty or non-JSON body */ }
  if (r.status === 401) {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    throw new Error("Your session has ended. Please sign in again.");
  }
  if (!r.ok) {
    const detail = (body as { detail?: unknown } | null)?.detail;
    throw new Error(typeof detail === "string" ? detail : r.statusText || "Invalid input");
  }
  return body as T;
}

export const getJSON = <T>(url: string): Promise<T> => fetch(url).then((r) => parse<T>(r));
// The custom header is the CSRF guard for cookie sessions: another site cannot add it to a cross-site request.
export const post = <T>(url: string, body: unknown): Promise<T> =>
  fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-Requested-With": "AgentHub" }, body: JSON.stringify(body) })
    .then((r) => parse<T>(r));

export const api = {
  /** Used by the sign-in gate; a 401 here is an answer, not an error, so it bypasses `parse`. */
  me: async (refresh = false): Promise<{ status: "in"; me: Me } | { status: "out"; mode: string }> => {
    const r = await fetch(refresh ? "/api/me?refresh=true" : "/api/me");   // refresh re-reads the Azure CLI login
    if (r.status === 401) return { status: "out", mode: ((await r.json().catch(() => ({}))) as { mode?: string }).mode ?? "entra" };
    if (!r.ok) throw new Error(r.statusText);
    return { status: "in", me: (await r.json()) as Me };
  },
  logout: () => post<{ redirect: string }>("/auth/logout", {}),
  keepalive: () => post<{ ok: boolean }>("/api/session/keepalive", {}),
  portfolio: () => getJSON<Portfolio>("/api/portfolio"),
  evalSuite: (a: AgentId) => getJSON<{ cases: EvalCase[]; isDefault: boolean; threshold: number }>(`/api/evals/suite?${new URLSearchParams({ ...a })}`),
  saveEvalSuite: (a: AgentId, cases: EvalCase[]) => fetch("/api/evals/suite", {
    method: "PUT", headers: { "Content-Type": "application/json", "X-Requested-With": "AgentHub" }, body: JSON.stringify({ ...a, cases }),
  }).then((r) => parse<{ ok: boolean; cases: EvalCase[] }>(r)),
  runEval: (a: AgentId) => post<EvalRun>("/api/evals/run", a),
  /** Builds a test set for an agent that has none (never overwrites one) and optionally starts the first run. */
  createEval: (a: AgentId, run: boolean) => post<{ created: boolean; cases: EvalCase[]; run: EvalRun | null }>("/api/evals/create", { ...a, run }),
  suggestEval: (a: AgentId) => post<{ cases: EvalCase[] }>("/api/evals/suggest", a),
  evalRuns: (a: AgentId) => getJSON<EvalRun[]>(`/api/evals/runs?${new URLSearchParams({ ...a })}`),
  evalRun: (id: string) => getJSON<EvalRun>(`/api/evals/runs/${id}`),
  summary: () => getJSON<Summary>("/api/summary"),
  refresh: () => post<unknown>("/api/refresh", {}),
  list: <K extends Kind>(kind: K, q = "", project = "", extra: { filter?: string; system?: boolean } = {}) => {
    const p = new URLSearchParams({ q, project });
    if (extra.filter) p.set("filter", extra.filter);
    if (extra.system) p.set("system", "true");
    return getJSON<KindMap[K][]>(`/api/${kind}?${p}`);
  },
  projects: () => getJSON<ProjectInfo[]>("/api/projects"),
  accounts: () => getJSON<AccountInfo[]>("/api/accounts"),
  discover: (query: string) => post<DiscoverResponse>("/api/discover", { query }),
  draft: (query: string, account: string, project: string) =>
    post<DraftResponse>("/api/agents/draft", { query, account, project }),
  assess: (b: {
    account: string; project: string; description: string; instructions: string;
    mcp: string[]; knowledge: string[]; guardrail: string | null; facts: Facts;
  }) => post<Assessment>("/api/agents/assess", b),
  createAgent: (b: AgentDraft & { project: string; account: string; keep_tools: boolean; facts: Facts; override_reason: string | null }) =>
    post<{ ok: boolean; name: string; version?: string; tier?: string }>("/api/agents/create", b),
  deleteAgent: (b: { project: string; account: string; name: string }) => post<{ ok: boolean }>("/api/agents/delete", b),
  chatAgent: (b: { project: string; account: string; name: string; message: string; previous: string | null }) =>
    post<ChatReply>("/api/agents/chat", b),
  chatModel: (b: { account: string; deployment: string; messages: Turn[]; temperature: number }) =>
    post<ChatReply>("/api/playground/chat", b),
  createGuardrail: (b: { account: string; name: string; thresholds: Record<string, string> }) =>
    post<{ ok: boolean; name: string }>("/api/guardrails/create", b),
  createGuardrailFromTemplate: (b: { account: string; tier: "Medium" | "High" | "Critical" }) =>
    post<{ ok: boolean; name: string }>("/api/guardrails/create-template", b),
};
