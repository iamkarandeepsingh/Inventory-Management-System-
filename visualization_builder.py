"""
Governed visualization payloads from approved SQL rows or explicit sample data only.

KPIs and findings remain tool-sourced; graphs are a separate channel (never mix sample
series into KPI numbers).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import duckdb

VIZ_VERSION = "v1.0"

SAMPLE_DISCLAIMER = (
    "This visualization is generated using sample data to illustrate the expected analytical output. "
    "No real data was found for the selected parameters."
)

NO_DATA_FRIENDLY = (
    "No data available for this selection. Here is a representative visualization to illustrate expected insights."
)

TREND_KEYWORDS = ("trend", "over time", "time series", "daily demand", "historical", "timeline")
PIE_KEYWORDS = ("abc", "classification", "distribution", "pie", "breakdown", "share", "split")
TABLE_KEYWORDS = ("table", "list", "anomaly", "stockout list", "rows")


def _wants_line(user_message: str) -> bool:
    low = user_message.lower()
    return any(k in low for k in TREND_KEYWORDS)


def _wants_pie(user_message: str, workflow_id: str) -> bool:
    low = user_message.lower()
    if workflow_id == "UC-7":
        return True
    return any(k in low for k in PIE_KEYWORDS)


def _wants_table(user_message: str, workflow_id: str) -> bool:
    low = user_message.lower()
    if workflow_id == "UC-5":
        return True
    return any(k in low for k in TABLE_KEYWORDS)


def _fetch_demand_trend_series(
    conn: duckdb.DuckDBPyConnection,
    snap: date,
    scope: str,
    demand_window_days: int,
) -> list[dict[str, Any]]:
    """Approved read-only aggregate — same location filter pattern as SQL templates."""
    start_d = snap - timedelta(days=int(demand_window_days))
    cur = conn.execute(
        """
        SELECT d.date, SUM(d.demand_qty)::DOUBLE AS total_demand
        FROM fact_demand_daily d
        JOIN dim_location l ON d.location_id = l.location_id
        WHERE d.date >= ? AND (? = 'all' OR l.location_code = ?)
        GROUP BY d.date
        ORDER BY d.date
        """,
        [start_d, scope, scope],
    )
    out: list[dict[str, Any]] = []
    for row in cur.fetchall():
        d, v = row[0], row[1]
        ds = d.isoformat() if hasattr(d, "isoformat") else str(d)
        out.append({"x": ds, "y": float(v or 0)})
    return out


def _bar_metric_from_row(workflow_id: str, r: dict[str, Any]) -> tuple[str, float]:
    if workflow_id == "UC-1":
        return "ATP", float(r.get("atp") or 0)
    if workflow_id == "UC-2":
        return "Backorder value", float(r.get("backorder_value") or 0)
    if workflow_id == "UC-3":
        return "DOS", float(r.get("dos") or 0)
    if workflow_id == "UC-4":
        return "Value at risk", float(r.get("value_at_risk") or 0)
    if workflow_id == "UC-6":
        return "Priority score", float(r.get("priority_score") or 0)
    if workflow_id == "UC-8":
        return "Coverage days", float(r.get("coverage_days") or 0)
    return "Metric", 0.0


def _real_viz_from_rows(
    conn: duckdb.DuckDBPyConnection,
    rows: list[dict[str, Any]],
    workflow_id: str,
    user_message: str,
    scope: str,
    demand_window_days: int,
    snap: date,
) -> dict[str, Any]:
    if _wants_line(user_message):
        series = _fetch_demand_trend_series(conn, snap, scope, demand_window_days)
        if series:
            return {
                "graph_type": "line",
                "title": "Aggregated daily demand (approved query)",
                "x_axis": "Date",
                "y_axis": "Total demand qty",
                "data": series,
                "sample_data": False,
                "disclaimer": None,
                "viz_version": VIZ_VERSION,
            }

    if _wants_pie(user_message, workflow_id) and workflow_id == "UC-7":
        buckets: dict[str, float] = {}
        for r in rows:
            cls = str(r.get("abc_class") or "Unknown")
            buckets[cls] = buckets.get(cls, 0.0) + 1.0
        if buckets:
            data = [{"label": k, "value": v} for k, v in sorted(buckets.items())]
            return {
                "graph_type": "pie",
                "title": "ABC classification mix (row counts in result set)",
                "x_axis": "Class",
                "y_axis": "Count",
                "data": data,
                "sample_data": False,
                "disclaimer": None,
                "viz_version": VIZ_VERSION,
            }

    if _wants_table(user_message, workflow_id) and workflow_id == "UC-5":
        data: list[dict[str, Any]] = []
        for r in rows[:50]:
            data.append(
                {
                    "sku": r.get("sku"),
                    "location_code": r.get("location_code"),
                    "anomaly_type": r.get("anomaly_type"),
                    "on_hand_qty": r.get("on_hand_qty"),
                    "unit_cost": r.get("unit_cost"),
                }
            )
        return {
            "graph_type": "table",
            "title": "Anomaly findings (tool rows)",
            "x_axis": "",
            "y_axis": "",
            "data": data,
            "sample_data": False,
            "disclaimer": None,
            "viz_version": VIZ_VERSION,
        }

    # Default: horizontal bar by SKU / metric
    data = []
    for r in rows[:25]:
        sku = str(r.get("sku") or "?")
        label = sku[:18] + ("…" if len(sku) > 18 else "")
        _, y = _bar_metric_from_row(workflow_id, r)
        data.append({"label": label, "value": y})
    name, _ = _bar_metric_from_row(workflow_id, rows[0] if rows else {})
    return {
        "graph_type": "bar",
        "title": f"{name} by item (top tool rows)",
        "x_axis": "SKU",
        "y_axis": name,
        "data": data,
        "sample_data": False,
        "disclaimer": None,
        "viz_version": VIZ_VERSION,
    }


def _sample_viz(workflow_id: str, user_message: str) -> dict[str, Any]:
    """Synthetic data for illustration only — never merged into KPIs."""
    if _wants_line(user_message) or workflow_id in {"UC-1", "UC-3", "UC-4", "UC-8"}:
        data = [{"x": f"Day {i + 1}", "y": float(80 + (i * 7) % 45 + i * 0.5)} for i in range(14)]
        return {
            "graph_type": "line",
            "title": "[Sample] Illustrative demand trend",
            "x_axis": "Period",
            "y_axis": "Units (demo)",
            "data": data,
            "sample_data": True,
            "disclaimer": SAMPLE_DISCLAIMER,
            "viz_version": VIZ_VERSION,
        }
    if _wants_pie(user_message, workflow_id) or workflow_id == "UC-7":
        return {
            "graph_type": "pie",
            "title": "[Sample] ABC-style distribution",
            "x_axis": "Class",
            "y_axis": "Share",
            "data": [
                {"label": "A", "value": 12},
                {"label": "B", "value": 28},
                {"label": "C", "value": 45},
            ],
            "sample_data": True,
            "disclaimer": SAMPLE_DISCLAIMER,
            "viz_version": VIZ_VERSION,
        }
    if _wants_table(user_message, workflow_id) or workflow_id == "UC-5":
        return {
            "graph_type": "table",
            "title": "[Sample] Anomaly-style listing",
            "x_axis": "",
            "y_axis": "",
            "data": [
                {"sku": "DEMO-001", "location_code": "DC-000", "anomaly_type": "NEG_QTY", "detail": "Synthetic row"},
                {"sku": "DEMO-002", "location_code": "DC-000", "anomaly_type": "COST", "detail": "Synthetic row"},
            ],
            "sample_data": True,
            "disclaimer": SAMPLE_DISCLAIMER,
            "viz_version": VIZ_VERSION,
        }
    return {
        "graph_type": "bar",
        "title": "[Sample] Illustrative stock / KPI bars",
        "x_axis": "Item",
        "y_axis": "Demo value",
        "data": [
            {"label": "SKU-A", "value": 42},
            {"label": "SKU-B", "value": 28},
            {"label": "SKU-C", "value": 65},
            {"label": "SKU-D", "value": 19},
            {"label": "SKU-E", "value": 53},
        ],
        "sample_data": True,
        "disclaimer": SAMPLE_DISCLAIMER,
        "viz_version": VIZ_VERSION,
    }


def build_visualization_package(
    conn: duckdb.DuckDBPyConnection | None,
    rows: list[dict[str, Any]],
    workflow_id: str,
    user_message: str,
    scope: str,
    demand_window_days: int,
    snap: date | None,
) -> dict[str, Any]:
    """
    Build governed visualization dict (graph_type, title, axes, data, sample_data, disclaimer).
    """
    if not rows:
        return _sample_viz(workflow_id, user_message)

    if conn is None or snap is None:
        return _sample_viz(workflow_id, user_message)

    return _real_viz_from_rows(conn, rows, workflow_id, user_message, scope, demand_window_days, snap)
