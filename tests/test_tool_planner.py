"""Unit tests for governed tool planning (no DuckDB file required)."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_tool_plan_uc1_shape():
    from tool_planner import build_tool_plan

    p = build_tool_plan(
        None,
        {"workflow_id": "UC-1", "scope": "all", "demand_window_days": 30, "top_n": 3},
    )
    assert set(p.keys()) == {"tool", "query", "kpi", "params"}
    assert p["tool"] == "sql_execute_UC-1"
    assert p["query"] == "q-uc1-001"
    assert p["kpi"] == "stockout_severity"
    assert p["params"]["complete"] is True
    assert p["params"]["location"] == "all"
    assert p["params"]["demand_window_days"] == 30


def test_tool_plan_non_executable_empty():
    from tool_planner import build_tool_plan

    p = build_tool_plan(None, {"workflow_id": "GREETING", "scope": "all"})
    assert p == {"tool": "", "query": "", "kpi": "", "params": {}}


def test_tool_plan_incomplete_location():
    from tool_planner import build_tool_plan

    p = build_tool_plan(
        None,
        {"workflow_id": "UC-2", "scope": "not-a-valid-loc", "demand_window_days": 30, "top_n": 10},
    )
    assert p["tool"] == ""
    assert p["params"]["complete"] is False
    assert "location" in p["params"]["missing_parameters"]
