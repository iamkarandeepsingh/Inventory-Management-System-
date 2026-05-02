"""Role-based presentation: Auditor (audit trail), Analyst (insights), Admin (threshold detail)."""

from __future__ import annotations

import json
from typing import Any

import duckdb

from rule_engine import load_threshold_config


def audit_tool_call_tail(conn: duckdb.DuckDBPyConnection, session_id: str, limit: int = 30) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT tool_call_id, timestamp, tool_name, status, error_message,
               input_json, output_json, evidence_refs
        FROM audit_tool_call
        WHERE session_id = ?
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        [session_id, limit],
    ).fetchall()
    out: list[dict[str, Any]] = []
    for (
        tcid,
        ts,
        tool_name,
        status,
        err,
        inp,
        outp,
        ev,
    ) in rows:
        def _parse(j: Any) -> Any:
            if j is None:
                return None
            if isinstance(j, (dict, list)):
                return j
            try:
                return json.loads(j) if isinstance(j, str) else j
            except json.JSONDecodeError:
                return str(j)[:2000]

        out.append(
            {
                "tool_call_id": tcid,
                "timestamp": str(ts) if ts is not None else None,
                "tool_name": tool_name,
                "status": status,
                "error_message": err,
                "input": _parse(inp),
                "output": _parse(outp),
                "evidence_refs": _parse(ev),
            }
        )
    return out


def analyst_highlights(frontend: dict[str, Any] | None) -> dict[str, Any]:
    if not frontend:
        return {"bullets": [], "headline": "Run an analytics query to generate insight highlights."}
    rows = frontend.get("findings_table") or []
    esc = [r for r in rows if r.get("recommended_action") == "ESCALATE"]
    mon = [r for r in rows if r.get("recommended_action") == "MONITOR"]
    bullets: list[str] = []
    if esc:
        bullets.append(
            f"{len(esc)} finding(s) flagged ESCALATE — prioritize immediate supply or allocation review."
        )
    if mon:
        bullets.append(f"{len(mon)} finding(s) on MONITOR — schedule follow-up within the demand window.")
    if rows and not bullets:
        bullets.append("No critical escalations; review INVESTIGATE items for process tuning.")
    if not rows:
        bullets.append("No tabular findings for this run; see summary and evidence for context.")
    headline = "Operational insights" if rows else "Awaiting structured findings"
    return {"headline": headline, "bullets": bullets[:6]}


def build_explain(conn: duckdb.DuckDBPyConnection, routing: dict[str, Any], role: str) -> dict[str, Any]:
    cfg = load_threshold_config(conn)
    base: dict[str, Any] = {
        "rule_ids": [
            "RULE-ST-01",
            "RULE-ST-02",
            "RULE-ST-03",
            "RULE-ST-04",
            "RULE-ST-05",
            "RULE-DOS-01",
            "RULE-DOS-02",
            "RULE-CC-01",
        ],
        "kpi_formula_version": None,  # filled by caller
        "sql_template_version": None,
        "rule_engine_version": None,
        "parameters_applied": {
            "scope": routing.get("scope"),
            "demand_window_days": routing.get("demand_window_days"),
            "top_n": routing.get("top_n"),
            "date_filter": routing.get("date_filter"),
        },
    }
    if role == "Admin":
        base["thresholds_loaded"] = cfg.by_name
        base["kpi_threshold_explainer"] = [
            {
                "kpi_name": name,
                "threshold_low": spec.get("threshold_low"),
                "threshold_high": spec.get("threshold_high"),
                "param_json": spec.get("param_json"),
                "severity_weights": spec.get("severity_weights"),
            }
            for name, spec in sorted(cfg.by_name.items())
        ]
        base["admin_note"] = "Full KPI threshold configuration is visible for Admin role."
    elif role == "Auditor":
        base["thresholds_summary"] = {
            name: {
                "threshold_low": spec.get("threshold_low"),
                "threshold_high": spec.get("threshold_high"),
            }
            for name, spec in cfg.by_name.items()
        }
        base["auditor_note"] = "Numeric thresholds summarized; raw config rows available in audit exports."
    elif role == "Supervisor":
        base["supervisor_note"] = (
            "Read-only supervisory view: KPIs and findings are governed-tool only; "
            "threshold configuration changes require Admin. Use Insights for operational review."
        )
    else:
        base["analyst_note"] = (
            "Insights focus: use Findings and Recommendations. "
            "Switch to Admin for full KPI threshold documentation."
        )
    return base


def merge_explain_versions(explain: dict[str, Any], kpi_ver: str, sql_ver: str, re_ver: str) -> None:
    explain["kpi_formula_version"] = kpi_ver
    explain["sql_template_version"] = sql_ver
    explain["rule_engine_version"] = re_ver


def enrich_response_for_role(
    conn: duckdb.DuckDBPyConnection,
    session_id: str,
    role: str,
    out: dict[str, Any],
) -> None:
    """Mutates out with role-specific fields (auditor_extras / analyst_extras markers)."""
    out["user_role"] = role
    if role == "Auditor":
        out["auditor_extras"] = {
            "recent_tool_calls": audit_tool_call_tail(conn, session_id),
            "evidence_extension": {
                "routing": out.get("routing"),
                "tool_plan": out.get("tool_plan"),
                "intent_classification": (out.get("routing") or {}).get("intent_classification"),
            },
        }
    elif role == "Analyst":
        out["analyst_extras"] = analyst_highlights(out.get("frontend"))
        out["analyst_extras"]["presentation_mode"] = "insights_first"
    elif role == "Supervisor":
        ah = analyst_highlights(out.get("frontend"))
        out["supervisor_extras"] = {
            "read_only_mode": True,
            "presentation_mode": "insights_read_only",
            **ah,
        }
        tp = out.get("tool_plan")
        if isinstance(tp, dict) and tp.get("query"):
            redacted = {**tp, "query": "[redacted for Supervisor read-only view]"}
            out["tool_plan"] = redacted
    elif role == "Admin":
        out["admin_extras"] = {
            "kpi_threshold_docs_enabled": True,
            "message": "Explain tab includes full threshold and weight configuration.",
        }
