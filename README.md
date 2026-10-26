# Agent Hub

A web app for your Azure AI Foundry estate (formerly "Foundry Agent Marketplace"). The home screen has four areas:

| Area | What it does |
|---|---|
| **Marketplace** | Search agents, models, MCP servers, knowledge bases and guardrails across all projects |
| **Agent Factory** | Create an agent (model, instructions, MCP servers, guardrail), edit it as a new version, or delete it |
| **Guardrails** | List content-filter policies and create new ones |
| **Playground** | Chat with any model deployment or agent; useful for testing guardrails |

Discovery walks subscriptions -> AIServices accounts -> projects, in parallel, and caches the result (`CACHE_TTL`).

## Run

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cd frontend; npm install; npm run build; cd ..   # builds the React UI into frontend/dist (needs Node 20+)
az login                       # DefaultAzureCredential picks this up
uvicorn app.main:app --reload  # http://localhost:8000
```

Settings go in `.env` (see below). Try it without Azure: set `MARKETPLACE_DEMO=1`.

### Front end (React + TypeScript)
The UI lives in [frontend/](frontend/) (Vite, React, React Router, plain CSS). FastAPI serves the built files from `frontend/dist`; if that folder doesn't exist it falls back to the older single page in `app/static/`.
- Develop with hot reload: run `uvicorn` on :8000, then `cd frontend; npm run dev` and open http://localhost:5173 (calls to `/api` are proxied).
- Check types: `npm run typecheck`. Run tests: `npm test` (Vitest + Testing Library). Production build: `npm run build`.
- Python tests (risk rules, sign-in, roles, CSRF, timeouts, dashboard numbers): `pip install -r requirements-dev.txt`, then `.\.venv\Scripts\python.exe -m pytest tests`.

Troubleshooting on Windows:
- *"running scripts is disabled"*: run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first, or call `.\.venv\Scripts\python.exe` directly.
- *`az` not recognized*: install the Azure CLI (`winget install -e --id Microsoft.AzureCLI`) and open a new terminal.

## Configuration (`.env`)

| Variable | Meaning |
|---|---|
| `AZURE_SUBSCRIPTION_IDS` | Comma-separated subscription IDs to scan. Blank scans every subscription you can see |
| `MARKETPLACE_DEMO` | `1` uses built-in sample data and makes no Azure calls |
| `CACHE_TTL` | Seconds before the catalog counts as stale and is refreshed in the background (default 300) |
| `CACHE_MAX_AGE` | Seconds after which saved data is too old to show; the app rescans first (default 86400) |
| `CACHE_FILE` | Where the catalog is saved (default `.cache/catalog.json`); `off` disables the file |
| `PLANNER_AGENT` | Name of the Foundry agent that powers the plain-English features (default `agent-hub-planner`). It is created automatically in the first project with a chat model, and uses only the project-level Azure AI User role |
| `PLANNER_AUTOCREATE` | `0` stops the app creating the planner agent; then create one yourself with that name |
| `PLANNER_DEPLOYMENT`, `PLANNER_ACCOUNT` | Optional. Call a model deployment directly instead of the planner agent. Needs the Cognitive Services OpenAI User role on the account |
| `NL_FEATURES` | `0` turns off the AI step; plain-English features then use keyword matching only |
| `AUTH_MODE` | `azcli` (default): the user is whoever ran `az login`. `entra`: Microsoft Entra ID sign-in for a shared deployment. `off`: no identity at all. See "Sign-in and roles" |
| `DEV_ROLE` | Role used in `azcli` and `off` modes (default `Admin`). Set `Viewer`, `Builder` or `Approver` to see what each role can do |
| `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET`, `PUBLIC_URL` | Needed when `AUTH_MODE=entra`. `PUBLIC_URL` is the address users open, e.g. `https://hub.contoso.com` |
| `SESSION_IDLE_MINUTES`, `SESSION_MAX_HOURS` | Sign-out after this much inactivity (default 30) or this long in total (default 8) |
| `DEFAULT_ROLE` | Optional role for signed-in users who have none assigned. Leave unset to refuse them |
| `STALE_DAYS` | Days without an update before an agent is listed as stale on the dashboard (default 90) |
| `EVAL_PASS_RATE` | Overall pass rate (percent) an agent needs on an evaluation to count as ready to release (default 80). Every safety check must also pass |
| `EVALS_FILE` | Where test sets and run history are saved (default `.cache/evals.json`); `off` keeps them in memory only |
| `RISK_ENFORCE` | `1` makes the risk check mandatory on every agent create, even from API calls that don't send answers. Without it, the Agent Factory always checks, other callers are advisory |
| `CORP_DOMAINS` | Comma-separated corporate domains (e.g. `contoso.com`). MCP servers outside them add risk. Blank means this isn't checked |
| `POLICY_FILE` | Optional JSON file overriding the risk weights (`points`) and tier cut-offs (`thresholds`) |
| `AUDIT_FILE` | Audit log location (default `.cache/audit.log`); `off` disables it |

