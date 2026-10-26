"""Discovers agents, model deployments, MCP servers and knowledge bases across
every Azure AI Foundry project the signed-in identity can reach.

Control plane (ARM):   subscriptions -> AIServices accounts -> projects, deployments, connections
Data plane (project):  agents (new + classic), indexes
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor

import requests
from azure.identity import AzureCliCredential, DefaultAzureCredential

log = logging.getLogger("marketplace")

ARM = "https://management.azure.com"
ARM_SCOPE = "https://management.azure.com/.default"
FOUNDRY_SCOPE = "https://ai.azure.com/.default"
CS_API = "2025-06-01"

KNOWLEDGE_CATEGORIES = {"CognitiveSearch", "AzureAISearch", "AzureBlob"}
MCP_CATEGORIES = {"RemoteTool", "MCP", "RemoteA2A"}


class Discovery:
    def __init__(self) -> None:
        # In "az login" mode the app acts as exactly the account that ran `az login`, the same one shown in the header.
        from . import auth
        self.cred = AzureCliCredential() if auth.mode() == "azcli" else DefaultAzureCredential()
        self.http = requests.Session()
        self.errors: list[str] = []

    # ---- plumbing -------------------------------------------------------
    def _get(self, url: str, scope: str, params: dict | None = None) -> dict:
        token = self.cred.get_token(scope).token
        r = self.http.get(url, headers={"Authorization": f"Bearer {token}"}, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def _list(self, url: str, scope: str, params: dict | None = None) -> list[dict]:
        out: list[dict] = []
        while url:
            data = self._get(url, scope, params)
            out += data.get("value") or data.get("data") or []
            url, params = data.get("nextLink"), None
        return out

    def _safe(self, fn, *a, default=None):
        try:
            return fn(*a)
        except Exception as e:  # one broken project must not break the catalog
            log.warning("%s failed: %s", getattr(fn, "__name__", fn), e)
            self.errors.append(f"{getattr(fn, '__name__', fn)}: {str(e)[:200]}")
            return default if default is not None else []

    # ---- control plane --------------------------------------------------
    def subscriptions(self) -> list[str]:
        configured = [s.strip() for s in os.getenv("AZURE_SUBSCRIPTION_IDS", "").split(",") if s.strip()]
        if configured:
            return configured
        subs = self._list(f"{ARM}/subscriptions", ARM_SCOPE, {"api-version": "2022-12-01"})
        return [s["subscriptionId"] for s in subs if s.get("state") == "Enabled"]

    def accounts(self, sub: str) -> list[dict]:
        accs = self._list(f"{ARM}/subscriptions/{sub}/providers/Microsoft.CognitiveServices/accounts",
                          ARM_SCOPE, {"api-version": CS_API})
        return [a for a in accs if a.get("kind") in ("AIServices", "OpenAI")]

    def projects(self, acc_id: str) -> list[dict]:
        return self._list(f"{ARM}{acc_id}/projects", ARM_SCOPE, {"api-version": CS_API})

    def deployments(self, acc_id: str) -> list[dict]:
        return self._list(f"{ARM}{acc_id}/deployments", ARM_SCOPE, {"api-version": CS_API})

    def guardrails(self, acc_id: str) -> list[dict]:
        """Content-filter (RAI) policies defined on the account: Microsoft built-ins and custom ones."""
        return self._list(f"{ARM}{acc_id}/raiPolicies", ARM_SCOPE, {"api-version": CS_API})

    def create_guardrail(self, acc_id: str, name: str, base: str, thresholds: dict[str, str]) -> dict:
        """Create a custom content filter. thresholds maps category -> Low|Medium|High, applied to prompts and completions."""
        filters = [{"name": cat, "severityThreshold": thr, "blocking": True, "enabled": True, "source": src}
                   for cat, thr in thresholds.items() for src in ("Prompt", "Completion")]
        return self.create_guardrail_filters(acc_id, name, base, filters)

    def create_guardrail_filters(self, acc_id: str, name: str, base: str, filters: list[dict]) -> dict:
        """Create a custom content filter from a full list of filters (harm categories, prompt shields, protected material)."""
        body = {"properties": {"basePolicyName": base, "mode": "Default", "contentFilters": filters}}
        token = self.cred.get_token(ARM_SCOPE).token
        r = self.http.put(f"{ARM}{acc_id}/raiPolicies/{name}", params={"api-version": CS_API}, json=body,
                          headers={"Authorization": f"Bearer {token}"}, timeout=60)
        if not r.ok:
            raise RuntimeError(f"{r.status_code}: {r.text[:300]}")
        return r.json()

    def model_chat(self, openai_endpoint: str, deployment: str, messages: list[dict], temperature: float,
                   json_mode: bool = False) -> dict:
        """Plain chat completion against a model deployment (no agent)."""
        token = self.cred.get_token("https://cognitiveservices.azure.com/.default").token
        body = {"model": deployment, "messages": messages, "temperature": temperature}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        r = self.http.post(f"{openai_endpoint}/openai/v1/chat/completions", timeout=120,
                           headers={"Authorization": f"Bearer {token}"}, json=body)
        if not r.ok:
            raise RuntimeError(f"{r.status_code}: {r.text[:400]}")
        ch = (r.json().get("choices") or [{}])[0]
        return {"text": (ch.get("message") or {}).get("content") or "", "finish": ch.get("finish_reason")}

    def connections(self, project_id: str) -> list[dict]:
        return self._list(f"{ARM}{project_id}/connections", ARM_SCOPE, {"api-version": CS_API})

    # ---- data plane -----------------------------------------------------
    @staticmethod
    def _endpoint(account: dict, project: str) -> str:
        host = account["properties"].get("endpoints", {}).get("AI Foundry API") \
            or f"https://{account['properties'].get('customSubDomainName', account['name'])}.services.ai.azure.com/"
        return f"{host.rstrip('/')}/api/projects/{project}"

    def agents(self, endpoint: str) -> list[dict]:
        found: list[dict] = []
        # New agent service
        for a in self._safe(self._list, f"{endpoint}/agents", FOUNDRY_SCOPE, {"api-version": "v1"}):
            v = (a.get("versions") or {}).get("latest") or {}
            d = v.get("definition") or {}
            found.append({"id": a.get("id") or a.get("name"), "name": a.get("name"),
                          "description": v.get("description") or a.get("description") or "",
                          "model": d.get("model"), "instructions": d.get("instructions") or "",
                          "tools": d.get("tools") or [], "created": v.get("created_at"),
                          "kind": d.get("kind") or "prompt", "generation": "new",
                          # stored as a full ARM id; show just the policy name so it matches the guardrail list
                          "guardrail": ((d.get("rai_config") or {}).get("rai_policy_name") or "").split("/")[-1] or None})
        # Classic (Assistants-style) agents
        for a in self._safe(self._list, f"{endpoint}/assistants", FOUNDRY_SCOPE, {"api-version": "v1"}):
            found.append({"id": a.get("id"), "name": a.get("name") or a.get("id"),
                          "description": a.get("description") or "", "model": a.get("model"),
                          "instructions": a.get("instructions") or "", "tools": a.get("tools") or [],
                          "tool_resources": a.get("tool_resources") or {}, "created": a.get("created_at"),
                          "kind": "classic", "generation": "classic"})
        return found

    def _call(self, method: str, url: str, json: dict | None = None, params: dict | None = None) -> dict:
        token = self.cred.get_token(FOUNDRY_SCOPE).token
        r = self.http.request(method, url, params=params, json=json, timeout=120,
                              headers={"Authorization": f"Bearer {token}"})
        if not r.ok:
            raise RuntimeError(f"{r.status_code}: {r.text[:300]}")
        return r.json() if r.content else {}

    def create_agent(self, endpoint: str, name: str, model: str, instructions: str, description: str = "",
                     tools: list[dict] | None = None, guardrail: str | None = None) -> dict:
        """Create a prompt agent (or a new version of it) in a Foundry project via the agents data plane."""
        definition = {"kind": "prompt", "model": model, "instructions": instructions}
        if tools:
            definition["tools"] = tools
        if guardrail:
            definition["rai_config"] = {"rai_policy_name": guardrail}
        return self._call("POST", f"{endpoint}/agents/{name}/versions", {"description": description,
                          "definition": definition}, {"api-version": "v1"})

    def delete_agent(self, endpoint: str, name: str) -> dict:
        return self._call("DELETE", f"{endpoint}/agents/{name}", params={"api-version": "v1"})

    def chat(self, endpoint: str, name: str, message: str, previous: str | None = None) -> dict:
        """One turn with a new-generation agent through the Responses API."""
        body = {"input": message, "agent_reference": {"type": "agent_reference", "name": name}}
        if previous:
            body["previous_response_id"] = previous
        res = self._call("POST", f"{endpoint}/openai/v1/responses", body)
        text = res.get("output_text") or "".join(
            c.get("text", "") for o in res.get("output", []) if o.get("type") == "message"
            for c in o.get("content", []) if c.get("type") == "output_text")
        return {"text": text or "(no text in response)", "id": res.get("id")}

    def indexes(self, endpoint: str) -> list[dict]:
        return self._list(f"{endpoint}/indexes", FOUNDRY_SCOPE, {"api-version": "v1"})

    # ---- assembly -------------------------------------------------------
    def _scan_project(self, sub: str, account: dict, proj: dict) -> dict:
        pname = proj["name"].split("/")[-1]
        rg = account["id"].split("/resourceGroups/")[1].split("/")[0]
        ctx = {"subscription": sub, "resourceGroup": rg, "account": account["name"],
               "project": pname, "location": account.get("location")}
        endpoint = self._endpoint(account, pname)
        portal = f"https://ai.azure.com/nextgen/?wsid={proj['id']}"
        out = {"agents": [], "mcp": [], "knowledge": []}

        conns = self._safe(self.connections, proj["id"])
        for c in conns:
            p = c.get("properties", {})
            cat = p.get("category", "")
            base = {**ctx, "id": c["id"], "name": c["name"], "category": cat,
                    "target": p.get("target"), "authType": p.get("authType"), "portalUrl": portal}
            if cat in MCP_CATEGORIES:
                out["mcp"].append({**base, "source": "connection"})
            elif cat in KNOWLEDGE_CATEGORIES:
                out["knowledge"].append({**base, "type": "Azure AI Search" if "Search" in cat else cat,
                                         "source": "connection"})

        for ix in self._safe(self.indexes, endpoint):
            out["knowledge"].append({**ctx, "id": f"{endpoint}/indexes/{ix.get('name')}", "name": ix.get("name"),
                                     "type": "Project index", "category": "Index", "target": ix.get("connectionName"),
                                     "version": ix.get("version"), "source": "index", "portalUrl": portal})

        seen_mcp = {m["target"] for m in out["mcp"] if m["target"]}
        for a in self._safe(self.agents, endpoint):
            tools = a.get("tools") or []
            mcp_urls, kb = [], []
            for t in tools:
                tt = t.get("type", "")
                if tt == "mcp":
                    url = t.get("server_url") or t.get("project_connection_id") or t.get("server_label")
                    mcp_urls.append(t.get("server_label") or url)
                    if t.get("server_url") and t["server_url"] not in seen_mcp:
                        seen_mcp.add(t["server_url"])
                        out["mcp"].append({**ctx, "id": t["server_url"], "name": t.get("server_label") or t["server_url"],
                                           "category": "MCP", "target": t["server_url"], "source": "agent-tool",
                                           "portalUrl": portal})
                elif tt in ("file_search", "azure_ai_search", "bing_grounding", "sharepoint_grounding", "fabric_dataagent"):
                    kb.append(tt)
            res = a.get("tool_resources") or {}
            kb += [f"vector_store:{v}" for v in (res.get("file_search") or {}).get("vector_store_ids", [])]
            out["agents"].append({**ctx, "id": a["id"], "name": a["name"], "description": a["description"],
                                  "model": a["model"], "instructions": a["instructions"], "toolDefs": [{k: v for k, v in t.items() if k not in ("headers", "authorization")} for t in tools],
                                  "kind": a["kind"], "generation": a["generation"], "created": a["created"],
                                  "guardrail": a.get("guardrail"),
                                  "tools": sorted({t.get("type", "?") for t in tools}),
                                  "mcpServers": mcp_urls, "knowledge": kb, "portalUrl": portal})
        return out

    def scan(self) -> dict:
        catalog = {"agents": [], "deployments": [], "mcp": [], "knowledge": [], "projects": [],
                   "guardrails": [], "accounts": [], "errors": []}
        jobs: list[tuple] = []
        for sub in self._safe(self.subscriptions):
            for acc in self._safe(self.accounts, sub):
                rg = acc["id"].split("/resourceGroups/")[1].split("/")[0]
                sub_domain = acc["properties"].get("customSubDomainName")
                catalog["accounts"].append({"name": acc["name"], "id": acc["id"], "subscription": sub,
                                            "resourceGroup": rg, "location": acc.get("location"),
                                            "openai": f"https://{sub_domain}.openai.azure.com" if sub_domain else None})
                deps = self._safe(self.deployments, acc["id"])
                for pol in self._safe(self.guardrails, acc["id"]):
                    p = pol.get("properties", {})
                    catalog["guardrails"].append({
                        "id": pol["id"], "name": pol["name"], "type": p.get("type"), "basePolicy": p.get("basePolicyName"),
                        "mode": p.get("mode"), "filters": p.get("contentFilters") or [],
                        "usedBy": [d["name"] for d in deps if d["properties"].get("raiPolicyName") == pol["name"]],
                        "subscription": sub, "resourceGroup": rg, "account": acc["name"], "location": acc.get("location")})
                for d in deps:
                    m = d["properties"].get("model", {})
                    catalog["deployments"].append({
                        "id": d["id"], "name": d["name"], "model": m.get("name"), "version": m.get("version"),
                        "publisher": m.get("format"), "sku": (d.get("sku") or {}).get("name"),
                        "capacity": (d.get("sku") or {}).get("capacity"),
                        "state": d["properties"].get("provisioningState"),
                        "guardrail": d["properties"].get("raiPolicyName"),
                        "subscription": sub, "resourceGroup": rg, "account": acc["name"],
                        "location": acc.get("location")})
                projs = self._safe(self.projects, acc["id"])
                if not projs:
                    self.errors.append(f"account {acc['name']} ({acc.get('kind')}): no Foundry projects returned")
                for proj in projs:
                    pname = proj["name"].split("/")[-1]
                    catalog["projects"].append({"name": pname, "account": acc["name"], "subscription": sub,
                                                "resourceGroup": rg, "endpoint": self._endpoint(acc, pname)})
                    jobs.append((sub, acc, proj))
        with ThreadPoolExecutor(max_workers=8) as pool:
            for res in pool.map(lambda j: self._safe(self._scan_project, *j, default={}), jobs):
                for k in ("agents", "mcp", "knowledge"):
                    catalog[k] += (res or {}).get(k, [])
        catalog["errors"] = self.errors
        return catalog
