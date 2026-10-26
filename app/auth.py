"""Sign-in, sessions and roles.

AUTH_MODE=off   (default) no sign-in; every request acts as a fixed local user (DEV_ROLE, default Admin).
AUTH_MODE=entra Microsoft Entra ID sign-in (OIDC authorization-code flow with PKCE, via MSAL).

The browser only ever holds an opaque, random session id in an HttpOnly cookie. Entra and Azure tokens stay on the
server and are not stored in the session. Roles come from Entra app roles: Viewer < Builder < Approver < Admin.
Sessions live in memory (one process); swap SessionStore for Redis or a database to run several instances.
"""
from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

log = logging.getLogger("marketplace")

ROLES = ("Viewer", "Builder", "Approver", "Admin")
RANK = {r: i + 1 for i, r in enumerate(ROLES)}
COOKIE = "hub_session"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "AgentHub"


@dataclass
class User:
    name: str
    email: str
    roles: list[str]
    oid: str = ""
    source: str = ""     # where the identity came from, e.g. "Azure CLI"
    tenant: str = ""

    @property
    def role(self) -> str | None:
        return max(self.roles, key=RANK.__getitem__) if self.roles else None

    @property
    def access(self) -> bool:
        return bool(self.roles)


@dataclass
class Session:
    user: User
    created: float
    last_seen: float
    id: str = field(default_factory=lambda: secrets.token_urlsafe(32))


def mode() -> str:
    """azcli (default): the user is whoever ran `az login`. entra: Entra ID sign-in. off: no identity, fixed local user."""
    m = os.getenv("AUTH_MODE", "azcli").strip().lower()
    return m if m in ("azcli", "entra", "off") else "azcli"


def _minutes(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def idle_seconds() -> float:
    return _minutes("SESSION_IDLE_MINUTES", 30) * 60


def max_seconds() -> float:
    return _minutes("SESSION_MAX_HOURS", 8) * 3600


class SessionStore:
    def __init__(self) -> None:
        self._s: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self, user: User) -> Session:
        now = time.time()
        s = Session(user, now, now)
        with self._lock:
            self._s[s.id] = s
            self._purge(now)
        return s

    def get(self, sid: str | None, touch: bool = True) -> Session | None:
        if not sid:
            return None
        now = time.time()
        with self._lock:
            s = self._s.get(sid)
            if not s:
                return None
            if now - s.last_seen > idle_seconds() or now - s.created > max_seconds():
                del self._s[sid]
                return None
            if touch:
                s.last_seen = now
            return s

    def delete(self, sid: str | None) -> None:
        with self._lock:
            self._s.pop(sid or "", None)

    def _purge(self, now: float) -> None:
        for k in [k for k, s in self._s.items() if now - s.last_seen > idle_seconds() or now - s.created > max_seconds()]:
            del self._s[k]


sessions = SessionStore()
_flows: dict[str, tuple[dict, str, float]] = {}   # state -> (MSAL flow, return path, created); one-time use
_flows_lock = threading.Lock()
FLOW_TTL = 600


# ---- who is calling ------------------------------------------------------------------------------------------------
def _local_user() -> User:
    role = os.getenv("DEV_ROLE", "Admin")
    name = "Demo user" if os.getenv("MARKETPLACE_DEMO") == "1" else "Local developer"
    return User(name, "local@localhost", [role] if role in RANK else ["Admin"])


_az: dict = {"user": None, "at": 0.0, "error": ""}
AZ_TTL_OK, AZ_TTL_FAIL = 300, 5   # re-read the Azure CLI identity every 5 minutes; retry quickly while not logged in


