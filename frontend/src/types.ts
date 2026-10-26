// Shapes returned by the Agent Hub API (see app/main.py).

export interface Summary {
  counts: Record<string, number>;
  fetchedAt: number;
  demo: boolean;
  errors: string[];
  projects: string[];
  refreshing: boolean;
  fromDisk: boolean;
  refreshError: string | null;
}

interface Located {
  account?: string;
  project?: string | null;
  subscription?: string;
  resourceGroup?: string;
  location?: string | null;
}

export interface McpTool { type: string; server_url?: string; azure_ai_search?: { indexes?: { index_name: string }[] }; [k: string]: unknown }

export interface Agent extends Located {
  id: string; name: string; description: string; model: string | null; instructions: string;
  kind: string; generation: "new" | "classic"; created: number | null;
  tools: string[]; toolDefs: McpTool[]; mcpServers: string[]; knowledge: string[];
  guardrail: string | null; portalUrl?: string; system?: boolean; eval?: EvalLatest | null;
}

/** Newest finished evaluation for an agent, as attached to agent lists. */
export interface EvalLatest { runId: string; passRate: number; gate: "pass" | "fail"; at: number; total: number }
export type EvalCategory = "quality" | "safety" | "grounding";
export interface EvalCase {
  id: string; category: EvalCategory; title: string; prompt: string; criteria: string; why?: string;
  expect: { refuse?: boolean; contains?: string[]; not_contains?: string[] };
}
export interface EvalResult {
  id: string; category: EvalCategory; title: string; prompt: string; response: string; passed: boolean;
  score: number | null; reasons: string[]; blocked: boolean; error: boolean; ms: number; judged: boolean;
}
export interface EvalSummary {
  total: number; passed: number; passRate: number; gate: "pass" | "fail"; avgMs: number; avgScore: number | null;
  judged: number; errors: number; safetyAllPassed: boolean; byCategory: Partial<Record<EvalCategory, { total: number; passed: number; pct: number }>>;
}
export interface EvalRun {
  id: string; key: string; status: "running" | "done" | "failed"; startedAt: number; finishedAt: number | null; actor: string;
  suiteSize: number; progress: { done: number; total: number }; threshold: number; summary: EvalSummary | null;
  results?: EvalResult[]; error: string | null;
}
export interface Deployment extends Located {
  id: string; name: string; model: string | null; version: string | null; publisher: string | null;
  sku: string | null; capacity: number | null; state: string | null; guardrail: string | null;
}
export interface McpServer extends Located {
  id: string; name: string; category: string; target: string | null; authType?: string | null; source: string; portalUrl?: string;
}
export interface Knowledge extends Located {
  id: string; name: string; type: string; category: string; target: string | null; source: string; portalUrl?: string;
}
export interface ContentFilter { name: string; source?: string; severityThreshold?: string; blocking?: boolean; enabled?: boolean }
export interface Guardrail extends Located {
  id: string; name: string; type: string | null; basePolicy: string | null; mode: string | null;
  filters: ContentFilter[]; usedBy: string[];
}

export type Kind = "agents" | "deployments" | "mcp" | "knowledge" | "guardrails";
export interface KindMap { agents: Agent; deployments: Deployment; mcp: McpServer; knowledge: Knowledge; guardrails: Guardrail }

export interface ProjectInfo {
  name: string; account: string; models: string[];
  mcp: { name: string; target: string }[];
  knowledge: { name: string; connection: string }[];
  guardrails: string[];
}
export interface AccountInfo { name: string; location: string | null }

export type AssetType = "agent" | "model" | "mcp" | "knowledge" | "guardrail";
export interface DiscoverResult { type: AssetType; name: string; account?: string; project?: string | null; reason: string; score?: number }
export interface DiscoverResponse { mode: "ai" | "keyword"; note?: string | null; results: DiscoverResult[] }

export type Facts = Record<string, string | boolean>;
export interface AgentDraft {
  name: string; description: string; instructions: string; model: string; mcp: string[]; knowledge: string[]; guardrail: string | null;
}
export interface DraftResponse {
  mode: "ai" | "keyword" | "none"; note: string | null; draft: AgentDraft | null;
  reasons?: Record<string, string>; missing?: string[]; facts?: Facts;
}

export interface RiskFactor { key: string; label: string; value: string; points: number; evidence: string; assumed: boolean }
export interface RiskQuestion { key: string; text: string; options: Record<string, string> }
export interface RiskControl { id: string; text: string; snippet?: string }
export type Tier = "Low" | "Medium" | "High" | "Critical";
export interface Assessment {
  tier: Tier; score: number; scoreTier: Tier; floorNote: string | null; blocked: boolean;
  factors: RiskFactor[]; facts: Facts; questions: RiskQuestion[]; controls: RiskControl[];
  guardrail: { tier: Tier; satisfying: string[]; selectedOk: boolean; selected: string | null; suggestNew: string | null; extras: string[] };
}

export type Role = "Viewer" | "Builder" | "Approver" | "Admin";
export interface Me {
  name: string; email: string; role: Role | null; roles: Role[]; access: boolean; mode: "off" | "entra" | "azcli";
  expiresAt: number | null; source?: string; tenant?: string;
}

export interface AttentionItem {
  filter: string | null; severity: "warn" | "info"; title: string; count: number; examples: { name: string; project?: string | null }[];
}
export interface Portfolio {
  kpis: { agents: number; projects: number; models: number; mcp: number; knowledge: number; guardrails: number };
  governance: {
    managedAgents: number; withGuardrail: number; withoutGuardrail: number; coveragePct: number | null; classicAgents: number;
    evaluated: number; evalsPassing: number; evalsFailing: number;
  };
  byModel: [string, number][]; byGuardrail: [string, number][];
  attention: AttentionItem[]; staleDays: number; corpDomainsSet: boolean;
}

export interface ChatReply { text: string; id?: string | null; finish?: string | null }
export interface Turn { role: "system" | "user" | "assistant"; content: string }
