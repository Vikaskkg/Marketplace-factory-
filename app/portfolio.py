"""Portfolio view: governance numbers for leadership, computed from the cached catalog.

Every figure comes with a filter name that `agent_filter` understands, so the number on the dashboard and the list
behind it can never disagree. The app's own helper agent (the planner) is excluded: it is not a business agent.
"""
from __future__ import annotations

import os
import time
from collections import Counter
from urllib.parse import urlparse

AGENT_FILTERS = ("no-guardrail", "stale", "no-description", "classic", "external-tools", "no-eval", "failing-eval")


def _key(a: dict) -> str:
    return f"{a.get('account')}/{a.get('project')}/{a.get('name')}"


def stale_days() -> int:
    try:
        return int(os.getenv("STALE_DAYS", "90"))
    except ValueError:
        return 90


def _external_urls(c: dict) -> set[str]:
    corp = [d.strip().lower() for d in os.getenv("CORP_DOMAINS", "").split(",") if d.strip()]
    if not corp:
        return set()   # without a corporate domain list nothing can be called external
    out = set()
    for m in c.get("mcp", []):
        host = (urlparse(m.get("target") or "").hostname or "").lower()
        if host and not any(host == d or host.endswith("." + d) for d in corp):
            out.add(m["target"])
    return out


def agent_filter(c: dict, agents: list[dict], name: str, now: float | None = None, evals: dict | None = None) -> list[dict]:
    """Agents matching one named condition. Unknown names match nothing, so a typo never shows everything.

    `evals` maps agent key (account/project/name) to its latest finished evaluation (see evals.EvalStore.latest).
    """
    now = now or time.time()
    evals = evals or {}
    if name == "no-eval":           # only new-generation agents can be evaluated through chat
        return [a for a in agents if a.get("generation") == "new" and _key(a) not in evals]
    if name == "failing-eval":
        return [a for a in agents if evals.get(_key(a), {}).get("gate") == "fail"]
    if name == "no-guardrail":      # only new-generation agents can carry a dedicated guardrail
        return [a for a in agents if a.get("generation") == "new" and not a.get("guardrail")]
    if name == "stale":
        cutoff = now - stale_days() * 86400
        return [a for a in agents if a.get("created") and a["created"] < cutoff]
    if name == "no-description":
        return [a for a in agents if not (a.get("description") or "").strip()]
    if name == "classic":
        return [a for a in agents if a.get("generation") == "classic"]
    if name == "external-tools":
        ext = _external_urls(c)
        return [a for a in agents if any(t.get("server_url") in ext for t in a.get("toolDefs", []))]
    return []


def compute(c: dict, system_names: set[str], now: float | None = None, evals: dict | None = None) -> dict:
    now = now or time.time()
    evals = evals or {}
    agents = [a for a in c.get("agents", []) if a["name"] not in system_names]
    managed = [a for a in agents if a.get("generation") == "new"]
    guarded = [a for a in managed if a.get("guardrail")]
    models = Counter(a.get("model") or "unknown" for a in agents)
    rails = Counter(a["guardrail"] for a in guarded)

    def item(a: dict) -> dict:
        return {"name": a["name"], "project": a.get("project"), "account": a.get("account")}

    attention = []
    for key, severity, title in (
        ("failing-eval", "warn", "Agents that failed their latest evaluation"),
        ("no-guardrail", "warn", "Agents without a dedicated guardrail (only the model's default filter applies)"),
        ("no-eval", "info", "Agents that have never been evaluated"),
        ("external-tools", "warn", "Agents using MCP servers outside your corporate domains"),
        ("stale", "info", f"Agents not updated in {stale_days()} days"),
        ("no-description", "info", "Agents with no description"),
        ("classic", "info", "Classic assistants (cannot carry a dedicated guardrail)"),
    ):
        hits = agent_filter(c, agents, key, now, evals)
        if hits:
            attention.append({"filter": key, "severity": severity, "title": title, "count": len(hits),
                              "examples": [item(a) for a in hits[:3]]})
    errors = c.get("errors", [])
    if errors:
        attention.append({"filter": None, "severity": "warn", "title": "The last scan reported problems",
                          "count": len(errors), "examples": [{"name": e[:140]} for e in errors[:3]]})

    return {
        # sample data has no project list, so fall back to the projects its agents belong to
        "kpis": {"agents": len(agents),
                 "projects": len(c.get("projects") or {a.get("project") for a in agents if a.get("project")}),
                 "models": len(c.get("deployments", [])),
                 "mcp": len(c.get("mcp", [])), "knowledge": len(c.get("knowledge", [])), "guardrails": len(c.get("guardrails", []))},
        "governance": {"managedAgents": len(managed), "withGuardrail": len(guarded),
                       "withoutGuardrail": len(managed) - len(guarded),
                       "coveragePct": round(100 * len(guarded) / len(managed)) if managed else None,
                       "classicAgents": len(agents) - len(managed),
                       "evaluated": sum(1 for a in managed if _key(a) in evals),
                       "evalsPassing": sum(1 for a in managed if evals.get(_key(a), {}).get("gate") == "pass"),
                       "evalsFailing": sum(1 for a in managed if evals.get(_key(a), {}).get("gate") == "fail")},
        "byModel": models.most_common(6),
        "byGuardrail": rails.most_common(6),
        "attention": attention,
        "staleDays": stale_days(),
        "corpDomainsSet": bool(os.getenv("CORP_DOMAINS")),
    }
