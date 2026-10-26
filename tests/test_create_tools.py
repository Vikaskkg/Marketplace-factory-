"""How the Agent Factory builds tool definitions, and how evaluation errors are explained."""
import os
import sys
from pathlib import Path

os.environ["MARKETPLACE_DEMO"] = "1"
os.environ["AUDIT_FILE"] = "off"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

import app.discovery as discovery  # noqa: E402
from app import evals, main  # noqa: E402

CAT = {
    "mcp": [{"name": "FoundryMCPServer", "target": "https://mcp.ai.azure.com", "project": "p", "account": "a", "source": "connection"},
            {"name": "gh", "target": "https://x.example/mcp", "project": "p", "account": "a", "source": "agent-tool"}],
    "knowledge": [], "guardrails": [], "deployments": [], "accounts": [],
    "agents": [{"name": "bot", "project": "p", "account": "a", "generation": "new", "toolDefs": [
        {"type": "mcp", "server_url": "https://x.example/mcp", "project_connection_id": "gh-conn"}, {"type": "file_search"}]}],
    "projects": [{"name": "p", "account": "a", "endpoint": "https://e"}],
}
sent = {}


class FakeDisc:
    def create_agent(self, endpoint, name, model, instructions, description, tools, guardrail):
        sent["tools"] = tools
        return {"version": "1"}


@pytest.fixture(autouse=True)
def live(monkeypatch):
    monkeypatch.setenv("MARKETPLACE_DEMO", "0")
    monkeypatch.setattr(main, "catalog", lambda force=False: CAT)
    monkeypatch.setattr(discovery, "Discovery", FakeDisc)
    sent.clear()


def create(**kw):
    base = dict(project="p", account="a", name="bot", model="gpt", instructions="x")
    return main.create_agent(main.NewAgent(**{**base, **kw}), main.auth.User("t", "t@x", ["Builder"]))


def test_a_server_from_a_foundry_connection_is_attached_through_that_connection():
    create(mcp=["https://mcp.ai.azure.com"])
    (tool,) = sent["tools"]
    assert tool["server_url"] == "https://mcp.ai.azure.com" and tool["project_connection_id"] == "FoundryMCPServer"


def test_a_server_found_only_in_an_agent_tool_has_no_connection_to_attach():
    create(mcp=["https://x.example/mcp"])
    assert "project_connection_id" not in sent["tools"][0]


def test_editing_keeps_the_connection_the_agent_already_used():
    create(mcp=["https://x.example/mcp"], keep_tools=True)
    mcp = [t for t in sent["tools"] if t["type"] == "mcp"][0]
    assert mcp["project_connection_id"] == "gh-conn"
    assert any(t["type"] == "file_search" for t in sent["tools"])        # other tools are carried over as before


# ---- evaluation error messages --------------------------------------------------------------------------------------------------
MCP_401 = ('400: {"error":{"message":"Authentication failed when connecting to the MCP server: https://mcp.ai.azure.com:443/: '
           'Response status code does not indicate success: 401 (Unauthorized).. Verify the config')


def test_mcp_sign_in_failure_is_explained_as_configuration_not_a_bad_answer():
    msg = evals.explain_error(MCP_401)
    assert "MCP server" in msg and "configuration problem" in msg and "Foundry" in msg


def test_other_service_errors_get_plain_guidance():
    assert "rate-limited" in evals.explain_error("429: too many requests")
    assert "could not find this agent" in evals.explain_error("404: agent not found")
    assert evals.explain_error("500: boom").startswith("The call failed")


def test_a_failing_tool_is_recorded_as_a_failed_check_with_the_explanation():
    case = {"id": "q", "category": "quality", "title": "t", "prompt": "hi", "criteria": "", "expect": {}}
    def chat(prompt): raise RuntimeError(MCP_401)
    (r,) = evals.run_cases([case], chat, None)
    assert r["error"] and not r["passed"] and "configuration problem" in r["reasons"][0]
    assert evals.summarize([r])["errors"] == 1 and evals.summarize([r])["gate"] == "fail"
