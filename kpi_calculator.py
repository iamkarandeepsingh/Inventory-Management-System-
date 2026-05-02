"""Deterministic KPI helpers (v2.1). Epsilon for division guards."""

from __future__ import annotations

from config import EPSILON, KPI_VERSION


def safe_div(numer: float, denom: float) -> tuple[float, bool]:
    """Returns (value, epsilon_applied)."""
    d = max(float(denom), EPSILON)
    applied = abs(float(denom)) < EPSILON
    return numer / d, applied


def atp(on_hand: float, allocated: float, reserved: float) -> float:
    return float(on_hand) - float(allocated) - float(reserved)


def avg_daily_demand(sum_demand: float, window_days: int) -> tuple[float, bool]:
    return safe_div(sum_demand, float(window_days))


def dos(on_hand: float, add: float) -> tuple[float, bool]:
    return safe_div(float(on_hand), float(add))


def coverage_days(on_hand: float, inbound: float, add: float) -> tuple[float, bool]:
    return safe_div(float(on_hand) + float(inbound), float(add))


def kpi_formula_text() -> str:
    return (
        "ATP = on_hand_qty - allocated_qty - reserved_qty; "
        "ADD = SUM(demand_qty over window_days) / window_days; "
        "DOS = on_hand_qty / MAX(ADD, 0.001); "
        "coverage_days = (on_hand_qty + inbound_open_qty) / MAX(ADD, 0.001)"
    )


def version() -> str:
    return KPI_VERSION
