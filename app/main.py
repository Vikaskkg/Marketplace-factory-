from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

from . import audit, auth, evals, nl, portfolio, risk  # noqa: E402
from .cache import CatalogCache  # noqa: E402
from .sample_data import DEMO  # noqa: E402

STATIC = Path(__file__).parent / "static"
DIST = Path(__file__).parent.parent / "frontend" / "dist"
KINDS = ("agents", "deployments", "mcp", "knowledge", "guardrails")

app = FastAPI(title="Agent Hub")
app.include_router(auth.router)


def _load() -> dict:
    if os.getenv("MARKETPLACE_DEMO") == "1":
        return DEMO
    from .discovery import Discovery  # imported lazily so demo mode needs no Azure SDK setup
    return Discovery().scan()


_demo_mode = os.getenv("MARKETPLACE_DEMO") == "1"
_cache = CatalogCache(
    _load,
    None if _demo_mode or os.getenv("CACHE_FILE") == "off"
    else Path(os.getenv("CACHE_FILE") or Path(__file__).parent.parent / ".cache" / "catalog.json"),
    ttl=int(os.getenv("CACHE_TTL", "300")), max_age=int(os.getenv("CACHE_MAX_AGE", "86400")),
    scope=os.getenv("AZURE_SUBSCRIPTION_IDS", ""))


def catalog(force: bool = False) -> dict:
    try:
        return _cache.get(force)
    except Exception as e:
        raise HTTPException(502, f"Discovery failed: {e}") from e


def _invalidate() -> None:
    _cache.invalidate()


VIEWER = [Depends(auth.require("Viewer"))]


@app.get("/healthz")
def healthz():
    """Liveness for load balancers: no sign-in, no Azure call."""
    return {"ok": True}


@app.get("/api/summary", dependencies=VIEWER)
def summary():
    c = catalog()
    counts = {k: len(c.get(k, [])) for k in KINDS}
    counts["agents"] = sum(1 for a in c.get("agents", []) if a["name"] != PLANNER_AGENT)   # the helper agent is not a business agent
    return {"counts": counts, "fetchedAt": c["fetchedAt"],
            "demo": os.getenv("MARKETPLACE_DEMO") == "1", "errors": c.get("errors", [])[:5],
            "projects": sorted({p["name"] for p in c.get("projects", [])}),
            "refreshing": c["refreshing"], "fromDisk": c["fromDisk"], "refreshError": c["refreshError"]}


@app.post("/api/refresh", dependencies=[Depends(auth.require("Builder"))])
def refresh():
    c = catalog(force=True)
    return {"counts": {k: len(c.get(k, [])) for k in KINDS}, "fetchedAt": c["fetchedAt"]}


@app.get("/api/projects", dependencies=VIEWER)
def projects():
    """Projects an agent can be created in, with the model deployments of their account."""
    c = catalog()
    found = c.get("projects") or [
        {"name": a["project"], "account": a["account"]} for a in c["agents"] if a.get("project")]
    out = {}
    for p in found:
        models = sorted({d["name"] for d in c["deployments"] if d.get("account") == p["account"]})
        mcp = [{"name": m["name"], "target": m["target"]} for m in c["mcp"]
               if m.get("project") == p["name"] and m.get("account") == p["account"] and m.get("target")]
        kb = [{"name": k["name"], "connection": k["target"]} for k in c["knowledge"]
              if k.get("source") == "index" and k.get("project") == p["name"] and k.get("account") == p["account"]
              and k.get("target")]
        rails = sorted(g["name"] for g in c.get("guardrails", []) if g.get("account") == p["account"])
        out[(p["account"], p["name"])] = {"name": p["name"], "account": p["account"], "models": models, "mcp": mcp,
                                          "knowledge": kb, "guardrails": rails}
    return sorted(out.values(), key=lambda p: (p["account"], p["name"]))