## Local cache
The scanned catalog is saved to `.cache/catalog.json`, so a restart opens instantly instead of waiting for the Azure scan.
- Fresh (under `CACHE_TTL`): served from memory.
- Stale: served immediately while a background thread rescans; the header shows "refreshing…".
- Too old (`CACHE_MAX_AGE`), missing, or after you create, edit or delete something through the app: rescanned before answering.
- If Azure can't be reached, the last saved catalog keeps being shown and the header tooltip says the refresh failed. **Refresh from Azure** always forces a live scan.
- The file holds the catalog, including agent instructions and project names. It is not encrypted, so keep the folder private and do not commit `.cache/`.
- A changed `AZURE_SUBSCRIPTION_IDS` or a corrupt file is ignored and rebuilt.

## Sign-in and roles
There are three modes, set with `AUTH_MODE`:

| Mode | Who the user is | Use it for |
|---|---|---|
| `azcli` (default) | Whoever ran `az login` on this machine. Name, email and tenant are read from the Azure CLI's token, and the app makes its Azure calls as that same account | Running on your own machine |
| `entra` | Whoever signs in with Microsoft Entra ID, with roles from Entra app roles | A shared deployment for many users |
| `off` | Nobody; a fixed local user | Tests and demos |

**`azcli` mode.** If nobody is logged in the page says to run `az login` and offers "check again". Switching accounts: run `az login` as the other account, then use **Switch account** in the user menu (the identity is also re-read every 5 minutes). There are no app roles in this mode, so the role comes from `DEV_ROLE` (default `Admin`); a service principal login shows its application id instead of an email. Anyone who can open the page acts as that Azure account, so use it only on your own machine (`uvicorn` listens on localhost by default) and use `entra` mode for anything shared. In every mode, requests that change something must carry a custom header and a matching `Origin`, which stops other web pages in your browser from posting to a local server.

**`entra` mode, how it works.** Users sign in with Microsoft Entra ID (authorization-code flow with PKCE). The browser only holds an opaque, random session id in an `HttpOnly` cookie; Entra and Azure tokens stay on the server and are not stored. Sessions end after `SESSION_IDLE_MINUTES` of inactivity or `SESSION_MAX_HOURS` in total, and the page warns two minutes before. **Sign out** (user menu) ends the session here and at Entra. Every request that changes something must carry a custom header and a matching `Origin`, which blocks cross-site requests.

**One-time Entra setup (an Entra administrator):**
1. App registrations, New registration, single tenant. Add the redirect URI `<PUBLIC_URL>/auth/callback` (platform **Web**).
2. Certificates and secrets: create a client secret and put it in `ENTRA_CLIENT_SECRET`. Copy the tenant and application (client) IDs into `ENTRA_TENANT_ID` and `ENTRA_CLIENT_ID`.
3. App roles: create four roles with these exact values: `Viewer`, `Builder`, `Approver`, `Admin` (allowed member type: Users/Groups).
4. Enterprise applications, your app, Users and groups: assign users or groups to roles. People with no role see "Access not granted".

**What each role can do** (the server enforces it; the page hides what you cannot use):
| Role | Can |
|---|---|
| Viewer | Browse, search, Ask, risk check, chat with agents and models |
| Builder | Everything a Viewer can, plus refresh from Azure, create and edit agents, create a recommended guardrail |
| Approver | Everything a Builder can, plus delete agents and create custom guardrails |
| Admin | Everything (reserved for future settings and policy pages) |
The highest role wins when a user has several. Deleting is limited to Approvers until agents have recorded owners.

The audit log now records who did each action (name, email, role). The sign-in flow itself needs a real Entra tenant to verify; the rest (roles, sessions, timeouts, CSRF) is covered by automated tests that create sessions directly.

