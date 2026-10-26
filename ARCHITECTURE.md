# Architecture: how the app talks to Azure

This document explains how the app authenticates to Azure, and which Azure API each screen and button calls.

## 1. Overview

```
Browser (app/static/index.html, hash routes)
   │  fetch /api/...
   ▼
FastAPI (app/main.py)         caching, validation, request shaping
   │
   ▼
Discovery (app/discovery.py)  the only file that talks to Azure
   ├── ARM (control plane)    https://management.azure.com
   ├── Foundry project (data plane)   https://<account>.services.ai.azure.com/api/projects/<project>
   └── Azure OpenAI endpoint  https://<account>.openai.azure.com
```

The browser never holds an Azure token. The server calls Azure with the identity of whoever started `uvicorn`, and every user of the web UI gets that identity's access.

## 2. Authentication

`Discovery.__init__` creates one `DefaultAzureCredential`. It tries these sources in order and uses the first that works:

1. Environment variables (`AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`): a service principal.
2. Workload identity / managed identity (when deployed on Azure).
3. Visual Studio Code, Azure CLI (`az login`), Azure PowerShell, `azd`.

For local development, `az login` is enough. Each request asks the credential for a token for the right **scope**, and sends it as `Authorization: Bearer <token>`:

| Scope | Used for |
|---|---|
| `https://management.azure.com/.default` | ARM: subscriptions, accounts, projects, deployments, connections, guardrails |
| `https://ai.azure.com/.default` | Foundry project data plane: agents, indexes, agent chat |
| `https://cognitiveservices.azure.com/.default` | Azure OpenAI chat completions (Playground, models) |

Tokens are cached and refreshed by the credential, so the app doesn't manage them.

### Required roles

| Action | Role |
|---|---|
| List subscriptions, accounts, projects, deployments, connections, guardrails | Reader on the subscription or resource groups |
| List, create, delete and chat with agents; list indexes | Azure AI User on each project (creating agents may need a role that can write agents) |
| Create guardrails | Cognitive Services Contributor (or any role that can write to the account) |
| Playground model chat | Cognitive Services OpenAI User on the account |

A project or account you can't read is skipped, and the reason is recorded in the `errors` list shown on the page.

## 3. Discovery (the catalog)

`Discovery.scan()` runs on first request and when you press **Refresh**. The result is cached for `CACHE_TTL` seconds (default 300). Creating, deleting or editing an agent or guardrail marks the cache stale so the next view rescans.

Order of calls:

1. **Subscriptions.** `GET /subscriptions?api-version=2022-12-01` (ARM). Skipped if `AZURE_SUBSCRIPTION_IDS` is set; then only those are scanned.
2. **Accounts.** `GET /subscriptions/{sub}/providers/Microsoft.CognitiveServices/accounts?api-version=2025-06-01`. Only kinds `AIServices` and `OpenAI` are kept.
3. **Per account** (ARM, same api-version):
   - `GET {account}/deployments`: the Models tab.
   - `GET {account}/raiPolicies`: guardrails (content filters).
   - `GET {account}/projects`: Foundry projects.
