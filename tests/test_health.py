"""Smoke tests for API and Agent 2 (no live Gemini required for health)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_health(client: TestClient):
    r = client.get("/api/health")
    assert r.status_code == 200
    j = r.json()
    assert "status" in j
    assert j.get("db") == "connected"


def test_agent2_uc1_direct():
    from bootstrap_data import init_database
    from agents.agent2_pipeline import execute_pipeline

    conn = init_database()
    out = execute_pipeline(
        conn,
        {"workflow_id": "UC-1", "scope": "all", "demand_window_days": 30, "top_n": 3},
        "pytest",
    )
    assert out.get("error") is None
    assert "findings" in out
    assert out["tool_versions"]["kpi_calculator"] == "v2.1"