## Portfolio dashboard
The home page shows leadership numbers from the latest scan: agents, projects, models, MCP servers, knowledge bases, guardrails; **guardrail coverage** (agents with a dedicated guardrail); models in use; and a **Needs attention** list (agents without a dedicated guardrail, stale agents, agents with no description, classic assistants, MCP servers outside `CORP_DOMAINS`, scan problems). Each attention item links to the filtered list, and the filter is the same code that produces the number, so the two cannot disagree. The app's own helper agent (`agent-hub-planner`) is tagged "System", hidden by default and excluded from every count.

## Evaluations
The **Evaluations** page tests each managed agent and keeps the results.
- **Creating a missing evaluation:** an agent with no evaluation shows a **Create an evaluation** panel that previews the checks we would build, each with the reason it is there, and offers **Create and run**, **Create without running**, or **Review and edit first**. The same one-click set up is on the Marketplace card ("Create evaluation" on an unevaluated agent, for Builders), on the success message after you create an agent in the Agent Factory, and as **Evaluate the N unevaluated** on the Evaluations page (confirms first; starts up to 10 at a time). An existing test set is never overwritten.
- **Test set:** built for the agent, not generic. Every agent gets four standard safety probes (prompt injection, data exfiltration, a harmful request, a jailbreak attempt), a purpose question and a "stays in scope" check, quality questions written from its description (by the planner model when available), and a "no made-up sources" check if it has knowledge bases. On top of that, extra safety probes come from the same facts as the risk profile: personal or regulated data adds record-lookup and bulk-export probes; tools that can change things add a "delete without confirming" probe; medical, legal, financial or eligibility use adds a "definitive advice" probe; customer or public use adds an abuse probe. **Suggest more checks** in the Test set tab adds whatever the current set is missing. Builders can edit, add and remove checks and save the set.
- **Run:** **Run evaluation** sends each check to the agent in a fresh conversation, with live progress. Answers are graded by rules (must refuse, must contain, must not contain) and, when the planner model is reachable, rated 1 to 5 by it against the check's criteria (3 or more passes; safety needs 4). If the platform's content filter blocks a request, that counts as a refusal: a pass for a safety check, a fail for an ordinary one. Without a judge model quality answers are only checked for being present, and the page says they were not rated.
- **Release gate:** a run is **Ready to release** only if the pass rate reaches `EVAL_PASS_RATE` (default 80%) **and** every safety check passed; otherwise **Not ready**.
- **Results:** summary tiles (overall, per category, average judge score, response time), a per-check table where each row opens the prompt and the agent's full answer, and a history with a pass-rate trend line against the threshold. Up to 50 runs per agent are kept.
- **Elsewhere:** Marketplace cards show "73% checks passed · not ready" (or "· ready"), or "Not evaluated"; the dashboard shows evaluation health and adds "Agents that failed their latest evaluation" and "never evaluated" to Needs attention, each linking to the matching list.
- **Roles:** Viewers see results; Builders run evaluations and edit test sets. Runs and test-set saves are recorded in the audit log.
- **Limits:** classic assistants cannot be evaluated (no chat call for them here). Only new-generation agents with a chat endpoint are covered. Runs execute inside the app process, one at a time per agent; the history is a local file, not a database. Release is not yet blocked automatically: the gate is shown, not enforced at agent creation.

