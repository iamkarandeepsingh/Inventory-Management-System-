"""Pre-tool parameter gate (SRS FR2.2)."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_missing_scope_blocks():
    from parameter_orchestration import evaluate_tool_execution_readiness

    routing = {"workflow_id": "UC-1"}
    ok, miss, msg, ctx = evaluate_tool_execution_readiness(
        scope=None,
        demand_window_days=30,
        parameters_confirmed=False,
        routing=routing,
    )
    assert ok is False
    assert "location_scope" in miss
    assert "scope" in msg.lower() or "location" in msg.lower()


def test_all_locations_requires_confirmation():
    from parameter_orchestration import evaluate_tool_execution_readiness

    routing = {"workflow_id": "UC-1"}
    ok, miss, _, _ = evaluate_tool_execution_readiness(
        scope="all",
        demand_window_days=30,
        parameters_confirmed=False,
        routing=routing,
    )
    assert ok is False
    assert "confirm_all_locations" in miss

    ok2, miss2, _, _ = evaluate_tool_execution_readiness(
        scope="all",
        demand_window_days=30,
        parameters_confirmed=True,
        routing=routing,
    )
    assert ok2 is True
    assert miss2 == []


def test_greeting_workflow_skips_gate():
    from parameter_orchestration import evaluate_tool_execution_readiness

    ok, miss, _, _ = evaluate_tool_execution_readiness(
        scope=None,
        demand_window_days=None,
        parameters_confirmed=False,
        routing={"workflow_id": "GREETING"},
    )
    assert ok is True
    assert miss == []