def _jwt_claims(token: str) -> dict:
    """Read a token's claims without verifying it. Only used on a token this machine just got from the Azure CLI."""
    import base64
    import json
    part = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def azcli_user(refresh: bool = False) -> User | None:
    """Who ran `az login`, or None if nobody is logged in. Cached briefly because asking the CLI takes a moment."""
    now = time.time()
    age = now - _az["at"]
    if not refresh and _az["at"] and age < (AZ_TTL_OK if _az["user"] else AZ_TTL_FAIL):
        return _az["user"]
    user, error = None, ""
    try:
        from azure.identity import AzureCliCredential
        claims = _jwt_claims(AzureCliCredential().get_token("https://management.azure.com/.default").token)
        email = claims.get("upn") or claims.get("unique_name") or claims.get("preferred_username") or claims.get("appid", "")
        role = os.getenv("DEV_ROLE", "Admin")
        user = User(claims.get("name") or email or "Azure CLI user", email, [role if role in RANK else "Admin"],
                    claims.get("oid", ""), "Azure CLI", claims.get("tid", ""))
    except Exception as e:
        error = str(e)[:200]
        log.info("no Azure CLI login found: %s", error)
    _az.update(user=user, at=now, error=error)
    return user


def resolve(request: Request, touch: bool = True, refresh: bool = False) -> User | None:
    m = mode()
    if m == "off" or (os.getenv("MARKETPLACE_DEMO") == "1" and m != "entra"):
        return _local_user()
    if m == "azcli":
        return azcli_user(refresh)
    s = sessions.get(request.cookies.get(COOKIE), touch)
    return s.user if s else None