## Risk profile and guardrail suggestion
The Agent Factory scores every agent as you build it, and shows the evidence.
- **Rubric (fixed rules, not a model's opinion):** audience, most sensitive data, ability to act, high-impact domain, human review, web grounding and non-corporate MCP servers each add points. Total score gives **Low / Medium / High / Critical** (cut-offs 3 / 6 / 11), and safety rules can raise it (regulated data, medical or eligibility decisions, or write access with sensitive data or a public audience).
- **Unknown facts** become questions on the page. Until you answer, a cautious assumption is used and marked "assumed". "Draft with AI" pre-fills what the description clearly states.
- **Guardrail recommendation:** each tier maps to a content-filter template. The page offers an existing policy that already meets it, or creates `hub-<tier>-v1` for you (Medium and High). It also lists controls to apply, including safety text you can add to the instructions in one click.
- **Enforcement:** if the selected guardrail is weaker than recommended, creating the agent needs a written reason (kept in the audit log). **Critical** agents are blocked: they need review-board approval and are not created from the app.
- **Audit log:** every agent create/delete and guardrail create is appended to `.cache/audit.log` with the tier, answers and any override reason.
- The extra filters in the High and Medium templates (jailbreak, indirect attack, protected material) use filter names from Azure's content-filter format as I understand it; confirm they are accepted in your tenant. The weights and cut-offs are starting points for your risk owners to tune with `POLICY_FILE`.

## Plain-English features
- **Ask in the Marketplace:** type what you need ("an agent that reviews supplier contracts"). The catalog is searched by keyword, then the planner model re-ranks the top matches and explains each in one line. It can only pick assets that exist in the catalog.
- **Draft with AI in the Agent Factory:** describe the agent you want. The planner proposes a name, instructions, model, MCP servers, knowledge bases and guardrail, limited to what exists in the selected project. The form is pre-filled for you to review; nothing is created until you press Create. Needs that no existing asset meets are listed as "not available".
- If the model can't be reached, both features still work with keyword matching and say so on the page.

## How it connects to Azure

The server signs in with `DefaultAzureCredential` (your `az login`, a service principal from `AZURE_TENANT_ID`/`AZURE_CLIENT_ID`/`AZURE_CLIENT_SECRET`, or a managed identity when deployed). The browser never sees a token. All Azure calls are in [app/discovery.py](app/discovery.py).

| API | Scope | Used for |
|---|---|---|
| ARM `https://management.azure.com` (api-version 2025-06-01) | `management.azure.com/.default` | Subscriptions, accounts, projects, deployments, connections, guardrails (list and create) |
| Foundry project data plane `https://<account>.services.ai.azure.com/api/projects/<project>` | `ai.azure.com/.default` | Agents and indexes (list), agent create/delete, agent chat |
| Azure OpenAI `https://<account>.openai.azure.com` | `cognitiveservices.azure.com/.default` | Playground model chat |

### Feature to API

| Action | Azure call |
|---|---|
| Marketplace tabs | Cached scan: ARM `accounts`, `deployments`, `raiPolicies`, `projects`, `connections`; data plane `/agents`, `/assistants`, `/indexes` |
| Create agent / save new version | `POST {project}/agents/{name}/versions` |
| Delete agent | `DELETE {project}/agents/{name}` |
| Agent chat (cards and Playground) | `POST {project}/openai/v1/responses` with `agent_reference` |
| Create guardrail | `PUT {account}/raiPolicies/{name}` (ARM) |
| Playground model chat | `POST /openai/v1/chat/completions` on the account |

The full call order, request bodies, safety choices and known uncertainties are in [ARCHITECTURE.md](ARCHITECTURE.md).

## Required access

| Action | Role |
|---|---|
| Browse (ARM listings) | Reader on the subscriptions or resource groups |
| Agents and indexes; chat; create/delete agents | **Azure AI User** on each project |
| Create guardrails | Cognitive Services Contributor on the account |
| Playground model chat | Cognitive Services OpenAI User on the account |

Projects or accounts you can't read are skipped. The reasons show on the page ("Discovery errors") and in the server log.

## App API

| Endpoint | Purpose |
|---|---|
| `GET /api/{agents,deployments,mcp,knowledge,guardrails}?q=&project=&account=` | Catalog lists |
| `GET /api/summary`, `POST /api/refresh` | Counts, errors, rescan |
| `GET /api/projects`, `GET /api/accounts` | Choices for the Agent Factory and Guardrails forms |
| `POST /api/agents/create`, `/delete`, `/chat` | Agent management and chat |
| `POST /api/guardrails/create` | New content filter |
| `POST /api/playground/chat` | Model chat |
| `POST /api/discover` | Plain-English search over the catalog |
| `POST /api/agents/draft` | Plain-English agent draft (creates nothing) |
| `POST /api/agents/assess` | Risk tier, evidence, questions, guardrail recommendation and controls |
| `GET/PUT /api/evals/suite` | An agent's test set (starter set until saved) |
| `POST /api/evals/create`, `POST /api/evals/suggest` | Build the first test set for an agent (and optionally run it); list checks a test set is missing |
| `POST /api/evals/run`, `GET /api/evals/runs`, `GET /api/evals/runs/{id}`, `GET /api/evals/latest` | Start a run, list runs, read one run with all results, newest result per agent |
| `POST /api/guardrails/create-template` | Create the recommended content filter for a tier |

## Notes
- The Foundry data-plane API is evolving; endpoints are isolated in `app/discovery.py`. Agent chat, guardrail-on-agent (`rai_config`) and guardrail creation haven't been verified against every tenant. See ARCHITECTURE.md section 6.
- The app has no sign-in of its own: anyone who can reach it acts with the server's Azure identity. Add authentication before sharing it.
- Not implemented: assigning a guardrail to a model deployment, Azure AI Search / file-search tools on new agents.
