"""API-level tests: sign-in modes, roles, CSRF, session limits, portfolio numbers.
Run: .venv\\Scripts\\python.exe -m pytest tests"""
import os
import sys
import time
from pathlib import Path

os.environ["MARKETPLACE_DEMO"] = "1"          # sample catalog, no Azure calls
os.environ["AUDIT_FILE"] = "off"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from app import auth, main, portfolio  # noqa: E402

client = TestClient(main.app)
H = {"x-requested-with": "AgentHub"}
DRAFT = {"account": "foundry-eng", "project": "devex", "name": "t1", "model": "gpt-5", "instructions": "x"}


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    for k in ("AUTH_MODE", "DEV_ROLE", "SESSION_IDLE_MINUTES", "SESSION_MAX_HOURS", "DEFAULT_ROLE"):
        monkeypatch.delenv(k, raising=False)
    auth.sessions._s.clear()
    client.cookies.clear()


def login(monkeypatch, roles, **extra):
    """Create a session directly (the Entra exchange itself needs a real tenant) and give the client its cookie."""
    monkeypatch.setenv("AUTH_MODE", "entra")
    s = auth.sessions.create(auth.user_from_claims({"name": "Ada Lovelace", "preferred_username": "ada@corp.example",
                                                    "roles": roles, "oid": "1", **extra}))
    client.cookies.set(auth.COOKIE, s.id)
    return s


# ---- local mode ------------------------------------------------------------------------------------------------------
def test_local_mode_acts_as_admin():
    assert client.get("/api/me").json()["role"] == "Admin"
    assert client.post("/api/agents/delete", json={"project": "devex", "account": "foundry-eng", "name": "a"}, headers=H).status_code == 200


def test_writes_need_the_csrf_header_in_every_mode():
    """Even a server on localhost must refuse a state-changing request that a foreign web page could have sent."""
    body = {"project": "devex", "account": "foundry-eng", "name": "a"}
    assert client.post("/api/agents/delete", json=body).status_code == 403
    assert client.post("/api/agents/delete", json=body, headers={**H, "origin": "https://evil.example"}).status_code == 403


def test_dev_role_limits_local_user(monkeypatch):
    monkeypatch.setenv("DEV_ROLE", "Viewer")
    assert client.get("/api/summary").status_code == 200
    assert client.post("/api/agents/create", json=DRAFT, headers=H).status_code == 403


# ---- "az login" mode (the default) --------------------------------------------------------------------------------------
def fake_jwt(claims: dict) -> str:
    import base64, json
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{enc({'alg': 'none'})}.{enc(claims)}.sig"


def stub_azure_cli(monkeypatch, claims=None, error=None):
    """Replace the Azure CLI credential: `claims` is what `az login` would hand out, `error` means nobody is logged in."""
    import azure.identity as ai
    class Tok:  # noqa: D401
        def __init__(self, t): self.token = t
    class Fake:
        def get_token(self, *_):
            if error: raise RuntimeError(error)
            return Tok(fake_jwt(claims))
    monkeypatch.setattr(ai, "AzureCliCredential", Fake)
    monkeypatch.setenv("MARKETPLACE_DEMO", "0")
    monkeypatch.delenv("AUTH_MODE", raising=False)
    auth._az.update(user=None, at=0.0, error="")


def test_azcli_user_comes_from_the_az_login_token(monkeypatch):
    stub_azure_cli(monkeypatch, {"name": "Grace Hopper", "upn": "grace@corp.example", "oid": "o-1", "tid": "t-1"})
    me = client.get("/api/me").json()
    assert (me["name"], me["email"], me["source"], me["tenant"], me["mode"]) == ("Grace Hopper", "grace@corp.example", "Azure CLI", "t-1", "azcli")
    assert me["role"] == "Admin"                      # no app roles exist in this mode; DEV_ROLE decides (default Admin)
    assert client.get("/api/summary").status_code != 401


def test_azcli_role_can_be_limited(monkeypatch):
    stub_azure_cli(monkeypatch, {"name": "G", "upn": "g@corp.example"})
    monkeypatch.setenv("DEV_ROLE", "Viewer")
    assert client.get("/api/me").json()["role"] == "Viewer"
    assert client.post("/api/agents/create", json=DRAFT, headers=H).status_code == 403


def test_azcli_not_logged_in_gives_401_and_recovers_after_az_login(monkeypatch):
    stub_azure_cli(monkeypatch, error="Please run 'az login'")
    r = client.get("/api/me")
    assert r.status_code == 401 and r.json()["mode"] == "azcli"
    assert client.get("/api/summary").status_code == 401
    stub_azure_cli(monkeypatch, {"name": "Grace Hopper", "upn": "grace@corp.example"})   # the user ran az login
    assert client.get("/api/me?refresh=true").status_code == 200


