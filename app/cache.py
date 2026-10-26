"""Catalog cache: in memory, saved to a local file, refreshed in the background.

- On start the last saved catalog is loaded from disk, so the first page opens instantly.
- A catalog older than `ttl` is still served at once while a refresh runs in a background thread.
- A catalog older than `max_age`, a missing one, a forced refresh, or one marked changed (after the app
  creates or deletes something) is rescanned before answering, so users never see data that is too old.
- A failed background refresh keeps the old data and retries after a short pause.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

log = logging.getLogger("marketplace")
VERSION = 1          # bump when the saved catalog's shape changes
RETRY_AFTER = 60     # seconds to wait after a failed background refresh


class CatalogCache:
    def __init__(self, loader: Callable[[], dict], path: Path | None, ttl: int, max_age: int, scope: str = "") -> None:
        self.loader, self.path, self.ttl, self.max_age = loader, path, ttl, max_age
        self.key = hashlib.sha256(scope.encode()).hexdigest()[:16]   # a different scan scope must not reuse the file
        self.data: dict | None = None
        self.at = 0.0
        self.from_disk = False
        self.last_error: str | None = None
        self._gen = 0                  # bumped by invalidate(); a scan that started earlier does not clear it
        self._dirty_gen = 0
        self._next_try = 0.0
        self._refreshing = False
        self._state = threading.Lock()
        self._scan_lock = threading.Lock()
        self._read_file()

    # ---- disk ---------------------------------------------------------------
    def _read_file(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            p = json.loads(self.path.read_text(encoding="utf-8"))
            if p.get("v") == VERSION and p.get("key") == self.key and isinstance(p.get("data"), dict):
                self.data, self.at, self.from_disk = p["data"], float(p["at"]), True
                log.info("catalog cache loaded from %s (%.0f min old)", self.path, (time.time() - self.at) / 60)
        except Exception as e:  # a corrupt cache file is just ignored and rebuilt
            log.warning("ignoring unreadable cache file %s: %s", self.path, e)

    def _write_file(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"v": VERSION, "key": self.key, "at": self.at, "data": self.data}, f)
            os.replace(tmp, self.path)   # atomic: readers never see a half-written file
        except Exception as e:
            log.warning("could not save cache file %s: %s", self.path, e)

    # ---- scanning -----------------------------------------------------------
    def _scan(self, force: bool = False) -> None:
        seen_at = self.at
        with self._scan_lock:
            if not force and self.at != seen_at:
                return   # someone else finished a scan while we waited
            gen = self._gen
            data = self.loader()
            with self._state:
                self.data, self.at, self.from_disk, self.last_error = data, time.time(), False, None
                if self._dirty_gen <= gen:
                    self._dirty_gen = 0
            self._write_file()

    def _background(self) -> None:
        try:
            self._scan()
        except Exception as e:
            self.last_error = str(e)[:300]
            self._next_try = time.time() + RETRY_AFTER
            log.warning("background catalog refresh failed: %s", e)
        finally:
            self._refreshing = False

    # ---- public -------------------------------------------------------------
    def invalidate(self) -> None:
        """Something changed in Azure through this app: the next read must rescan first."""
        with self._state:
            self._gen += 1
            self._dirty_gen = self._gen

    def get(self, force: bool = False) -> dict:
        now = time.time()
        dirty = self._dirty_gen > 0 and now >= self._next_try
        must_wait = (force or self.data is None or dirty or now - self.at > self.max_age)
        if must_wait:
            try:
                self._scan(force)
            except Exception as e:
                # Azure unreachable: an explicit refresh or an empty cache must fail loudly; otherwise keep serving old data
                if force or self.data is None or now - self.at > self.max_age:
                    raise
                self.last_error = str(e)[:300]
                self._next_try = now + RETRY_AFTER
                log.warning("catalog rescan failed, serving cached data: %s", e)
        elif now - self.at > self.ttl and not self._refreshing and now >= self._next_try:
            with self._state:
                start = not self._refreshing
                self._refreshing = True
            if start:
                threading.Thread(target=self._background, daemon=True, name="catalog-refresh").start()
        return {**self.data, "fetchedAt": self.at, "refreshing": self._refreshing,
                "fromDisk": self.from_disk, "refreshError": self.last_error}
