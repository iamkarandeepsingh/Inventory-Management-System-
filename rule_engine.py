"""Versioned rule engine — thresholds loaded from config_kpi_threshold (never hardcoded)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import duckdb

from config import EPSILON, KPI_VERSION, RULE_ENGINE_VERSION


@dataclass
class ThresholdConfig:
    by_name: dict[str, dict[str, Any]]


def load_threshold_config(conn: duckdb.DuckDBPyConnection) -> ThresholdConfig:
    rows = conn.execute(
        """
        SELECT kpi_name, param_json, threshold_low, threshold_high, severity_weights
        FROM config_kpi_threshold
        ORDER BY kpi_name, effective_from DESC
        """
    ).fetchall()
    by_name: dict[str, dict[str, Any]] = {}
    for name, pj, low, high, sw in rows:
        if name in by_name:
            continue
        by_name[name] = {
            "param_json": json.loads(pj) if isinstance(pj, str) else (pj or {}),
            "threshold_low": float(low) if low is not None else None,
            "threshold_high": float(high) if high is not None else None,
            "severity_weights": json.loads(sw) if isinstance(sw, str) else (sw or {}),
        }
    return ThresholdConfig(by_name=by_name)


def _stockout_severity(
    atp: float, avg_daily_demand: float, cfg: ThresholdConfig
) -> tuple[float, str, list[str]]:
    """Returns severity_score, recommended_action, rule_ids triggered."""
    w = cfg.by_name.get("STOCKOUT_SEVERITY", {}).get("severity_weights", {})
    aw = float(w.get("atp_weight", 0.6))
    dw = float(w.get("demand_weight", 0.4))
    rules: list[str] = []

    if atp < 0:
        rules.append("RULE-ST-01")
        atp_comp = min(1.0, abs(atp) / 100.0)
    elif atp == 0 and avg_daily_demand > EPSILON:
        rules.append("RULE-ST-02")
        atp_comp = 0.65
    else:
        atp_comp = 0.25

    demand_comp = min(1.0, max(avg_daily_demand, 0.0) / 20.0)
    score = aw * atp_comp + dw * demand_comp
    score = min(1.0, max(0.0, score))

    if score >= 0.8:
        rules.append("RULE-ST-03")
        action = "ESCALATE"
    elif score >= 0.5:
        rules.append("RULE-ST-04")
        action = "MONITOR"
    else:
        rules.append("RULE-ST-05")
        action = "INVESTIGATE"
    return round(score, 4), action, rules


def _backorder_severity(qty: float, cfg: ThresholdConfig) -> tuple[float, str, list[str]]:
    w = cfg.by_name.get("BACKORDER_SEVERITY", {}).get("severity_weights", {})
    qw = float(w.get("qty_weight", 1.0))
    score = min(1.0, max(0.0, qty / 80.0)) * qw
    score = min(1.0, score)
    rules = []
    if score >= 0.8:
        rules.append("RULE-ST-03")
        action = "ESCALATE"
    elif score >= 0.5:
        rules.append("RULE-ST-04")
        action = "MONITOR"
    else:
        rules.append("RULE-ST-05")
        action = "INVESTIGATE"
    return round(score, 4), action, rules


def _dos_rules(dos: float, cfg: ThresholdConfig) -> tuple[float, str, list[str]]:
    high = cfg.by_name.get("DOS", {}).get("threshold_high")
    high = float(high) if high is not None else 60.0
    rules = []
    if dos > high:
        rules.append("RULE-DOS-01")
        score = min(1.0, (dos - high) / max(high, EPSILON))
        action = "MONITOR" if score < 0.8 else "ESCALATE"
    else:
        score = 0.3
        action = "INVESTIGATE"
    if score >= 0.8:
        rules.append("RULE-ST-03")
        action = "ESCALATE"
    elif score >= 0.5 and "RULE-ST-04" not in rules:
        rules.append("RULE-ST-04")
    return round(score, 4), action, rules


def _slow_mover_rules(
    movement_qty: float, on_hand: float, classification: str, cfg: ThresholdConfig
) -> tuple[float, str, list[str]]:
    rules = []
    if movement_qty <= EPSILON and on_hand > 0:
        rules.append("RULE-DOS-02")
        score = 0.85 if classification == "Dead Stock" else 0.55
    else:
        score = 0.45
    if score >= 0.8:
        rules.append("RULE-ST-03")
        action = "ESCALATE"
    elif score >= 0.5:
        rules.append("RULE-ST-04")
        action = "MONITOR"
    else:
        rules.append("RULE-ST-05")
        action = "INVESTIGATE"
    return round(score, 4), action, rules


def _anomaly_severity() -> tuple[float, str, list[str]]:
    return 0.9, "ESCALATE", ["RULE-ST-01"]


def _cycle_count_rules(
    priority_score: float, scores: list[float], _cfg: ThresholdConfig
) -> tuple[float, str, list[str]]:
    rules = []
    if not scores:
        return round(priority_score, 4), "INVESTIGATE", ["RULE-ST-05"]
    arr = sorted(scores)
    q_idx = max(0, int(0.75 * (len(arr) - 1)))
    quartile = arr[q_idx]
    if priority_score >= quartile:
        rules.append("RULE-CC-01")
    if priority_score >= 0.8:
        rules.append("RULE-ST-03")
        action = "ESCALATE"
    elif priority_score >= 0.5:
        rules.append("RULE-ST-04")
        action = "MONITOR"
    else:
        rules.append("RULE-ST-05")
        action = "INVESTIGATE"
    return round(priority_score, 4), action, rules


def _abc_rules(cumulative_pct: float, cfg: ThresholdConfig) -> tuple[float, str, list[str]]:
    p = cfg.by_name.get("ABC", {}).get("param_json", {})
    a_cut = float(p.get("A", 80))
    b_cut = float(p.get("B", 95))
    if cumulative_pct <= a_cut:
        score = 0.9
        action = "ESCALATE"
    elif cumulative_pct <= b_cut:
        score = 0.6
        action = "MONITOR"
    else:
        score = 0.35
        action = "INVESTIGATE"
    return round(score, 4), action, []


def _coverage_rules(
    coverage_days: float, lead_days: float, cfg: ThresholdConfig
) -> tuple[float, str, list[str]]:
    if coverage_days < lead_days:
        gap = (lead_days - coverage_days) / max(lead_days, EPSILON)
        score = min(1.0, 0.5 + gap * 0.5)
    else:
        score = 0.35
    if score >= 0.8:
        return round(score, 4), "ESCALATE", ["RULE-ST-03"]
    if score >= 0.5:
        return round(score, 4), "MONITOR", ["RULE-ST-04"]
    return round(score, 4), "INVESTIGATE", ["RULE-ST-05"]


def rule_engine_version() -> str:
    return RULE_ENGINE_VERSION


def kpi_version() -> str:
    return KPI_VERSION
