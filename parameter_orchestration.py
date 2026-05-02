"""Pre-tool parameter validation (SRS FR2.2) — no SQL until scope + demand are explicit."""

from __future__ import annotations

from typing import Any

from config import VALID_SCOPES
from sql_templates import QUERY_BY_WORKFLOW

EXECUTABLE_WORKFLOWS = frozenset(QUERY_BY_WORKFLOW.keys())

DEMAND_WINDOW_PRESETS: tuple[int, ...] = (7, 14, 30, 60, 90)


def _scope_normalized(scope: str | None) -> str | None:
    if scope is None:
        return None
    s = str(scope).strip()
    return s if s else None


def evaluate_tool_execution_readiness(
    *,
    scope: str | None,
    demand_window_days: int | None,
    parameters_confirmed: bool,
    routing: dict[str, Any],
) -> tuple[bool, list[str], str, dict[str, Any]]:
    """
    Returns (ready, missing_codes, user_message, clarification_context).
    When ready is False, caller must not run SQL / KPI pipeline.
    """
    wf = routing.get("workflow_id")
    if wf not in EXECUTABLE_WORKFLOWS:
        return True, [], "", {}

    missing: list[str] = []
    s = _scope_normalized(scope)
    if s is None:
        missing.append("location_scope")
    elif s not in VALID_SCOPES:
        missing.append("location_scope_invalid")

    if demand_window_days is None:
        missing.append("demand_window_days")
    elif int(demand_window_days) <= 0:
        missing.append("demand_window_days_invalid")

    ctx: dict[str, Any] = {
        "missing_parameters": list(missing),
        "location_codes": sorted(VALID_SCOPES),
        "demand_window_presets": list(DEMAND_WINDOW_PRESETS),
        "pending_workflow_id": wf,
    }

    if missing:
        msg = _message_for_missing(missing, wf)
        return False, missing, msg, ctx

    if s == "all" and not parameters_confirmed:
        miss = ["confirm_all_locations"]
        ctx["missing_parameters"] = miss
        msg = (
            "You selected **all locations** (network-wide scope). "
            "To avoid silent defaults, enable **Confirm parameters for this run** below, then send again — "
            "or pick a single location from the scope list."
        )
        return False, miss, msg, ctx

    return True, [], "", {}


def _message_for_missing(missing: list[str], workflow_id: str | None) -> str:
    parts: list[str] = []
    if "location_scope" in missing:
        locs = ", ".join(sorted(VALID_SCOPES))
        parts.append(
            f"**Location scope** is required before running workflow {workflow_id}. "
            f"Pick one in the UI: {locs}."
        )
    if "location_scope_invalid" in missing:
        parts.append(
            "The location scope sent is not recognized. Choose a valid site code or **all** from the list."
        )
    if "demand_window_days" in missing:
        opts = ", ".join(str(x) for x in DEMAND_WINDOW_PRESETS)
        parts.append(
            f"**Demand window (days)** is required. Select how many days of demand history to use ({opts})."
        )
    if "demand_window_days_invalid" in missing:
        parts.append("Demand window must be a positive number of days.")
    return "\n\n".join(parts) if parts else "Additional parameters are required before analysis can run."


def pending_payload_for_session(
    routing: dict[str, Any],
    missing: list[str],
) -> dict[str, Any]:
    return {
        "workflow_id": routing.get("workflow_id"),
        "routing_snapshot": dict(routing),
        "missing_parameters": list(missing),
    }