def test_azcli_identity_is_cached_but_refreshable(monkeypatch):
    stub_azure_cli(monkeypatch, {"name": "First", "upn": "first@corp.example"})
    assert client.get("/api/me").json()["name"] == "First"
    stub_azure_cli(monkeypatch, {"name": "Second", "upn": "second@corp.example"})
    auth._az.update(user=auth.User("First", "first@corp.example", ["Admin"]), at=time.time())   # still within the cache window
    assert client.get("/api/me").json()["name"] == "First"
    assert client.get("/api/me?refresh=true").json()["name"] == "Second"        # `az login` as someone else, then refresh


def test_service_principal_login_falls_back_to_the_app_id(monkeypatch):
    stub_azure_cli(monkeypatch, {"appid": "app-123", "oid": "o"})
    assert client.get("/api/me").json()["email"] == "app-123"


def test_azcli_mode_uses_the_cli_credential_for_azure_calls(monkeypatch):
    import azure.identity as ai
    seen = {}
    monkeypatch.setattr(ai, "AzureCliCredential", lambda: seen.setdefault("cli", object()))
    monkeypatch.delenv("AUTH_MODE", raising=False)
    from app import discovery
    monkeypatch.setattr(discovery, "AzureCliCredential", ai.AzureCliCredential)
    assert discovery.Discovery().cred is seen["cli"]


def test_healthz_is_open(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "entra")
    assert client.get("/healthz").json() == {"ok": True}


# ---- entra mode --------------------------------------------------------------------------------------------------------
def test_unauthenticated_requests_get_401(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "entra")
    for path in ("/api/summary", "/api/agents", "/api/portfolio", "/api/projects"):
        assert client.get(path).status_code == 401, path
    assert client.get("/api/me").status_code == 401
    assert client.post("/api/discover", json={"query": "anything"}, headers=H).status_code == 401


def test_role_matrix(monkeypatch):
    login(monkeypatch, ["Viewer"])
    assert client.get("/api/summary").status_code == 200
    assert client.post("/api/agents/create", json=DRAFT, headers=H).status_code == 403
    assert client.post("/api/refresh", headers=H).status_code == 403
    login(monkeypatch, ["Builder"])
    assert client.post("/api/agents/create", json=DRAFT, headers=H).status_code == 200
    assert client.post("/api/agents/delete", json={k: DRAFT[k] for k in ("project", "account", "name")}, headers=H).status_code == 403
    assert client.post("/api/guardrails/create", json={"account": "a", "name": "g", "thresholds": {"Hate": "Low"}}, headers=H).status_code == 403
    login(monkeypatch, ["Approver"])
    assert client.post("/api/agents/delete", json={k: DRAFT[k] for k in ("project", "account", "name")}, headers=H).status_code == 200


def test_highest_role_wins_and_unknown_roles_are_ignored(monkeypatch):
    login(monkeypatch, ["Viewer", "Admin", "SuperUser"])
    me = client.get("/api/me").json()
    assert me["role"] == "Admin" and me["roles"] == ["Viewer", "Admin"]


def test_signed_in_user_without_a_role_is_refused(monkeypatch):
    login(monkeypatch, [])
    me = client.get("/api/me").json()
    assert me["access"] is False
    assert client.get("/api/summary").status_code == 403


