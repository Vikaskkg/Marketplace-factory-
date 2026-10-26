"""Append-only audit trail: one JSON object per line.

Records who did what through the app. With sign-in on, the actor is the signed-in user (name, email, role); in local
mode it is the operating-system user. Set AUDIT_FILE to change the location, or AUDIT_FILE=off to disable. Ship this
file to durable storage in production.
"""
from __future__ import annotations

import getpass
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("marketplace")
_lock = threading.Lock()


def _path() -> Path | None:
    v = os.getenv("AUDIT_FILE")
    if v == "off" or os.getenv("MARKETPLACE_DEMO") == "1":
        return None
    return Path(v) if v else Path(__file__).parent.parent / ".cache" / "audit.log"


def record(action: str, user: Any = None, **details) -> None:
    p = _path()
    if not p:
        return
    actor = ({"name": user.name, "email": user.email, "role": user.role} if user is not None
             else {"name": getpass.getuser()})
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"ts": time.time(), "actor": actor, "action": action, **details}, default=str)
        with _lock, p.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:   # auditing must never break the request, but the failure must be visible
        log.warning("audit write failed: %s", e)
