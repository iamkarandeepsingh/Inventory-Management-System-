"""
Agent 2 — Tool execution pipeline (no LLM).
Executes approved SQL, deterministic KPI/rule enrichment, audit logging.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import duckdb

from config import KPI_VERSION, SQL_TEMPLATE_VERSION
from kpi_calculator import kpi_formula_text, version as kpi_version_str
from rule_engine import (
    _abc_rules,
    _anomaly_severity,
    _backorder_severity,
    _coverage_rules,
    _cycle_count_rules,
    _dos_rules,
    _slow_mover_rules,
    _stockout_severity,
    load_threshold_config,
    rule_engine_version,
)
from sql_templates import QUERY_BY_WORKFLOW
from tool_planner import build_tool_plan
from visualization_builder import build_visualization_package


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


def _build_params(
    workflow_id: str,
    scope: str,
    demand_window_days: int,
    top_n: int,
    snap: date,
) -> list[Any]:
    start_d = snap - timedelta(days=int(demand_window_days))
    start_90 = snap - timedelta(days=90)
    start_365 = snap - timedelta(days=365)
    if workflow_id == "UC-1":
        return [scope, scope, float(demand_window_days), start_d, int(top_n)]
    if workflow_id == "UC-2":
        return [scope, scope, int(top_n)]
    if workflow_id == "UC-3":
        return [float(demand_window_days), start_d, scope, scope, int(top_n)]
    if workflow_id == "UC-4":
        return [start_d, scope, scope, int(top_n)]
    if workflow_id == "UC-5":
        return [scope, scope, int(top_n)]
    if workflow_id == "UC-6":
        return [start_90, start_90, scope, scope, int(top_n)]
    if workflow_id == "UC-7":
        return [start_365, int(top_n)]
    if workflow_id == "UC-8":
        return [float(demand_window_days), start_d, scope, scope, int(top_n)]
    raise ValueError(f"Unknown workflow_id: {workflow_id}")


def _rows_to_dicts(cur: Any) -> list[dict[str, Any]]:
    cols = [d[0] for d in cur.description]
    out = []
    for row in cur.fetchall():
        out.append({cols[i]: row[i] for i in range(len(cols))})
    return out


def _enrich_findings(
    workflow_id: str,
    rows: list[dict[str, Any]],
    cfg: Any,
    query_id: str,
    snap: date,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    if workflow_id == "UC-6":
        scores = [float(r.get("priority_score") or 0) for r in rows]

    for idx, r in enumerate(rows, start=1):
        ev = {
            "query_id": query_id,
            "snapshot_date": str(snap),
            "records_used": len(rows),
        }
        if workflow_id == "UC-1":
            atp = float(r.get("atp") or 0)
            add = float(r.get("avg_daily_demand") or 0)
            score, action, rules = _stockout_severity(atp, add, cfg)
            key_kpi, kpi_val = "ATP", atp
        elif workflow_id == "UC-2":
            qty = float(r.get("backorder_qty") or 0)
            score, action, rules = _backorder_severity(qty, cfg)
            key_kpi, kpi_val = "Backorder value", float(r.get("backorder_value") or 0)
        elif workflow_id == "UC-3":
            dos = float(r.get("dos") or 0)
            score, action, rules = _dos_rules(dos, cfg)
            key_kpi, kpi_val = "DOS", dos
        elif workflow_id == "UC-4":
            mov = float(r.get("movement_qty") or 0)
            oh = float(r.get("on_hand_qty") or 0)
            cls = str(r.get("classification") or "")
            score, action, rules = _slow_mover_rules(mov, oh, cls, cfg)
            key_kpi, kpi_val = "Value at risk", float(r.get("value_at_risk") or 0)
        elif workflow_id == "UC-5":
            score, action, rules = _anomaly_severity()
            key_kpi, kpi_val = "Anomaly", str(r.get("anomaly_type") or "")
        elif workflow_id == "UC-6":
            ps = float(r.get("priority_score") or 0)
            score, action, rules = _cycle_count_rules(ps, scores, cfg)
            key_kpi, kpi_val = "Priority score", ps
        elif workflow_id == "UC-7":
            cum = float(r.get("cumulative_pct") or 0)
            score, action, rules = _abc_rules(cum, cfg)
            key_kpi, kpi_val = "Cumulative % / Class", f"{cum}% {r.get('abc_class')}"
        elif workflow_id == "UC-8":
            cov = float(r.get("coverage_days") or 0)
            lead = float(r.get("default_lead_time_days") or 0)
            score, action, rules = _coverage_rules(cov, lead, cfg)
            key_kpi, kpi_val = "Coverage days", cov
        else:
            continue

        loc = r.get("location_code")
        if loc is None and workflow_id == "UC-7":
            loc = "ALL"

        findings.append(
            {
                "rank": idx,
                "sku": r.get("sku"),
                "location": loc,
                "key_kpi_name": key_kpi,
                "key_kpi_value": kpi_val,
                "severity_score": score,
                "recommended_action": action,
                "rule_ids": rules,
                "raw": r,
                "evidence": ev,
            }
        )

    return findings


def _strip_raw_for_audit(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for f in findings:
        d = {k: v for k, v in f.items() if k != "raw"}
        out.append(d)
    return out


def execute_pipeline(
    conn: duckdb.DuckDBPyConnection,
    routing: dict[str, Any],
    session_id: str,
    user_message: str = "",
) -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    workflow_id = routing.get("workflow_id")
    if workflow_id not in QUERY_BY_WORKFLOW:
        return {
            "workflow_id": workflow_id,
            "run_id": run_id,
            "snapshot_date": None,
            "scope": routing.get("scope"),
            "parameters": {
                "demand_window_days": routing.get("demand_window_days"),
                "top_n": routing.get("top_n"),
            },
            "findings": [],
            "kpis_used": {
                "formula": kpi_formula_text(),
                "version": kpi_version_str(),
            },
            "tool_versions": {
                "sql_template": SQL_TEMPLATE_VERSION,
                "kpi_calculator": KPI_VERSION,
                "rule_engine": rule_engine_version(),
            },
            "row_count": 0,
            "error": {"code": "UNSUPPORTED_WORKFLOW", "message": "Workflow not executable"},
            "epsilon_applied": False,
            "tool_plan": build_tool_plan(None, routing),
        }

    tool_plan = build_tool_plan(conn, routing)
    if tool_plan["params"].get("complete") is False:
        return {
            "workflow_id": workflow_id,
            "run_id": run_id,
            "snapshot_date": None,
            "scope": routing.get("scope"),
            "parameters": {
                "demand_window_days": routing.get("demand_window_days"),
                "top_n": routing.get("top_n"),
            },
            "findings": [],
            "kpis_used": {
                "formula": kpi_formula_text(),
                "version": kpi_version_str(),
            },
            "tool_versions": {
                "sql_template": SQL_TEMPLATE_VERSION,
                "kpi_calculator": KPI_VERSION,
                "rule_engine": rule_engine_version(),
            },
            "row_count": 0,
            "error": {
                "code": "INCOMPLETE_PARAMETERS",
                "message": "Required parameters missing; clarify location or date window.",
            },
            "epsilon_applied": False,
            "tool_plan": tool_plan,
        }

    query_id, sql = QUERY_BY_WORKFLOW[workflow_id]
    scope = routing.get("scope") or "all"
    demand_window_days = int(routing.get("demand_window_days") or 30)
    top_n = int(routing.get("top_n") or 10)
    cfg = load_threshold_config(conn)
    tool_name = f"sql_execute_{workflow_id}"

    try:
        snap = _snapshot_date(conn)
    except Exception as e:
        return _error_response(
            run_id,
            workflow_id,
            routing,
            scope,
            demand_window_days,
            top_n,
            "DB_SNAPSHOT",
            str(e),
            tool_plan=tool_plan,
        )

    params = _build_params(workflow_id, scope, demand_window_days, top_n, snap)
    started = datetime.now(UTC)

    try:
        cur = conn.execute(sql, params)
        rows = _rows_to_dicts(cur)
    except Exception as e:
        _log_tool_call(
            conn,
            session_id,
            run_id,
            tool_name,
            {"sql_params": [str(p) for p in params], "query_id": query_id},
            None,
            "error",
            str(e),
        )
        return _error_response(
            run_id,
            workflow_id,
            routing,
            scope,
            demand_window_days,
            top_n,
            "SQL_ERROR",
            "Data temporarily unavailable, please retry",
            snap=snap,
            tool_plan=tool_plan,
        )

    findings = _enrich_findings(workflow_id, rows, cfg, query_id, snap)
    epsilon_applied = workflow_id in {"UC-3", "UC-4", "UC-8", "UC-1"}

    visualization = build_visualization_package(
        conn,
        rows,
        workflow_id,
        user_message,
        scope,
        demand_window_days,
        snap,
    )

    payload = {
        "workflow_id": workflow_id,
        "run_id": run_id,
        "snapshot_date": str(snap),
        "scope": scope,
        "parameters": {"demand_window_days": demand_window_days, "top_n": top_n},
        "findings": _strip_raw_for_audit(findings),
        "kpis_used": {"formula": kpi_formula_text(), "version": kpi_version_str()},
        "tool_versions": {
            "sql_template": SQL_TEMPLATE_VERSION,
            "kpi_calculator": KPI_VERSION,
            "rule_engine": rule_engine_version(),
        },
        "row_count": len(rows),
        "error": None,
        "epsilon_applied": epsilon_applied,
        "query_id": query_id,
        "started_at": started.isoformat().replace("+00:00", "Z"),
        "tool_plan": tool_plan,
        "visualization": visualization,
    }

    evidence_refs = {
        "query_id": query_id,
        "snapshot_date": str(snap),
        "run_id": run_id,
        "kpi_version": KPI_VERSION,
        "sql_template_version": SQL_TEMPLATE_VERSION,
        "rule_engine_version": rule_engine_version(),
    }
    _log_tool_call(
        conn,
        session_id,
        run_id,
        tool_name,
        {"routing": routing, "params": [str(p) for p in params]},
        payload,
        "ok",
        None,
        evidence_refs,
    )
    return payload


def _error_response(
    run_id: str,
    workflow_id: str | None,
    routing: dict[str, Any],
    scope: str,
    demand_window_days: int,
    top_n: int,
    code: str,
    message: str,
    snap: date | None = None,
    tool_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if tool_plan is None:
        tool_plan = build_tool_plan(None, routing)
    return {
        "workflow_id": workflow_id,
        "run_id": run_id,
        "snapshot_date": str(snap) if snap else None,
        "scope": scope,
        "parameters": {"demand_window_days": demand_window_days, "top_n": top_n},
        "findings": [],
        "kpis_used": {"formula": kpi_formula_text(), "version": kpi_version_str()},
        "tool_versions": {
            "sql_template": SQL_TEMPLATE_VERSION,
            "kpi_calculator": KPI_VERSION,
            "rule_engine": rule_engine_version(),
        },
        "row_count": 0,
        "error": {"code": code, "message": message},
        "epsilon_applied": False,
        "tool_plan": tool_plan,
    }


def _log_tool_call(
    conn: duckdb.DuckDBPyConnection,
    session_id: str,
    run_id: str,
    tool_name: str,
    input_obj: dict[str, Any],
    output_obj: dict[str, Any] | None,
    status: str,
    error_message: str | None,
    evidence_refs: dict[str, Any] | None = None,
) -> None:
    tcid = str(uuid.uuid4())
    ts = datetime.now(UTC)
    ev = evidence_refs or {
        "kpi_version": KPI_VERSION,
        "sql_template_version": SQL_TEMPLATE_VERSION,
        "rule_engine_version": rule_engine_version(),
        "run_id": run_id,
    }
    out_json = json.dumps(output_obj) if output_obj is not None else "{}"
    conn.execute(
        """
        INSERT INTO audit_tool_call (
            tool_call_id, session_id, timestamp, tool_name,
            input_json, output_json, evidence_refs, status, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            tcid,
            session_id,
            ts,
            f"{tool_name}|v2.1",
            json.dumps(input_obj),
            out_json,
            json.dumps(ev),
            status,
            error_message,
        ],
    )