def test_csrf_header_and_origin_are_required_for_writes(monkeypatch):
    login(monkeypatch, ["Admin"])
    assert client.post("/api/agents/create", json=DRAFT).status_code == 403                           # no header
    assert client.post("/api/agents/create", json=DRAFT, headers={**H, "origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/agents/create", json=DRAFT, headers={**H, "origin": "http://testserver"}).status_code == 200


def test_idle_timeout_ends_the_session(monkeypatch):
    s = login(monkeypatch, ["Viewer"])
    assert client.get("/api/summary").status_code == 200
    s.last_seen = time.time() - 31 * 60
    assert client.get("/api/summary").status_code == 401


def test_absolute_timeout_ends_the_session_even_if_active(monkeypatch):
    s = login(monkeypatch, ["Viewer"])
    s.created = time.time() - 9 * 3600
    assert client.get("/api/summary").status_code == 401


def test_me_does_not_extend_an_idle_session(monkeypatch):
    s = login(monkeypatch, ["Viewer"])
    s.last_seen = time.time() - 600
    before = s.last_seen
    client.get("/api/me")
    assert s.last_seen == before
    client.get("/api/summary")
    assert s.last_seen > before


def test_logout_ends_the_session_and_points_at_entra(monkeypatch):
    monkeypatch.setenv("ENTRA_TENANT_ID", "tenant-1"); monkeypatch.setenv("ENTRA_CLIENT_ID", "c")
    monkeypatch.setenv("ENTRA_CLIENT_SECRET", "s"); monkeypatch.setenv("PUBLIC_URL", "https://hub.example")
    s = login(monkeypatch, ["Viewer"])
    assert client.post("/auth/logout").status_code == 403                         # CSRF header required
    r = client.post("/auth/logout", headers=H)
    assert "login.microsoftonline.com/tenant-1/oauth2/v2.0/logout" in r.json()["redirect"]
    assert "post_logout_redirect_uri=https%3A%2F%2Fhub.example%2F" in r.json()["redirect"]
    assert auth.sessions.get(s.id) is None
    client.cookies.set(auth.COOKIE, s.id)
    assert client.get("/api/summary").status_code == 401


def test_login_without_configuration_says_what_is_missing(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "entra")
    for k in ("ENTRA_TENANT_ID", "ENTRA_CLIENT_ID", "ENTRA_CLIENT_SECRET", "PUBLIC_URL"):
        monkeypatch.delenv(k, raising=False)
    r = client.get("/auth/login", follow_redirects=False)
    assert r.status_code == 503 and "ENTRA_TENANT_ID" in r.json()["detail"]


def test_callback_with_unknown_state_is_rejected(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "entra")
    for k, v in (("ENTRA_TENANT_ID", "t"), ("ENTRA_CLIENT_ID", "c"), ("ENTRA_CLIENT_SECRET", "s"), ("PUBLIC_URL", "https://hub.example")):
        monkeypatch.setenv(k, v)
    r = client.get("/auth/callback?state=forged&code=abc", follow_redirects=False)
    assert r.status_code in (302, 307) and "auth_error=expired" in r.headers["location"]
    assert auth.COOKIE not in r.headers.get("set-cookie", "")


def test_return_address_cannot_leave_the_site():
    for bad in ("https://evil.example", "//evil.example", "/\\evil", "javascript:alert(1)", "/ok\r\nSet-Cookie: x=1"):
        assert auth.safe_next(bad) == "/", bad
    assert auth.safe_next("/#/factory") == "/#/factory"


def test_default_role_applies_only_when_configured(monkeypatch):
    assert auth.user_from_claims({"name": "x", "roles": []}).access is False
    monkeypatch.setenv("DEFAULT_ROLE", "Viewer")
    assert auth.user_from_claims({"name": "x", "roles": []}).role == "Viewer"


# ---- portfolio and system agents -----------------------------------------------------------------------------------
def test_planner_agent_is_hidden_and_not_counted(monkeypatch):
    cat = main.catalog()
    planner = {**cat["agents"][0], "id": "p", "name": main.PLANNER_AGENT}
    monkeypatch.setattr(main, "catalog", lambda force=False: {**cat, "agents": cat["agents"] + [planner]})
    names = [a["name"] for a in client.get("/api/agents").json()]
    assert main.PLANNER_AGENT not in names
    assert main.PLANNER_AGENT in [a["name"] for a in client.get("/api/agents?system=true").json()]
    assert client.get("/api/summary").json()["counts"]["agents"] == len(cat["agents"])
    assert client.get("/api/portfolio").json()["kpis"]["agents"] == len(cat["agents"])


def test_dashboard_numbers_match_the_lists_behind_them():
    p = client.get("/api/portfolio").json()
    for item in p["attention"]:
        if item["filter"]:
            assert item["count"] == len(client.get(f"/api/agents?filter={item['filter']}").json()), item["filter"]
    g = p["governance"]
    assert g["withGuardrail"] + g["withoutGuardrail"] == g["managedAgents"]


def test_unknown_filter_matches_nothing():
    assert client.get("/api/agents?filter=nonsense").json() == []


def test_stale_and_external_filters(monkeypatch):
    now = time.time()
    c = {"agents": [
        {"name": "old", "generation": "new", "created": now - 200 * 86400, "description": "d", "guardrail": "g", "toolDefs": []},
        {"name": "fresh", "generation": "new", "created": now - 86400, "description": "", "guardrail": None,
         "toolDefs": [{"type": "mcp", "server_url": "https://vendor.example/mcp"}]},
        {"name": "classic", "generation": "classic", "created": now, "description": "d", "toolDefs": []}],
        "mcp": [{"name": "v", "target": "https://vendor.example/mcp"}, {"name": "i", "target": "https://tools.corp.example/mcp"}]}
    monkeypatch.setenv("CORP_DOMAINS", "corp.example")
    names = lambda f: [a["name"] for a in portfolio.agent_filter(c, c["agents"], f, now)]
    assert names("stale") == ["old"]
    assert names("no-guardrail") == ["fresh"]            # classic agents cannot carry one, so they are not counted
    assert names("no-description") == ["fresh"]
    assert names("external-tools") == ["fresh"]
    assert names("classic") == ["classic"]
    monkeypatch.delenv("CORP_DOMAINS")
    assert names("external-tools") == []                 # nothing is called external until corporate domains are listed
