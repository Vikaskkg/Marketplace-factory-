"""Demo catalog so the UI works without Azure access (MARKETPLACE_DEMO=1)."""

def _ctx(sub, rg, acc, proj=None):
    return {"subscription": sub, "resourceGroup": rg, "account": acc, "project": proj, "location": "eastus2"}

HR = _ctx("demo-sub-prod", "rg-hr", "foundry-hr", "hr-assistant")
FIN = _ctx("demo-sub-prod", "rg-fin", "foundry-finance", "finance-ops")
ENG = _ctx("demo-sub-dev", "rg-eng", "foundry-eng", "devex")

DEMO = {
    "agents": [
        {**HR, "id": "asst_hr_1", "name": "Benefits Advisor", "description": "Answers employee benefits questions from policy docs.",
         "model": "gpt-4o", "kind": "prompt", "generation": "new", "tools": ["azure_ai_search"], "mcpServers": [],
         "knowledge": ["azure_ai_search"], "created": 1760000000, "portalUrl": "https://ai.azure.com"},
        {**FIN, "id": "asst_fin_1", "name": "Invoice Triage", "description": "Classifies and routes supplier invoices.",
         "model": "gpt-4.1", "kind": "prompt", "generation": "new", "tools": ["mcp", "file_search"],
         "mcpServers": ["erp-mcp"], "knowledge": ["file_search"], "created": 1760500000, "portalUrl": "https://ai.azure.com"},
        {**ENG, "id": "asst_eng_1", "name": "Code Reviewer", "description": "Reviews pull requests via GitHub MCP.",
         "model": "gpt-5", "kind": "prompt", "generation": "new", "tools": ["mcp", "code_interpreter"],
         "mcpServers": ["github-mcp"], "knowledge": [], "created": 1761000000, "portalUrl": "https://ai.azure.com"},
        {**ENG, "id": "asst_eng_2", "name": "Docs Helper", "description": "Searches internal engineering docs.",
         "model": "gpt-4o-mini", "kind": "classic", "generation": "classic", "tools": ["file_search"],
         "mcpServers": [], "knowledge": ["vector_store:vs_eng_docs"], "created": 1759000000, "portalUrl": "https://ai.azure.com"},
    ],
    "deployments": [
        {**_ctx("demo-sub-prod", "rg-hr", "foundry-hr"), "id": "d1", "name": "gpt-4o", "model": "gpt-4o", "version": "2024-11-20",
         "publisher": "OpenAI", "sku": "GlobalStandard", "capacity": 100, "state": "Succeeded"},
        {**_ctx("demo-sub-prod", "rg-fin", "foundry-finance"), "id": "d2", "name": "gpt-4.1", "model": "gpt-4.1", "version": "2025-04-14",
         "publisher": "OpenAI", "sku": "GlobalStandard", "capacity": 50, "state": "Succeeded"},
        {**_ctx("demo-sub-dev", "rg-eng", "foundry-eng"), "id": "d3", "name": "gpt-5", "model": "gpt-5", "version": "2025-08-07",
         "publisher": "OpenAI", "sku": "GlobalStandard", "capacity": 30, "state": "Succeeded"},
        {**_ctx("demo-sub-dev", "rg-eng", "foundry-eng"), "id": "d4", "name": "text-embedding-3-large", "model": "text-embedding-3-large",
         "version": "1", "publisher": "OpenAI", "sku": "Standard", "capacity": 120, "state": "Succeeded"},
    ],
    "mcp": [
        {**FIN, "id": "m1", "name": "erp-mcp", "category": "RemoteTool", "target": "https://erp.contoso.com/mcp",
         "authType": "CustomKeys", "source": "connection", "portalUrl": "https://ai.azure.com"},
        {**ENG, "id": "m2", "name": "github-mcp", "category": "MCP", "target": "https://api.githubcopilot.com/mcp/",
         "authType": "OAuth2", "source": "agent-tool", "portalUrl": "https://ai.azure.com"},
    ],
    "knowledge": [
        {**HR, "id": "k1", "name": "hr-policies-index", "type": "Azure AI Search", "category": "CognitiveSearch",
         "target": "https://contoso-search.search.windows.net", "source": "connection", "portalUrl": "https://ai.azure.com"},
        {**ENG, "id": "k2", "name": "eng-docs", "type": "Project index", "category": "Index", "target": "eng-search", "version": "3",
         "source": "index", "portalUrl": "https://ai.azure.com"},
    ],
    "guardrails": [
        {**ENG, "id": "g1", "name": "Microsoft.DefaultV2", "type": "SystemManaged", "basePolicy": None, "mode": "Default",
         "usedBy": ["gpt-5"], "filters": [{"name": c, "source": s, "severityThreshold": "Medium", "blocking": True, "enabled": True}
                                          for c in ("Hate", "Sexual", "Violence", "Selfharm") for s in ("Prompt", "Completion")]},
        {**ENG, "id": "g2", "name": "strict-internal", "type": "UserManaged", "basePolicy": "Microsoft.DefaultV2", "mode": "Default",
         "usedBy": [], "filters": [{"name": c, "source": s, "severityThreshold": "Low", "blocking": True, "enabled": True}
                                   for c in ("Hate", "Sexual", "Violence", "Selfharm") for s in ("Prompt", "Completion")]},
    ],
    "errors": [],
}
