"""In-memory last result per session for export endpoints."""

from __future__ import annotations

import threading
from typing import Any

_lock = threading.Lock()
_by_session: dict[str, dict[str, Any]] = {}
_pending_tool: dict[str, dict[str, Any]] = {}


def save_pending_tool(session_id: str, payload: dict[str, Any] | None) -> None:
    with _lock:
        if payload is None:
            _pending_tool.pop(session_id, None)
        else:
            _pending_tool[session_id] = dict(payload)


def get_pending_tool(session_id: str) -> dict[str, Any] | None:
    with _lock:
        return _pending_tool.get(session_id)


def save_session_payload(session_id: str, payload: dict[str, Any]) -> None:
    with _lock:
        _by_session[session_id] = payload


def get_session_payload(session_id: str) -> dict[str, Any] | None:
    with _lock:
        return _by_session.get(session_id)
