"""Authentication and protected routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_chat_requires_auth(client: TestClient):
    r = client.post(
        "/api/chat",
        json={"message": "Show stockouts", "session_id": "pytest-no-auth", "scope": "all"},
    )
    assert r.status_code == 401


def test_login_success(client: TestClient):
    r = client.post("/api/auth/login", json={"username": "analyst", "password": "analyst123"})
    assert r.status_code == 200
    j = r.json()
    assert j.get("token_type") == "bearer"
    assert "access_token" in j
    assert j.get("role") == "Analyst"


def test_login_invalid_password(client: TestClient):
    r = client.post("/api/auth/login", json={"username": "analyst", "password": "wrong"})
    assert r.status_code == 401


def test_me_requires_auth(client: TestClient):
    r = client.get("/api/auth/me")
    assert r.status_code == 401


def test_me_with_token(client: TestClient):
    login = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    token = login.json()["access_token"]
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json().get("role") == "Admin"


def test_chat_missing_parameters_returns_clarification(client: TestClient):
    login = client.post("/api/auth/login", json={"username": "analyst", "password": "analyst123"})
    token = login.json()["access_token"]
    r = client.post(
        "/api/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "message": "Show stockouts for my network",
            "session_id": "pytest-param-gate",
            "scope": None,
            "demand_window_days": None,
            "parameters_confirmed": False,
        },
    )
    assert r.status_code == 200
    j = r.json()
    assert j.get("status") == "needs_clarification"
    assert j.get("reason") == "missing_tool_parameters"
    assert "missing_parameters" in j
    assert "clarification_context" in j


def test_chat_runs_when_params_explicit(client: TestClient):
    login = client.post("/api/auth/login", json={"username": "analyst", "password": "analyst123"})
    token = login.json()["access_token"]
    r = client.post(
        "/api/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "message": "Show stockouts",
            "session_id": "pytest-param-ok",
            "scope": "DC-004",
            "demand_window_days": 30,
            "parameters_confirmed": False,
        },
    )
    assert r.status_code == 200
    j = r.json()
    assert not (
        j.get("status") == "needs_clarification" and j.get("reason") == "missing_tool_parameters"
    ), "Explicit scope + window should pass the pre-tool parameter gate"