4. **Per project, in parallel (8 workers).**
   - ARM `GET {project}/connections`: classified by `category`: `RemoteTool`, `MCP`, `RemoteA2A` become MCP servers; `CognitiveSearch`, `AzureAISearch`, `AzureBlob` become knowledge bases.
   - Data plane `GET {endpoint}/indexes?api-version=v1`: knowledge bases of type "Project index".
   - Data plane `GET {endpoint}/agents?api-version=v1`: new-generation agents (latest version's definition: model, instructions, tools, guardrail).
   - Data plane `GET {endpoint}/assistants?api-version=v1`: classic agents.

   MCP tools found inside agent definitions are added to the MCP list (de-duplicated by URL).

The project endpoint is `endpoints["AI Foundry API"]` from the account, or `https://<customSubDomainName>.services.ai.azure.com`, plus `/api/projects/<project>`.

Every call goes through `_safe()`: a failure is logged, added to `errors`, and the scan continues. One broken project never blocks the rest. Paged results follow `nextLink`.

### Sign-in, sessions and roles (`app/auth.py`)

Every `/api` route declares a minimum role through the `auth.require("Viewer|Builder|Approver|Admin")` dependency (`/healthz`, `/auth/*` and the static files are open). With `AUTH_MODE=entra`, the dependency looks up the `hub_session` cookie in an in-memory `SessionStore` (random 256-bit id; idle and absolute timeouts; the user record holds name, email and role names only), returns 401 if there is none, 403 if the user has no role or too low a role, and, for POST requests, checks the `X-Requested-With: AgentHub` header and that `Origin` matches the host. The Entra exchange uses MSAL's `initiate_auth_code_flow` / `acquire_token_by_auth_code_flow` (state, nonce and PKCE handled by MSAL; the pending flow is held server-side and used once); the returned tokens are discarded, and only the validated ID-token claims (`name`, `preferred_username`, `roles`) become the user. The return address after login must be a same-site relative path. `POST /auth/logout` removes the session and returns Entra's end-session URL. `GET /api/me` reports the user and does not extend an idle session; `POST /api/session/keepalive` does. In `AUTH_MODE=azcli` (the default) `azcli_user()` asks `AzureCliCredential` for a management-plane token, reads its claims (`name`, `upn`/`unique_name`, `tid`, `oid`, or `appid` for a service principal) without verifying them (the token was just obtained locally from the CLI), and caches the result for 5 minutes (5 seconds while nobody is logged in, so `az login` is noticed quickly); `GET /api/me?refresh=true` bypasses the cache. `Discovery` then uses `AzureCliCredential` too, so the identity shown in the header is the one making the Azure calls. The role in this mode is `DEV_ROLE`. In `AUTH_MODE=off`, or in demo mode, the dependency returns a fixed local user. The CSRF header and `Origin` check run in all modes, because a server on localhost can otherwise be driven by any page open in the same browser. The in-memory store means one process; use Redis or a database behind the same interface to run several instances. `audit.record(..., user=...)` writes the user as the actor.

### Evaluations (`app/evals.py`)

A test set is a list of cases (`category` quality, safety or grounding; a `prompt`; optional `criteria` text; `expect` rules). `POST /api/evals/run` creates a run record, takes a snapshot for the response, and starts a daemon thread running `evals.execute`: for each case it calls the agent through `Discovery.chat` (the Responses API, one fresh turn, no `previous_response_id`) and grades the answer with `evals.grade`. Grading order: a content-filter error from the service (matched by `content_filter` or `ResponsibleAIPolicyViolation` in the error text) is a refusal; otherwise rule checks run, and if a judge is available the planner agent returns `{"score":1-5,"reason":...}` (the same planner used for Ask and Draft). A broken or unparseable judge reply falls back to wording checks for safety cases and to "answered" for quality cases; it never turns a failure into a pass on its own for safety. `summarize()` computes the pass rate, per-category rates, average latency and score, and the gate (`passRate >= EVAL_PASS_RATE` and all safety cases passed). `EvalStore` keeps suites and runs in one JSON file written atomically (50 runs per agent). `latest()` gives the newest finished run per agent; `list_items` attaches it to each agent as `eval`, and `portfolio.agent_filter` uses it for the `no-eval` and `failing-eval` filters, so the dashboard counts and the lists agree. The starter set is built by `evals.default_cases(agent, llm, facts)`, where `facts` come from `risk.assess` run on the agent's description, instructions, MCP tools and guardrail (`_agent_facts` in `app/main.py`), so unknowns are assumed cautiously and the extra probes in `evals.risk_probes` follow the same rubric as the risk profile; each case carries a `why` shown to the user. `POST /api/evals/create` saves that set only if the agent has none (it never overwrites) and can start the first run through the same `_start_run` helper as `POST /api/evals/run`, which also saves the starter set when it runs it. `POST /api/evals/suggest` returns `evals.suggest_cases`: cases of the full starter set whose prompts are not already in the saved set. Call errors are classified by `evals.explain_error` (for example an MCP server rejecting the agent's sign-in is reported as a configuration problem, not a failed answer). In demo mode the agent is `demo_chat` and `seed_demo` creates three sample histories (improving, declining, steady). One in-process store means a single instance; use a database to scale out. Enforcement at creation or release is intentionally not wired in yet.

