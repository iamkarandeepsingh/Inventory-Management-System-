"""
Maps classified routing (workflow / intent) to governed tool invocation metadata.

No LLM and no fabricated numbers — only resolves template ids, KPI rule ids, and
parameters from routing + DB snapshot date.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import duckdb

from config import VALID_SCOPES
from sql_templates import QUERY_BY_WORKFLOW

# KPI / rule enrichment used in agent2_pipeline._enrich_findings (stable ids for clients).
WORKFLOW_TO_KPI_CALCULATOR: dict[str, str] = {
    "UC-1": "stockout_severity",
    "UC-2": "backorder_severity",
    "UC-3": "dos_rules",
    "UC-4": "slow_mover_rules",
    "UC-5": "anomaly_severity",
    "UC-6": "cycle_count_rules",
    "UC-7": "abc_rules",
    "UC-8": "coverage_rules",
}


def _snapshot_date(conn: duckdb.DuckDBPyConnection) -> date:
    row = conn.execute(
        "SELECT MAX(snapshot_date) FROM fact_inventory_snapshot"
    ).fetchone()
    if not row or row[0] is None:
        raise RuntimeError("No snapshot_date in fact_inventory_snapshot")
    v = row[0]
    if isinstance(v, datetime):
        return v.date()
    if hasattr(v, "date"):
        return v.date()  # type: ignore[no-any-return]
    return v  # type: ignore[no-any-return]


def _params_complete(
    scope: str | None, demand_window_days: int | None, top_n: int
) -> tuple[bool, list[str]]:
    missing: list[str] = []
    if scope is None or str(scope).strip() == "" or scope not in VALID_SCOPES:
        missing.append("location")
    if demand_window_days is None or int(demand_window_days) <= 0:
        missing.append("date_window")
    if top_n <= 0:
        missing.append("top_n")
    return (len(missing) == 0, missing)


def _resolved_date_window(
    workflow_id: str, snap: date, demand_window_days: int
) -> dict[str, Any]:
    """Align with agents.agent2_pipeline._build_params windows."""
    start_d = snap - timedelta(days=int(demand_window_days))
    start_90 = snap - timedelta(days=90)
    start_365 = snap - timedelta(days=365)
    if workflow_id == "UC-6":
        return {
            "demand_window_start": str(start_90),
            "demand_window_end": str(snap),
            "demand_window_days_effective": 90,
            "notes": "SQL uses 90-day window for cycle-count signals.",
        }
    if workflow_id == "UC-7":
        return {
            "demand_window_start": str(start_365),
            "demand_window_end": str(snap),
            "demand_window_days_effective": 365,
            "notes": "SQL uses 365-day window for ABC consumption.",
        }
    return {
        "demand_window_start": str(start_d),
        "demand_window_end": str(snap),
        "demand_window_days_effective": int(demand_window_days),
        "notes": None,
    }


def build_tool_plan(
    conn: duckdb.DuckDBPyConnection | None,
    routing: dict[str, Any],
) -> dict[str, Any]:
    """
    Return governed tool plan JSON:
    { "tool", "query", "kpi", "params" }

    When the route is not executable or required parameters are missing,
    tool/query/kpi are empty strings and params carry status + missing fields
    (no SQL run — caller should clarify first).
    """
    empty: dict[str, Any] = {"tool": "", "query": "", "kpi": "", "params": {}}

    wf = routing.get("workflow_id")
    if wf not in QUERY_BY_WORKFLOW:
        return empty

    raw_scope = routing.get("scope")
    scope = str(raw_scope).strip() if raw_scope is not None else None
    if scope == "":
        scope = None

    raw_dwd = routing.get("demand_window_days")
    if raw_dwd is None:
        demand_window_days = None
    else:
        try:
            demand_window_days = int(raw_dwd)
        except (TypeError, ValueError):
            demand_window_days = None
    try:
        top_n = int(routing.get("top_n") or 10)
    except (TypeError, ValueError):
        top_n = 10

    ok, missing = _params_complete(scope, demand_window_days, top_n)
    if not ok:
        return {
            "tool": "",
            "query": "",
            "kpi": "",
            "params": {
                "complete": False,
                "missing_parameters": missing,
                "location": scope if scope in VALID_SCOPES else None,
                "demand_window_days": demand_window_days,
                "top_n": top_n,
            },
        }

    query_id, _sql = QUERY_BY_WORKFLOW[wf]
    tool = f"sql_execute_{wf}"
    kpi = WORKFLOW_TO_KPI_CALCULATOR.get(wf, "")

    if conn is None:
        return {
            "tool": tool,
            "query": query_id,
            "kpi": kpi,
            "params": {
                "complete": True,
                "location": scope,
                "demand_window_days": demand_window_days,
                "top_n": top_n,
                "snapshot_date": None,
                "date_filter": routing.get("date_filter"),
            },
        }

    try:
        snap = _snapshot_date(conn)
    except Exception:
        return {
            "tool": tool,
            "query": query_id,
            "kpi": kpi,
            "params": {
                "complete": True,
                "location": scope,
                "demand_window_days": demand_window_days,
                "top_n": top_n,
                "snapshot_date": None,
                "date_filter": routing.get("date_filter"),
                "error": "snapshot_unavailable",
            },
        }

    window = _resolved_date_window(wf, snap, demand_window_days)
    params: dict[str, Any] = {
        "complete": True,
        "location": scope,
        "demand_window_days": demand_window_days,
        "top_n": top_n,
        "snapshot_date": str(snap),
        "date_filter": routing.get("date_filter"),
        **window,
    }

    return {"tool": tool, "query": query_id, "kpi": kpi, "params": params}