def _check_csrf(request: Request) -> None:
    """Anything that changes state must carry a header a foreign web page cannot add (and a matching Origin).

    This matters in every mode: even without cookies, any page open in your browser could otherwise post to a
    server running on localhost.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise HTTPException(403, "Missing CSRF header")
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "Cross-origin request refused")


def require(minimum: str):
    """FastAPI dependency: the caller must be signed in and hold at least this role."""
    def dep(request: Request) -> User:
        user = resolve(request)
        if user is None:
            raise HTTPException(401, "Not signed in")
        _check_csrf(request)
        if not user.access:
            raise HTTPException(403, "Your account has no Agent Hub role. Ask an administrator to assign one.")
        if RANK[user.role or "Viewer"] < RANK[minimum]:
            raise HTTPException(403, f"This needs the {minimum} role; you have {user.role}.")
        return user
    return dep


# ---- Entra (MSAL) ------------------------------------------------------------------------------------------------------
def _cfg() -> dict:
    c = {k: os.getenv(k, "") for k in ("ENTRA_TENANT_ID", "ENTRA_CLIENT_ID", "ENTRA_CLIENT_SECRET", "PUBLIC_URL")}
    missing = [k for k, v in c.items() if not v]
    if missing:
        raise HTTPException(503, f"Sign-in is not configured: set {', '.join(missing)}")
    c["PUBLIC_URL"] = c["PUBLIC_URL"].rstrip("/")
    c["AUTHORITY"] = f"https://login.microsoftonline.com/{c['ENTRA_TENANT_ID']}"
    return c


_msal_app = None


def _msal():
    global _msal_app
    if _msal_app is None:
        import msal   # imported lazily so AUTH_MODE=off needs no sign-in setup
        c = _cfg()
        _msal_app = msal.ConfidentialClientApplication(c["ENTRA_CLIENT_ID"], authority=c["AUTHORITY"],
                                                       client_credential=c["ENTRA_CLIENT_SECRET"])
    return _msal_app


def user_from_claims(claims: dict) -> User:
    """Build the user from validated ID-token claims. Only recognised role names are kept."""
    wanted = {r.lower(): r for r in ROLES}
    roles = sorted({wanted[str(r).lower()] for r in (claims.get("roles") or []) if str(r).lower() in wanted}, key=RANK.get)
    default = os.getenv("DEFAULT_ROLE")
    if not roles and default in RANK:
        roles = [default]
    return User(claims.get("name") or claims.get("preferred_username") or "Unknown",
                claims.get("preferred_username") or claims.get("email") or "", roles, claims.get("oid", ""))


def safe_next(path: str | None) -> str:
    """Only same-site relative paths may be used as the return address (no open redirect)."""
    p = path or "/"
    if not p.startswith("/") or p.startswith("//") or "\\" in p or "\n" in p or "\r" in p:
        return "/"
    return p


router = APIRouter()


@router.get("/auth/login")
def login(next: str = "/"):
    if mode() != "entra":
        return RedirectResponse(safe_next(next))
    c = _cfg()
    flow = _msal().initiate_auth_code_flow(["User.Read"], redirect_uri=f"{c['PUBLIC_URL']}/auth/callback")
    if "auth_uri" not in flow:
        raise HTTPException(502, "Could not start sign-in")
    with _flows_lock:
        now = time.time()
        for k in [k for k, v in _flows.items() if now - v[2] > FLOW_TTL]:
            del _flows[k]
        _flows[flow["state"]] = (flow, safe_next(next), now)
    return RedirectResponse(flow["auth_uri"])


@router.get("/auth/callback")
def callback(request: Request):
    if mode() != "entra":
        return RedirectResponse("/")
    c = _cfg()
    with _flows_lock:
        entry = _flows.pop(request.query_params.get("state", ""), None)
    if not entry or time.time() - entry[2] > FLOW_TTL:
        return RedirectResponse("/?auth_error=expired")
    try:
        result = _msal().acquire_token_by_auth_code_flow(entry[0], dict(request.query_params))
    except ValueError:   # state or nonce mismatch
        return RedirectResponse("/?auth_error=invalid")
    if "error" in result or "id_token_claims" not in result:
        log.warning("sign-in failed: %s", result.get("error_description", result.get("error")))
        return RedirectResponse("/?auth_error=failed")
    user = user_from_claims(result["id_token_claims"])
    session = sessions.create(user)   # tokens in `result` are deliberately not kept
    resp = RedirectResponse(entry[1])
    resp.set_cookie(COOKIE, session.id, httponly=True, secure=c["PUBLIC_URL"].startswith("https://"),
                    samesite="lax", max_age=int(max_seconds()), path="/")
    from . import audit
    audit.record("auth.login", user=user)
    return resp


@router.post("/auth/logout")
def logout(request: Request):
    user = resolve(request, touch=False)
    _check_csrf(request)
    sessions.delete(request.cookies.get(COOKIE))
    target = "/"
    if mode() == "entra":
        c = _cfg()
        target = f"{c['AUTHORITY']}/oauth2/v2.0/logout?post_logout_redirect_uri={quote(c['PUBLIC_URL'] + '/', safe='')}"
    from . import audit
    if user:
        audit.record("auth.logout", user=user)
    resp = JSONResponse({"redirect": target})
    resp.delete_cookie(COOKIE, path="/")
    return resp


@router.get("/api/me")
def me(request: Request, refresh: bool = False):
    """Who am I? 401 means the browser should show the sign-in page. `refresh` re-reads the Azure CLI login."""
    s_id = request.cookies.get(COOKIE)
    user = resolve(request, touch=False, refresh=refresh)   # asking who I am must not extend an idle session
    if user is None:
        return JSONResponse({"detail": "Not signed in", "mode": mode()}, status_code=401)
    sess = sessions.get(s_id, touch=False) if mode() == "entra" else None
    expires = None
    if sess:
        expires = min(sess.last_seen + idle_seconds(), sess.created + max_seconds())
    return {"name": user.name, "email": user.email, "role": user.role, "roles": user.roles, "access": user.access,
            "mode": mode(), "expiresAt": expires, "source": user.source, "tenant": user.tenant}


@router.post("/api/session/keepalive")
def keepalive(user: User = Depends(require("Viewer"))):
    """Explicit 'stay signed in': the dependency already refreshed the idle timer."""
    return {"ok": True}