class NewAgent(BaseModel):
    project: str
    account: str
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}$")
    model: str = Field(min_length=1)
    instructions: str = Field(min_length=1, max_length=10000)
    description: str = Field("", max_length=500)
    mcp: list[str] = []          # MCP server URLs, must be known to this project's catalog
    knowledge: list[str] = []    # project index names to attach through Azure AI Search
    keep_tools: bool = False     # editing: carry over the agent's existing non-MCP tools
    guardrail: str | None = None  # content-filter policy name from the project's account
    facts: dict | None = None     # answers to the risk questions; omit to skip the risk check (unless RISK_ENFORCE=1)
    override_reason: str | None = Field(None, max_length=500)   # required to go below the recommended guardrail


class AssessReq(BaseModel):
    account: str
    project: str
    description: str = Field("", max_length=1000)
    instructions: str = Field("", max_length=10000)
    mcp: list[str] = []
    knowledge: list[str] = []
    guardrail: str | None = None
    facts: dict = {}


def _rails(c: dict, account: str) -> list[dict]:
    return [{"name": g["name"], "filters": g.get("filters") or []} for g in c.get("guardrails", [])
            if g.get("account") == account]


def _risk(c: dict, r: AssessReq) -> dict:
    return risk.assess(r.facts, f"{r.description}\n{r.instructions}", r.mcp, r.guardrail, _rails(c, r.account))


class AgentRef(BaseModel):
    project: str
    account: str
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}$")


class ChatMsg(AgentRef):
    message: str = Field(min_length=1, max_length=4000)
    previous: str | None = None


def _endpoint(account: str, project: str) -> str:
    proj = next((p for p in catalog().get("projects", [])
                 if p["name"] == project and p["account"] == account), None)
    if not proj:
        raise HTTPException(404, "Unknown project; refresh the catalog and try again")
    return proj["endpoint"]


def _demo() -> bool:
    return os.getenv("MARKETPLACE_DEMO") == "1"


