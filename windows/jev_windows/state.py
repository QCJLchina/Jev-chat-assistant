"""Revision-tracked progress state shared by every bridge operation.

The bridge only exposes a "has anything changed since revision N?" poll. Keeping
that bookkeeping in one small object stops each service from reimplementing it
and keeps the revision counter single-sourced.
"""
from __future__ import annotations

import threading

from .i18n import describe, msg, render


class ProgressState:
    """Owns the mutable progress dictionary plus its revision counter."""

    def __init__(self, language: str):
        self._lock = threading.RLock()
        self._state: dict = {
            "status": msg("status.initial"),
            "phase": "idle",
            "preview": [],
            "analysis": None,
            "suggestions": [],
            "error": "",
        }
        self._state["status_message"] = describe(self._state["status"])
        self._state["error_message"] = None
        self._revision = 0
        self.language = language

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def set_language(self, language: str) -> None:
        with self._lock:
            self.language = language
            self._revision += 1

    def update(self, **updates: object) -> None:
        """Apply progress fields, keeping messages translatable until render."""
        with self._lock:
            for field in ("status", "error"):
                if field in updates:
                    updates[field + "_message"] = describe(updates[field])
                    if isinstance(updates[field], Exception):
                        updates[field] = str(updates[field])
            self._state.update(updates)
            self._revision += 1

    def phase(self) -> str:
        with self._lock:
            return self._state.get("phase", "idle")

    def get(self, key: str, default=None):
        with self._lock:
            return self._state.get(key, default)

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._state)

    def revision(self) -> int:
        with self._lock:
            return self._revision

    def rendered(self) -> dict:
        state = self.snapshot()
        for field in ("status", "error"):
            state[field] = render(state.get(field + "_message"), self.language, str(state[field]))
        return state

    def poll(self, known_revision: int = -1) -> dict:
        with self._lock:
            revision = self._revision
            if known_revision == revision:
                return {"revision": revision}
            state = dict(self._state)
        for field in ("status", "error"):
            state[field] = render(state.get(field + "_message"), self.language, str(state[field]))
        return {"revision": revision, **state}