### Portfolio (`app/portfolio.py`)

`compute()` derives the dashboard from the cached catalog, and `agent_filter()` implements each filter name (`no-guardrail`, `stale`, `no-description`, `classic`, `external-tools`). `GET /api/portfolio` returns the numbers; `GET /api/agents?filter=<name>` returns the agents behind them, using the same function. The helper agent named by `PLANNER_AGENT` is marked `system` in lists, hidden unless `system=true`, and excluded from counts.

### Risk and guardrail recommendation (`app/risk.py`, `app/audit.py`)

`risk.assess()` takes the answers (from the form or the planner's extraction), the description text, the attached MCP URLs, the chosen guardrail and the account's guardrails. It returns the factors with their points and evidence, the tier, the questions still open, the recommended content-filter template, whether the chosen guardrail satisfies it (`risk.satisfies` compares filter names, sources and severity strictness), and a controls list. The tier is computed from fixed weights (overridable with `POLICY_FILE`), never by a model; the planner only helps fill in facts. `POST /api/agents/create` re-runs the assessment on the server: a Critical tier returns 403, a weaker-than-recommended guardrail without an override reason returns 422, and the result (tier, facts, override reason) is written by `audit.record()` to an append-only JSON-lines file. The recommended filters are created through `Discovery.create_guardrail_filters`, an ARM `PUT` on `raiPolicies`.

### Front end (`frontend/`)

React + TypeScript, built with Vite into `frontend/dist`, which FastAPI serves (`app/main.py`, route `/` and `/assets`). Hash routes (`#/marketplace`, `#/factory`, ...) keep it a single page with no server routing. `src/api.ts` holds every API call with types from `src/types.ts`; `src/summary.tsx` loads `/api/summary` once and polls while the server refreshes in the background; pages are in `src/pages/`, shared parts in `src/components/` (`RiskPanel`, `ChatDialog`, `Cards`). The risk panel re-runs `POST /api/agents/assess` (debounced) whenever the description, instructions, tools, knowledge, guardrail or answers change.

### Catalog cache (`app/cache.py`)

`CatalogCache` wraps `Discovery.scan()`. State: the catalog, the time it was scanned, a "changed" counter and a refresh flag. Reads follow this order: no data, a forced refresh, a pending change (set by `_invalidate()` after create/delete) or data older than `CACHE_MAX_AGE` -> scan and wait; data older than `CACHE_TTL` -> return it and start one background refresh thread; otherwise return it. Saves go to `.cache/catalog.json` through a temp file and an atomic rename. The file is tagged with a format version and a hash of `AZURE_SUBSCRIPTION_IDS`, so a changed scope or format is ignored. A failed refresh keeps the old data and retries after 60 seconds. It is a single-process cache; running several app instances would each keep their own copy; a shared store such as a database or Redis would be needed to scale out.

## 4. Feature to API map

| Screen / action | App endpoint | Azure call |
|---|---|---|
| Marketplace: all tabs | `GET /api/{agents,deployments,mcp,knowledge,guardrails}` | From the cached scan in section 3 (no live call per request) |
| Refresh from Azure | `POST /api/refresh` | Full rescan |
| Page header counts, errors | `GET /api/summary` | From the cache |
| Agent Factory: project, model and MCP choices | `GET /api/projects` | From the cache |
| Agent Factory: create / save new version | `POST /api/agents/create` | Data plane `POST {endpoint}/agents/{name}/versions?api-version=v1` |
| Agent card: Delete | `POST /api/agents/delete` | Data plane `DELETE {endpoint}/agents/{name}?api-version=v1` |
| Agent card: Chat; Playground with an agent | `POST /api/agents/chat` | Data plane `POST {endpoint}/openai/v1/responses` |
| Guardrails: create | `POST /api/guardrails/create` | ARM `PUT {account}/raiPolicies/{name}?api-version=2025-06-01` |
| Guardrails form: account list | `GET /api/accounts` | From the cache |
| Playground with a model | `POST /api/playground/chat` | `POST https://<account>.openai.azure.com/openai/v1/chat/completions` |
| Marketplace "Ask" | `POST /api/discover` | Catalog only, then (optional) the planner model through the same chat-completions call, in JSON mode |
| Factory "Draft with AI" | `POST /api/agents/draft` | Catalog only, then (optional) the planner model; creates nothing |

### Request shapes

**Create agent** (`definition` is a prompt agent):

```json
{
  "description": "...",
  "definition": {
    "kind": "prompt",
    "model": "<deployment name>",
    "instructions": "...",
    "tools": [{ "type": "mcp", "server_label": "x", "server_url": "https://...", "require_approval": "never" }],
    "rai_config": { "rai_policy_name": "<guardrail>" }
  }
}
```

Posting to an existing name adds a new version. Editing an agent keeps its non-MCP tools and replaces its MCP tools with the ticked set. The MCP URLs and the guardrail name must exist in that project's or account's cached catalog, or the server returns 422.

**Agent chat** (Responses API, one turn per call; pass `previous_response_id` to continue):

```json
{ "input": "hello", "agent_reference": { "type": "agent_reference", "name": "my-agent" }, "previous_response_id": "resp_..." }
```

The older `agent` key is rejected by the service; use `agent_reference`.

**Create guardrail.** Each chosen category and severity is expanded to a prompt filter and a completion filter, based on `Microsoft.DefaultV2`:

```json
{ "properties": { "basePolicyName": "Microsoft.DefaultV2", "mode": "Default",
  "contentFilters": [ { "name": "Hate", "severityThreshold": "Medium", "blocking": true, "enabled": true, "source": "Prompt" }, "..." ] } }
```

Severity means "block at this level and above", so Low is the strictest. Categories: Hate, Sexual, Violence, Selfharm.

**Model chat:** `{ "model": "<deployment>", "messages": [...], "temperature": 0.7 }`. A prompt blocked by a content filter returns HTTP 400 with code `content_filter`; the Playground shows that text in red.

### Plain-English features (`app/nl.py`)

1. `build_assets()` flattens the cached catalog (agents, models, MCP servers, knowledge bases, guardrails) into one list of searchable text records.
2. `rank()` scores them with a TF-IDF style keyword match (name matches count triple). This is the whole path when no planner model is available.
3. If a planner model is reachable (`_planner()` in `app/main.py`), the top 15 candidates are sent to it. For discovery it returns which candidates fit and why; for drafting it returns an agent spec. The prompts forbid anything outside the lists given.
4. The server re-validates the model's answer: only existing models, MCP URLs, indexes and guardrails survive, and names must match the agent-name pattern. The draft is returned to the browser to pre-fill the form; creating still goes through `POST /api/agents/create` and its own checks.

Limits of this first version: ranking is keyword-based (no embeddings yet, so "documentation" will not match "docs"); results are not yet filtered per user; the planner model sees asset names and descriptions but not agent data beyond the first 300 characters of instructions.

## 5. Safety choices in the server

- The browser sends project and account **names**; the server looks up the real endpoint from its own catalog. The browser can't make the server call an arbitrary URL.
- Agent names must match `^[A-Za-z0-9][A-Za-z0-9-]{0,62}$`; guardrail names `^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$`. Chat and instruction lengths are capped.
- MCP tool `headers` and `authorization` values are removed from agent data before it reaches the browser.
- In demo mode (`MARKETPLACE_DEMO=1`) no Azure call is made and writes return fake success.

## 6. Known uncertainties

The Foundry data-plane API is still changing. These calls were written from the documented shape and from service error messages, and haven't been confirmed end to end against every tenant:

- `rai_config` as the field that attaches a guardrail to an agent.
- The `/openai/v1/responses` path for agent chat.
- The `/openai/v1/chat/completions` path on the account's `openai.azure.com` host (needs a custom subdomain).
- Guardrail creation via `raiPolicies` (list is read-only and lower risk).

All of them live in `app/discovery.py`, so a change of path or field name is a one-line edit. The page shows the service's own error text when a call fails.

## 7. Not implemented

- Assigning a guardrail to a model deployment (needs a full deployment rewrite; use the Foundry portal).
- Azure AI Search and file-search tools on new agents.
- Sign-in for the UI: anyone who can reach the server acts with the server's Azure identity. Put it behind authentication before sharing it.