@app.post("/api/agents/create")
def create_agent(a: NewAgent, user: auth.User = Depends(auth.require("Builder"))):
    if _demo():
        return {"ok": True, "demo": True, "name": a.name}
    c = catalog()
    endpoint = _endpoint(a.account, a.project)
    known = {m["target"]: m for m in c["mcp"] if m.get("project") == a.project and m.get("account") == a.account}
    unknown = [u for u in a.mcp if u not in known]
    if unknown:
        raise HTTPException(422, f"Unknown MCP server(s): {', '.join(unknown)}")
    if a.guardrail and not any(g["name"] == a.guardrail and g.get("account") == a.account
                               for g in c.get("guardrails", [])):
        raise HTTPException(422, f"Unknown guardrail: {a.guardrail}")
    tools = []
    for u in a.mcp:
        tool = {"type": "mcp", "server_label": re.sub(r"\W", "_", known[u]["name"]), "server_url": u, "require_approval": "never"}
        if known[u].get("source") == "connection":
            # Servers that need credentials are reached through their Foundry connection; without it the server answers 401
            tool["project_connection_id"] = known[u]["name"]
        tools.append(tool)
    in_project = [k for k in c["knowledge"] if k.get("project") == a.project and k.get("account") == a.account]
    indexes = {k["name"]: k for k in in_project if k.get("source") == "index" and k.get("target")}
    unknown = [n for n in a.knowledge if n not in indexes]
    if unknown:
        raise HTTPException(422, f"Unknown knowledge base(s): {', '.join(unknown)}")
    if a.knowledge:
        conn_ids = {k["name"]: k["id"] for k in in_project if k.get("source") == "connection"}
        tools.append({"type": "azure_ai_search", "azure_ai_search": {"indexes": [
            {"project_connection_id": conn_ids.get(indexes[n]["target"], indexes[n]["target"]),
             "index_name": n, "query_type": "simple", "top_k": 5} for n in a.knowledge]}})
    if a.keep_tools:
        old = next((x for x in c["agents"] if x["name"] == a.name and x.get("project") == a.project
                    and x.get("account") == a.account and x.get("generation") == "new"), None)
        old_defs = (old or {}).get("toolDefs", [])
        for t in tools:   # editing must not drop a connection the agent already used for the same server
            prior = next((d for d in old_defs if d.get("type") == "mcp" and d.get("server_url") == t.get("server_url")), None)
            if prior and prior.get("project_connection_id") and "project_connection_id" not in t:
                t["project_connection_id"] = prior["project_connection_id"]
        tools = [t for t in old_defs if t.get("type") not in ("mcp", "azure_ai_search")] + tools
    assessment = None
    if a.facts is not None or os.getenv("RISK_ENFORCE") == "1":
        assessment = _risk(c, AssessReq(account=a.account, project=a.project, description=a.description,
                                        instructions=a.instructions, mcp=a.mcp, knowledge=a.knowledge,
                                        guardrail=a.guardrail, facts=a.facts or {}))
        if assessment["blocked"]:
            audit.record("agent.create.blocked", user=user, agent=a.name, project=a.project, tier=assessment["tier"])
            raise HTTPException(403, "Risk tier is Critical: this agent needs review-board approval and is not created automatically.")
        if not assessment["guardrail"]["selectedOk"] and not (a.override_reason or "").strip():
            raise HTTPException(422, f"Risk tier is {assessment['tier']}: the selected guardrail is weaker than recommended. "
                                     "Choose a recommended guardrail, or give a reason to override.")
    from .discovery import Discovery
    try:
        # Foundry wants the policy's full ARM resource id here, not its name
        rail_id = next((g.get("id") or g["name"] for g in c.get("guardrails", [])
                        if g["name"] == a.guardrail and g.get("account") == a.account), None) if a.guardrail else None
        res = Discovery().create_agent(endpoint, a.name, a.model, a.instructions, a.description, tools, rail_id)
    except Exception as e:
        raise HTTPException(502, f"Create failed: {e}") from e
    _invalidate()  # make the next listing rescan so the new agent shows up
    audit.record("agent.create", user=user, agent=a.name, project=a.project, account=a.account, model=a.model, guardrail=a.guardrail,
                 mcp=a.mcp, knowledge=a.knowledge, version=res.get("version"),
                 tier=assessment and assessment["tier"], score=assessment and assessment["score"],
                 facts=assessment and assessment["facts"], override_reason=(a.override_reason or None))
    return {"ok": True, "name": a.name, "version": res.get("version"), "tier": assessment and assessment["tier"]}


@app.post("/api/agents/assess", dependencies=VIEWER)
def assess_agent(r: AssessReq):
    """Risk tier, evidence, questions, guardrail recommendation and controls for an agent as currently configured."""
    return _risk(catalog(), r)


@app.post("/api/agents/delete")
def delete_agent(a: AgentRef, user: auth.User = Depends(auth.require("Approver"))):   # until agents have owners, only Approvers delete
    if _demo():
        return {"ok": True, "demo": True}
    from .discovery import Discovery
    try:
        Discovery().delete_agent(_endpoint(a.account, a.project), a.name)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Delete failed: {e}") from e
    _invalidate()
    audit.record("agent.delete", user=user, agent=a.name, project=a.project, account=a.account)
    return {"ok": True}


@app.post("/api/agents/chat", dependencies=VIEWER)
def chat_agent(m: ChatMsg):
    if _demo():
        return {"text": f"(demo) {m.name} would answer: {m.message}", "id": None}
    from .discovery import Discovery
    try:
        return Discovery().chat(_endpoint(m.account, m.project), m.name, m.message, m.previous)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Chat failed: {e}") from e


@app.get("/api/accounts", dependencies=VIEWER)
def accounts():
    c = catalog()
    found = c.get("accounts") or [{"name": n} for n in sorted({d["account"] for d in c["deployments"]})]
    return [{"name": a["name"], "location": a.get("location")} for a in found]


def _account(name: str) -> dict:
    acc = next((a for a in catalog().get("accounts", []) if a["name"] == name), None)
    if not acc:
        raise HTTPException(404, "Unknown account; refresh the catalog and try again")
    return acc


