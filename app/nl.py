"""Natural-language discovery and agent drafting over the catalog.

Everything here is grounded in the scanned catalog: the optional LLM step only re-ranks and explains
retrieved assets, or proposes an agent draft that is then validated against what actually exists.
Without a reachable chat model it falls back to plain keyword matching, so the features still work.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from typing import Callable

from . import risk

LLM = Callable[[list[dict]], str]   # takes chat messages, returns the model's JSON text

STOP = set("a an and are as at be by can do for from has have how i in is it its me my of on or our that the their "
           "this to us we what which who will with you your need want find agent agents help using use create make".split())
TYPES = ("agent", "model", "mcp", "knowledge", "guardrail")


def _tokens(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if w in STOP or len(w) < 2:
            continue
        for suf in ("ing", "es", "s", "ed"):
            if w.endswith(suf) and len(w) - len(suf) >= 3:
                w = w[: -len(suf)]
                break
        out.append(w)
    return out


def build_assets(c: dict) -> list[dict]:
    """One flat, searchable list over every kind of asset in the catalog."""
    a: list[dict] = []
    for x in c.get("agents", []):
        a.append({"type": "agent", "name": x["name"], "account": x.get("account"), "project": x.get("project"),
                  "text": f"{x['name']}. {x.get('description') or ''}. model {x.get('model') or ''}. "
                          f"tools {' '.join(x.get('tools') or [])}. {(x.get('instructions') or '')[:300]}",
                  "meta": {"model": x.get("model"), "generation": x.get("generation"), "guardrail": x.get("guardrail")}})
    for x in c.get("deployments", []):
        a.append({"type": "model", "name": x["name"], "account": x.get("account"), "project": None,
                  "text": f"{x['name']}. {x.get('publisher') or ''} {x.get('model') or ''} {x.get('version') or ''}. "
                          f"sku {x.get('sku') or ''}", "meta": {"guardrail": x.get("guardrail")}})
    for x in c.get("mcp", []):
        a.append({"type": "mcp", "name": x["name"], "account": x.get("account"), "project": x.get("project"),
                  "text": f"{x['name']}. {x.get('category') or ''} {x.get('target') or ''}", "meta": {"target": x.get("target")}})
    for x in c.get("knowledge", []):
        a.append({"type": "knowledge", "name": x["name"], "account": x.get("account"), "project": x.get("project"),
                  "text": f"{x['name']}. {x.get('type') or ''} {x.get('category') or ''} {x.get('target') or ''}",
                  "meta": {"source": x.get("source")}})
    for x in c.get("guardrails", []):
        lv = ", ".join(sorted({f"{f['name']} {f.get('severityThreshold')}" for f in x.get("filters", [])}))
        a.append({"type": "guardrail", "name": x["name"], "account": x.get("account"), "project": None,
                  "text": f"{x['name']}. content filter guardrail {x.get('type') or ''} {lv}", "meta": {}})
    return a


def rank(query: str, assets: list[dict], types: tuple[str, ...] = TYPES) -> list[dict]:
    """TF-IDF style keyword ranking; name matches count triple."""
    q = _tokens(query)
    pool = [x for x in assets if x["type"] in types]
    if not q or not pool:
        return []
    docs = [(Counter(_tokens(x["text"])), set(_tokens(x["name"]))) for x in pool]
    df = Counter(t for tf, _ in docs for t in tf)
    n = len(pool)
    scored = []
    for x, (tf, name_tokens) in zip(pool, docs):
        s = sum(math.log(1 + n / (1 + df[t])) * ((1 + math.log(tf[t])) if tf[t] else 0) * (3 if t in name_tokens else 1)
                for t in set(q))
        if s > 0:
            scored.append({**x, "score": round(s, 3)})
    return sorted(scored, key=lambda x: -x["score"])


def _json(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    return json.loads(m.group(0)) if m else {}


def _public(x: dict, reason: str) -> dict:
    return {"type": x["type"], "name": x["name"], "account": x.get("account"), "project": x.get("project"),
            "reason": reason, "score": x.get("score")}


def discover(c: dict, query: str, llm: LLM | None, limit: int = 8) -> dict:
    cands = rank(query, build_assets(c))[:15]
    note = None
    if llm and cands:
        listing = "\n".join(f"{i}. [{x['type']}] {x['name']} ({x.get('project') or x.get('account')}): {x['text'][:240]}"
                            for i, x in enumerate(cands))
        try:
            out = _json(llm([
                {"role": "system", "content": "You match a user's need to catalog assets. Use ONLY the numbered candidates. "
                 "Return JSON {\"results\":[{\"i\":<number>,\"reason\":\"<one short sentence why it fits>\"}]} with at most "
                 f"{limit} items, best first, omitting candidates that do not fit."},
                {"role": "user", "content": f"Need: {query}\n\nCandidates:\n{listing}"}]))
            res = [_public(cands[r["i"]], str(r.get("reason", ""))[:200]) for r in out.get("results", [])
                   if isinstance(r.get("i"), int) and 0 <= r["i"] < len(cands)]
            if res:
                return {"mode": "ai", "results": res[:limit]}
        except Exception as e:  # fall back to keyword results, but say so
            note = f"AI ranking unavailable ({str(e)[:120]}); showing keyword matches."
    return {"mode": "keyword", "note": note, "results": [_public(x, "Matches your words in its name or description.")
                                                         for x in cands[:limit]]}


def _slug(text: str) -> str:
    words = _tokens(text)[:3] or ["new-agent"]
    return re.sub(r"[^A-Za-z0-9-]", "", "-".join(words))[:60] or "new-agent"


def draft(c: dict, query: str, account: str, project: str, llm: LLM | None) -> dict:
    """Propose an agent spec from a description, restricted to assets in this project/account."""
    assets = build_assets(c)
    models = [x for x in assets if x["type"] == "model" and x["account"] == account and not re.search("embed", x["name"], re.I)]
    mcp = [x for x in assets if x["type"] == "mcp" and x["account"] == account and x["project"] == project]
    kb = [x for x in c.get("knowledge", []) if x.get("account") == account and x.get("project") == project
          and x.get("source") == "index" and x.get("target")]
    rails = [x["name"] for x in c.get("guardrails", []) if x.get("account") == account]
    if not models:
        return {"mode": "none", "note": "This account has no chat model deployments to build on.", "draft": None, "missing": []}

    top_mcp = rank(query, mcp)
    kb_assets = [x for x in assets if x["type"] == "knowledge" and x["account"] == account and x["project"] == project
                 and x["name"] in {k["name"] for k in kb}]
    top_kb = rank(query, kb_assets)
    draft_ = {"name": _slug(query), "description": query.strip()[:300],
              "instructions": f"You are an assistant. Your job: {query.strip()}\nBe accurate and concise. "
                              "If you are unsure, say so instead of guessing.",
              "model": models[0]["name"], "mcp": [x["meta"]["target"] for x in top_mcp[:2] if x["meta"].get("target")],
              "knowledge": [x["name"] for x in top_kb[:2]],
              "guardrail": "Microsoft.DefaultV2" if "Microsoft.DefaultV2" in rails else None}
    reasons = {x["meta"]["target"]: "Matches your description" for x in top_mcp[:2] if x["meta"].get("target")}
    reasons.update({x["name"]: "Matches your description" for x in top_kb[:2]})
    missing: list[str] = []
    facts = risk.facts_from_text(query)   # the planner may add to these; unknown facts become questions later
    mode, note = "keyword", None

    if llm:
        def lst(xs): return "\n".join(f"- {x}" for x in xs) or "(none)"
        try:
            out = _json(llm([
                {"role": "system", "content": "You design an AI agent from a description. Choose ONLY from the allowed lists. "
                 "Return JSON: {\"name\":\"kebab-case\",\"description\":\"...\",\"instructions\":\"clear, specific system prompt\","
                 "\"model\":\"<allowed model>\",\"mcp\":[\"<allowed url>\"],\"knowledge\":[\"<allowed index>\"],"
                 "\"guardrail\":\"<allowed or null>\",\"reasons\":{\"<chosen item>\":\"why\"},"
                 "\"missing\":[\"capability the user needs that no allowed item provides\"],"
                 "\"risk_facts\":{\"audience\":\"staff|customers|public|null\",\"data\":\"none|internal|confidential|personal|regulated|null\","
                 "\"actions\":\"read_only|writes|null\",\"domain\":\"general|hr|financial|legal|medical|eligibility|null\","
                 "\"human_review\":\"yes|no|null\",\"web_grounding\":true}}. Use as few tools as needed. For risk_facts use null "
                 "whenever the description does not clearly say; never guess."},
                {"role": "user", "content": f"Description: {query}\n\nAllowed models:\n{lst(m['name'] for m in models)}\n\n"
                 f"Allowed MCP servers (url - name):\n{lst(f'{x['meta']['target']} - {x['name']}' for x in mcp)}\n\n"
                 f"Allowed knowledge indexes:\n{lst(k['name'] + ': ' + (k.get('type') or '') for k in kb)}\n\n"
                 f"Allowed guardrails:\n{lst(rails)}"}]))
            draft_.update({k: out[k] for k in ("description", "instructions") if isinstance(out.get(k), str) and out[k].strip()})
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,62}", str(out.get("name", ""))):
                draft_["name"] = out["name"]
            if out.get("model") in {m["name"] for m in models}:
                draft_["model"] = out["model"]
            allowed_urls = {x["meta"]["target"] for x in mcp}
            draft_["mcp"] = [u for u in out.get("mcp", []) if u in allowed_urls]
            draft_["knowledge"] = [k for k in out.get("knowledge", []) if k in {x["name"] for x in kb}]
            draft_["guardrail"] = out.get("guardrail") if out.get("guardrail") in rails else draft_["guardrail"]
            reasons = {k: str(v)[:160] for k, v in (out.get("reasons") or {}).items()}
            missing = [str(m)[:160] for m in out.get("missing", [])][:5]
            for k, v in (out.get("risk_facts") or {}).items():   # keep only values the rubric understands
                if k in risk.QUESTIONS and v in risk.QUESTIONS[k][1]:
                    facts[k] = v
                elif k == "web_grounding" and v is True:
                    facts[k] = True
            mode = "ai"
        except Exception as e:
            note = f"AI drafting unavailable ({str(e)[:120]}); built a basic draft from keyword matches."
    return {"mode": mode, "note": note, "draft": draft_, "reasons": reasons, "missing": missing, "facts": facts}