CATEGORIES = ("Hate", "Sexual", "Violence", "Selfharm")
LEVELS = ("Low", "Medium", "High")


class NewGuardrail(BaseModel):
    account: str
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    base: str = "Microsoft.DefaultV2"
    thresholds: dict[str, str]   # category -> block at this severity and above


class TemplateGuardrail(BaseModel):
    account: str
    tier: str = Field(pattern="^(Medium|High|Critical)$")   # Low uses the built-in default policy


@app.post("/api/guardrails/create-template")
def create_guardrail_from_template(g: TemplateGuardrail, user: auth.User = Depends(auth.require("Builder"))):
    """Create the recommended content filter for a risk tier under a fresh name like hub-high-v1."""
    taken = {x["name"] for x in catalog().get("guardrails", []) if x.get("account") == g.account}
    name = risk._unused_name(g.tier, taken)
    if _demo():
        return {"ok": True, "demo": True, "name": name}
    acc = _account(g.account)
    from .discovery import Discovery
    try:
        Discovery().create_guardrail_filters(acc["id"], name, "Microsoft.DefaultV2", risk.TEMPLATES[g.tier])
    except Exception as e:
        raise HTTPException(502, f"Create failed: {e}") from e
    _invalidate()
    audit.record("guardrail.create", user=user, account=g.account, name=name, tier=g.tier, source="template")
    return {"ok": True, "name": name}


@app.post("/api/guardrails/create")
def create_guardrail(g: NewGuardrail, user: auth.User = Depends(auth.require("Approver"))):
    bad = [k for k, v in g.thresholds.items() if k not in CATEGORIES or v not in LEVELS]
    if bad or not g.thresholds:
        raise HTTPException(422, f"thresholds must map {CATEGORIES} to one of {LEVELS}")
    if _demo():
        return {"ok": True, "demo": True, "name": g.name}
    from .discovery import Discovery
    try:
        Discovery().create_guardrail(_account(g.account)["id"], g.name, g.base, g.thresholds)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Create failed: {e}") from e
    _invalidate()
    audit.record("guardrail.create", user=user, account=g.account, name=g.name, thresholds=g.thresholds, source="form")
    return {"ok": True, "name": g.name}


class Turn(BaseModel):
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str = Field(max_length=20000)


class ModelChat(BaseModel):
    account: str
    deployment: str
    messages: list[Turn] = Field(min_length=1, max_length=60)
    temperature: float = Field(0.7, ge=0, le=2)


@app.post("/api/playground/chat", dependencies=VIEWER)
def playground_chat(m: ModelChat):
    if _demo():
        return {"text": f"(demo) {m.deployment} would reply to: {m.messages[-1].content}", "finish": "stop"}
    c = catalog()
    if not any(d["name"] == m.deployment and d["account"] == m.account for d in c["deployments"]):
        raise HTTPException(404, "Unknown deployment; refresh the catalog and try again")
    endpoint = _account(m.account).get("openai")
    if not endpoint:
        raise HTTPException(422, "This account has no custom subdomain, so it can't be called with Entra ID")
    from .discovery import Discovery
    try:
        return Discovery().model_chat(endpoint, m.deployment, [t.model_dump() for t in m.messages], m.temperature)
    except Exception as e:  # content-filter blocks arrive here as a 400 with code "content_filter"
        raise HTTPException(502, f"Model call failed: {e}") from e


PLANNER_AGENT = os.getenv("PLANNER_AGENT", "agent-hub-planner")
PLANNER_INSTRUCTIONS = ("You are the planner behind Agent Hub's plain-English features. Each message contains a [SYSTEM] block "
                        "with the task and rules and a [USER] block with the request and the allowed items. Follow the "
                        "[SYSTEM] rules exactly, use only the items listed, and reply with a single JSON object and nothing else.")
_planner_state: dict = {"ref": None, "failed": False}


def _planner_agent(c: dict) -> tuple[str, str] | None:
    """(project endpoint, agent name) of the planner agent; creates it once if missing (PLANNER_AUTOCREATE=0 to forbid)."""
    if _planner_state["ref"]:
        return _planner_state["ref"]
    projects = c.get("projects", [])
    for a in c.get("agents", []):
        if a["name"] == PLANNER_AGENT and a.get("generation") == "new":
            p = next((p for p in projects if p["name"] == a.get("project") and p["account"] == a.get("account")), None)
            if p:
                _planner_state["ref"] = (p["endpoint"], PLANNER_AGENT)
                return _planner_state["ref"]
    if _planner_state["failed"] or os.getenv("PLANNER_AUTOCREATE") == "0":
        return None
    from .discovery import Discovery
    for p in projects:  # first project whose account has a chat model
        models = [d["name"] for d in c["deployments"]
                  if d["account"] == p["account"] and not re.search("embed", d["name"] + (d.get("model") or ""), re.I)]
        if not models:
            continue
        try:
            Discovery().create_agent(p["endpoint"], PLANNER_AGENT, next((m for m in models if "gpt" in m.lower()), models[0]),
                                     PLANNER_INSTRUCTIONS, "Used by Agent Hub for plain-English search and agent drafting. Safe to delete; it is recreated on demand.")
            _planner_state["ref"] = (p["endpoint"], PLANNER_AGENT)
            _invalidate()
            return _planner_state["ref"]
        except Exception:
            continue
    _planner_state["failed"] = True   # don't retry on every request
    return None


def _planner():
    """A function that sends chat messages to the planner model and returns its JSON text, or None.

    PLANNER_DEPLOYMENT (and optionally PLANNER_ACCOUNT) pick the model; otherwise the first chat
    deployment in an account with an Azure OpenAI endpoint is used. The call runs in the customer's own
    Foundry account. Set NL_FEATURES=0 to turn the AI step off and use keyword matching only.
    """
    if _demo() or os.getenv("NL_FEATURES") == "0":
        return None
    c = catalog()
    want, acct = os.getenv("PLANNER_DEPLOYMENT"), os.getenv("PLANNER_ACCOUNT")
    if not want:  # default: run the planner as a Foundry agent, which needs only the project role
        ref = _planner_agent(c)
        if ref:
            from .discovery import Discovery
            disc = Discovery()
            return lambda msgs: disc.chat(ref[0], ref[1], "\n\n".join(
                f"[{m['role'].upper()}]\n{m['content']}" for m in msgs))["text"]
    for d in c["deployments"]:
        if re.search("embed", d["name"] + (d.get("model") or ""), re.I) or (want and d["name"] != want) \
                or (acct and d["account"] != acct):
            continue
        endpoint = next((a.get("openai") for a in c.get("accounts", []) if a["name"] == d["account"]), None)
        if endpoint:
            from .discovery import Discovery
            disc = Discovery()
            return lambda msgs: disc.model_chat(endpoint, d["name"], msgs, 0.2, json_mode=True)["text"]
    return None


class Ask(BaseModel):
    query: str = Field(min_length=3, max_length=500)


class DraftReq(Ask):
    account: str
    project: str


@app.post("/api/discover", dependencies=VIEWER)
def discover(a: Ask):
    """Natural-language search over agents, models, MCP servers, knowledge bases and guardrails."""
    return nl.discover(catalog(), a.query, _planner())


@app.post("/api/agents/draft", dependencies=VIEWER)
def draft_agent(a: DraftReq):
    """Propose an agent from a description. Nothing is created; the UI pre-fills the form for review."""
    return nl.draft(catalog(), a.query, a.account, a.project, _planner())


_evals = evals.EvalStore(
    None if _demo_mode or os.getenv("EVALS_FILE") == "off"
    else Path(os.getenv("EVALS_FILE") or Path(__file__).parent.parent / ".cache" / "evals.json"))


def _eval_store() -> evals.EvalStore:
    if _demo():
        evals.seed_demo(_evals, catalog()["agents"])   # a little history so the page is not empty in demo mode
    return _evals


def _managed_agent(account: str, project: str, name: str) -> dict:
    a = next((x for x in catalog().get("agents", []) if x["name"] == name and x.get("project") == project
              and x.get("account") == account and x.get("generation") == "new"), None)
    if not a:
        raise HTTPException(404, "Unknown agent, or it is a classic assistant that cannot be evaluated here")
    return a


def _slim(run: dict) -> dict:
    return {k: v for k, v in run.items() if k != "results"}


class EvalRef(BaseModel):
    """Names are looked up in the catalog, so only a length limit is needed (sample agents have spaces in their names)."""
    project: str = Field(max_length=100)
    account: str = Field(max_length=100)
    name: str = Field(min_length=1, max_length=100)


class SuiteReq(EvalRef):
    cases: list[dict] = Field(max_length=evals.MAX_CASES)


@app.get("/api/evals/latest", dependencies=VIEWER)
def evals_latest():
    """Newest finished run per agent: pass rate, gate and time. Keys are account/project/name."""
    return _eval_store().latest()


@app.get("/api/evals/suite", dependencies=VIEWER)
def evals_suite(account: str, project: str, name: str):
    """The agent's saved test set, or a starter set (not saved until you save or run it)."""
    agent = _managed_agent(account, project, name)
    saved = _eval_store().suite(evals.agent_key(account, project, name))
    if saved is not None:
        return {"cases": saved, "isDefault": False, "threshold": evals.threshold()}
    return {"cases": evals.default_cases(agent, _planner(), _agent_facts(agent)), "isDefault": True, "threshold": evals.threshold()}


@app.put("/api/evals/suite")
def evals_save_suite(s: SuiteReq, user: auth.User = Depends(auth.require("Builder"))):
    _managed_agent(s.account, s.project, s.name)
    try:
        cases = evals.clean_cases(s.cases)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if not cases:
        raise HTTPException(422, "A test set needs at least one case.")
    _eval_store().set_suite(evals.agent_key(s.account, s.project, s.name), cases)
    audit.record("eval.suite.save", user=user, agent=s.name, project=s.project, cases=len(cases))
    return {"ok": True, "cases": cases}


def _agent_facts(agent: dict) -> dict:
    """What this agent handles and can do, using the same rubric as the risk profile (unknowns are assumed cautiously)."""
    mcp_urls = [t["server_url"] for t in agent.get("toolDefs", []) if t.get("type") == "mcp" and t.get("server_url")]
    return risk.assess({}, f"{agent.get('description', '')}\n{agent.get('instructions', '')}", mcp_urls,
                       agent.get("guardrail"), _rails(catalog(), agent.get("account", "")))["facts"]


def _start_run(a: EvalRef, user: auth.User, agent: dict, llm) -> dict:
    """Start a background run of the agent's saved test set (creating the starter set first if there is none)."""
    store = _eval_store()
    key = evals.agent_key(a.account, a.project, a.name)
    if store.has_running(key):
        raise HTTPException(409, "An evaluation of this agent is already running.")
    cases = store.suite(key)
    if not cases:
        cases = evals.default_cases(agent, llm, _agent_facts(agent))
        store.set_suite(key, cases)   # running the starter set saves it, so the next run tests the same things
    if _demo():
        chat = evals.demo_chat
    else:
        from .discovery import Discovery
        disc, endpoint = Discovery(), _endpoint(a.account, a.project)
        chat = lambda prompt: disc.chat(endpoint, a.name, prompt)["text"]   # noqa: E731  one fresh turn per case
    run = evals.new_run({"account": a.account, "project": a.project, "name": a.name}, cases, user.email or user.name)
    store.add_run(run)
    started = _slim(dict(run))   # snapshot now: the background thread starts updating the stored run immediately
    threading.Thread(target=evals.execute, args=(store, run, cases, chat, llm), daemon=True, name="eval-run").start()
    audit.record("eval.run", user=user, agent=a.name, project=a.project, run=run["id"], cases=len(cases))
    return started


@app.post("/api/evals/run")
def evals_run(a: EvalRef, user: auth.User = Depends(auth.require("Builder"))):
    """Start an evaluation in the background; poll GET /api/evals/runs/{id} for progress and results."""
    return _start_run(a, user, _managed_agent(a.account, a.project, a.name), _planner())


class CreateEval(EvalRef):
    run: bool = True


@app.post("/api/evals/create")
def evals_create(a: CreateEval, user: auth.User = Depends(auth.require("Builder"))):
    """Set up an evaluation for an agent that has none: build a test set from what the agent does and (optionally) run it.

    An existing test set is never overwritten. Returns the test set, whether it was newly created, and the run if one started.
    """
    agent = _managed_agent(a.account, a.project, a.name)
    store = _eval_store()
    key = evals.agent_key(a.account, a.project, a.name)
    llm = _planner()
    created = store.suite(key) is None
    if created:
        store.set_suite(key, evals.default_cases(agent, llm, _agent_facts(agent)))
        audit.record("eval.create", user=user, agent=a.name, project=a.project, cases=len(store.suite(key) or []))
    return {"created": created, "cases": store.suite(key), "run": _start_run(a, user, agent, llm) if a.run else None}


@app.post("/api/evals/suggest")
def evals_suggest(a: EvalRef, user: auth.User = Depends(auth.require("Builder"))):
    """Checks the agent's current test set is missing (for example extra safety probes if it handles personal data)."""
    agent = _managed_agent(a.account, a.project, a.name)
    have = {c["prompt"] for c in _eval_store().suite(evals.agent_key(a.account, a.project, a.name)) or []}
    return {"cases": evals.suggest_cases(agent, _planner(), _agent_facts(agent), have)}


@app.get("/api/evals/runs", dependencies=VIEWER)
def evals_runs(account: str, project: str, name: str):
    return [_slim(r) for r in _eval_store().runs(evals.agent_key(account, project, name))]


@app.get("/api/evals/runs/{run_id}", dependencies=VIEWER)
def evals_run_detail(run_id: str):
    r = _eval_store().run(run_id)
    if not r:
        raise HTTPException(404, "No such run")
    return r


@app.get("/api/portfolio", dependencies=VIEWER)
def portfolio_view():
    """Governance numbers for leadership; each attention item names the list filter that shows its agents."""
    return portfolio.compute(catalog(), {PLANNER_AGENT}, evals=_eval_store().latest())


@app.get("/api/{kind}", dependencies=VIEWER)
def list_items(kind: str, q: str = "", project: str = Query("", description="filter by project name"),
               account: str = "", filter: str = "", system: bool = False):
    if kind not in KINDS:
        raise HTTPException(404, f"kind must be one of {KINDS}")
    c = catalog()
    items = c.get(kind, [])
    if kind == "agents":   # tag the app's own helper agent and hide it unless asked for
        latest = _eval_store().latest()
        items = [{**a, "system": a["name"] == PLANNER_AGENT,
                  "eval": latest.get(evals.agent_key(a.get("account"), a.get("project"), a["name"]))} for a in items]
        if not system:
            items = [a for a in items if not a["system"]]
        if filter:
            keep = {id(a) for a in portfolio.agent_filter(c, items, filter, evals=latest)}
            items = [a for a in items if id(a) in keep]
    if project and kind != "deployments":  # deployments belong to the account, not a project
        items = [i for i in items if i.get("project") == project]
    if account:
        items = [i for i in items if i.get("account") == account]
    if q:
        ql = q.lower()
        items = [i for i in items if ql in " ".join(map(str, i.values())).lower()]
    return items


@app.get("/")
def index():
    # The React build (frontend/dist, from `npm run build`) wins; the older single-file page is the fallback.
    built = DIST / "index.html"
    return FileResponse(built if built.exists() else STATIC / "index.html",
                        headers={"Cache-Control": "no-cache"})   # index.html must always be revalidated; assets are hashed


if (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
