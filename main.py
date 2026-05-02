"""
FastAPI application — governed inventory AI agent (Agent 1 + Agent 2).
"""

from __future__ import annotations

import csv
import io
import json
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from auth import authenticate_user, create_access_token, decode_access_token
from agents.agent1_router import (
    AMBIGUOUS_STOCK_CLARIFY,
    GREETING_REPLY,
    INJECTION_REPLY,
    OUT_OF_SCOPE_REPLY,
    SUPPORTED_WORKFLOWS_TEXT,
    compose_narrative,
    merge_routing_with_ui,
    route_intent,
    try_greeting_response,
)
from agents.agent2_pipeline import execute_pipeline
from bootstrap_data import init_database, print_startup_stats
from config import APP_VERSION, DUCKDB_PATH, KPI_VERSION, SQL_TEMPLATE_VERSION, VALID_SCOPES
from rule_engine import rule_engine_version
from parameter_orchestration import (
    DEMAND_WINDOW_PRESETS,
    EXECUTABLE_WORKFLOWS,
    evaluate_tool_execution_readiness,
    pending_payload_for_session,
)
from session_store import (
    get_pending_tool,
    get_session_payload,
    save_pending_tool,
    save_session_payload,
)
from role_enrichment import (
    build_explain as _role_build_explain,
    enrich_response_for_role,
    merge_explain_versions,
)
from tool_planner import build_tool_plan
from visualization_builder import NO_DATA_FRIENDLY


def _coerce_user_visible_text(value: Any, agent2: dict[str, Any] | None) -> str:
    """Reject empty or bogus LLM/client strings like 'undefined' / 'null'."""
    if value is None:
        s = ""
    else:
        s = str(value).strip()
    if s and s.lower() not in ("undefined", "null"):
        return s
    if agent2:
        from agents.agent1_router import _deterministic_narrative

        return _deterministic_narrative(agent2)
    return (
        "The assistant reply could not be displayed. "
        "Try another question or check the supported inventory workflows."
    )


def _apply_safe_messages(out: dict[str, Any], agent2: dict[str, Any] | None) -> None:
    if "narrative" in out:
        out["narrative"] = _coerce_user_visible_text(out.get("narrative"), agent2)
    if "user_message" in out:
        out["user_message"] = _coerce_user_visible_text(out.get("user_message"), agent2)


def _finalize_chat_out(out: dict[str, Any]) -> None:
    """Duplicate narrative for thin clients that read message/assistant_message only."""
    n = out.get("narrative")
    if isinstance(n, str):
        out["assistant_message"] = n
        out["message"] = n


def _attach_tool_plan(
    out: dict[str, Any],
    conn: duckdb.DuckDBPyConnection,
    routing: dict[str, Any],
    agent2: dict[str, Any] | None,
) -> None:
    """Expose governed tool selection JSON: tool, query, kpi, params."""
    if agent2 and isinstance(agent2.get("tool_plan"), dict):
        out["tool_plan"] = agent2["tool_plan"]
    else:
        out["tool_plan"] = build_tool_plan(conn, routing)


def _make_explain(conn: duckdb.DuckDBPyConnection, routing: dict[str, Any], role: str) -> dict[str, Any]:
    ex = _role_build_explain(conn, routing, role)
    merge_explain_versions(ex, KPI_VERSION, SQL_TEMPLATE_VERSION, rule_engine_version())
    return ex


def _attach_role_context(
    conn: duckdb.DuckDBPyConnection,
    session_id: str,
    user_role: str,
    out: dict[str, Any],
) -> None:
    enrich_response_for_role(conn, session_id, user_role, out)


_db_lock = threading.Lock()
_conn: duckdb.DuckDBPyConnection | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _conn
    print(f"Initializing DuckDB at {DUCKDB_PATH} …")
    _conn = init_database()
    print("Table row counts:")
    print_startup_stats(_conn)
    print("Startup complete.")
    yield
    if _conn is not None:
        _conn.close()
        _conn = None


app = FastAPI(
    title="Governed Inventory AI Agent",
    version=APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8001",
        "http://127.0.0.1:8001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _persist_session(session_id: str, out: dict[str, Any], user_id: int, username: str) -> None:
    out["authenticated_user_id"] = user_id
    out["authenticated_username"] = username
    save_session_payload(session_id, out)


def _export_owner_ok(data: dict[str, Any], user_id: int) -> bool:
    owner = data.get("authenticated_user_id")
    if owner is None:
        return False
    try:
        return int(owner) == int(user_id)
    except (TypeError, ValueError):
        return False


@app.middleware("http")
async def _jwt_auth_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)
    path = request.url.path
    p = path.rstrip("/") or "/"
    if not p.startswith("/api"):
        return await call_next(request)
    if p == "/api/health":
        return await call_next(request)
    if p == "/api/auth/login" and request.method == "POST":
        return await call_next(request)
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    token = auth[7:].strip()
    payload = decode_access_token(token)
    if not payload:
        return JSONResponse({"detail": "Invalid or expired token"}, status_code=401)
    try:
        request.state.user_id = int(str(payload.get("sub") or "0"))
    except ValueError:
        return JSONResponse({"detail": "Invalid token subject"}, status_code=401)
    request.state.username = str(payload.get("username") or "")
    request.state.role = str(payload.get("role") or "Analyst")
    return await call_next(request)


@app.middleware("http")
async def _no_store_chat_and_index(request: Request, call_next):
    response = await call_next(request)
    p = request.url.path
    if p == "/" or p.startswith("/assets/") or p.rstrip("/").endswith("index.html"):
        response.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
    if p == "/api/chat" and request.method == "POST":
        response.headers["Cache-Control"] = "no-store"
    return response


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    scope: str | None = None
    demand_window_days: int | None = None
    session_id: str = "default"
    parameters_confirmed: bool = False

    @field_validator("scope", mode="before")
    @classmethod
    def scope_normalize(cls, v: Any) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None

    @field_validator("demand_window_days", mode="before")
    @classmethod
    def demand_window_ok(cls, v: Any) -> int | None:
        """Unset stays None — no silent default (SRS FR2.2)."""
        if v is None:
            return None
        if isinstance(v, bool):
            return None
        if isinstance(v, str) and v.strip().isdigit():
            n = int(v.strip())
        else:
            try:
                n = int(v)
            except (TypeError, ValueError):
                return None
        return n if n > 0 else None


def get_conn() -> duckdb.DuckDBPyConnection:
    global _conn
    if _conn is None:
        raise RuntimeError("Database not initialized")
    return _conn


def _touch_session(conn: duckdb.DuckDBPyConnection, session_id: str, user_id: int, user_role: str) -> None:
    row = conn.execute(
        "SELECT 1 FROM audit_chat_session WHERE session_id = ?",
        [session_id],
    ).fetchone()
    if row:
        conn.execute(
            """
            UPDATE audit_chat_session
            SET ended_at = NULL, app_version = ?, user_id = ?, user_role = ?
            WHERE session_id = ?
            """,
            [APP_VERSION, user_id, user_role, session_id],
        )
    else:
        conn.execute(
            """
            INSERT INTO audit_chat_session (session_id, user_id, user_role, started_at, ended_at, app_version)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, NULL, ?)
            """,
            [session_id, user_id, user_role, APP_VERSION],
        )


def _log_guard_event(
    conn: duckdb.DuckDBPyConnection,
    session_id: str,
    tool_name: str,
    input_obj: dict[str, Any],
    output_obj: dict[str, Any],
    status: str,
    err: str | None = None,
) -> None:
    tcid = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO audit_tool_call (
            tool_call_id, session_id, timestamp, tool_name,
            input_json, output_json, evidence_refs, status, error_message
        ) VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?)
        """,
        [
            tcid,
            session_id,
            f"{tool_name}|v2.1",
            json.dumps(input_obj),
            json.dumps(output_obj),
            json.dumps({"kpi_version": KPI_VERSION, "sql_template": SQL_TEMPLATE_VERSION}),
            status,
            err,
        ],
    )


def _action_rank(action: str) -> int:
    return {"ESCALATE": 0, "MONITOR": 1, "INVESTIGATE": 2}.get(action, 3)


def _build_executive_insights(
    findings: list[dict[str, Any]],
    workflow_id: str | None,
    scope: str,
    row_count: int,
) -> dict[str, Any]:
    """Deterministic summary metrics from tool rows only (no LLM, no fabricated SKUs)."""
    wf_titles = {
        "UC-1": "Stockout triage",
        "UC-2": "Backorder analysis",
        "UC-3": "Overstock / days of supply",
        "UC-4": "Slow movers",
        "UC-5": "Data anomalies",
        "UC-6": "Cycle count priority",
        "UC-7": "ABC classification",
        "UC-8": "On-order coverage",
    }
    title = wf_titles.get(workflow_id or "", workflow_id or "Analysis")
    if row_count == 0:
        return {
            "headline": f"{title}",
            "subhead": "No rows matched the approved query for the current scope and window.",
            "metrics": [{"label": "Records", "value": "0"}],
            "bullets": [
                "Adjust location scope or demand window, or run a different governed workflow.",
            ],
            "scope_echo": scope,
            "source": "tool_result",
        }
    esc = sum(1 for f in findings if f.get("recommended_action") == "ESCALATE")
    mon = sum(1 for f in findings if f.get("recommended_action") == "MONITOR")
    inv = sum(1 for f in findings if f.get("recommended_action") == "INVESTIGATE")
    sev_vals = [float(f.get("severity_score") or 0) for f in findings]
    avg_sev = sum(sev_vals) / len(sev_vals) if sev_vals else 0.0
    top = findings[0] if findings else {}
    bullets: list[str] = []
    if esc:
        bullets.append(f"{esc} finding(s) flagged ESCALATE — prioritize supply and allocation review.")
    if mon:
        bullets.append(f"{mon} finding(s) on MONITOR — track within the active demand window.")
    if inv and not bullets:
        bullets.append(f"{inv} finding(s) for INVESTIGATE — validate data and process exceptions.")
    if top.get("sku"):
        bullets.append(
            f"Highest-ranked row: SKU {top.get('sku')} @ {top.get('location')} "
            f"(severity {top.get('severity_score')})."
        )
    return {
        "headline": f"{title}",
        "subhead": f"{row_count} governed row(s) · scope: {scope}",
        "metrics": [
            {"label": "Records", "value": str(row_count)},
            {"label": "ESCALATE", "value": str(esc)},
            {"label": "MONITOR", "value": str(mon)},
            {"label": "INVESTIGATE", "value": str(inv)},
            {"label": "Avg severity", "value": f"{avg_sev:.3f}"},
        ],
        "bullets": bullets[:6],
        "scope_echo": scope,
        "source": "tool_result",
    }


def _build_recommendations(findings: list[dict[str, Any]]) -> list[str]:
    ranked = sorted(findings, key=lambda f: (_action_rank(f.get("recommended_action", "")), f.get("rank", 0)))
    out: list[str] = []
    for i, f in enumerate(ranked, start=1):
        sku = f.get("sku")
        loc = f.get("location")
        act = f.get("recommended_action")
        out.append(f"{i}. [{act}] SKU {sku} @ {loc} — review per governance rules.")
    return out


def _build_frontend_cards(
    agent2: dict[str, Any],
    narrative: str,
    routing: dict[str, Any],
) -> dict[str, Any]:
    findings = agent2.get("findings") or []
    rows = []
    for f in findings:
        rows.append(
            {
                "rank": f.get("rank"),
                "sku": f.get("sku"),
                "location": f.get("location"),
                "key_kpi": f"{f.get('key_kpi_name')}: {f.get('key_kpi_value')}",
                "severity_score": f.get("severity_score"),
                "recommended_action": f.get("recommended_action"),
                "action_color": {
                    "ESCALATE": "red",
                    "MONITOR": "yellow",
                    "INVESTIGATE": "gray",
                }.get(f.get("recommended_action"), "gray"),
            }
        )
    return {
        "summary": narrative,
        "findings_table": rows,
        "executive_insights": _build_executive_insights(
            findings,
            agent2.get("workflow_id"),
            str(routing.get("scope") or "all"),
            int(agent2.get("row_count") or 0),
        ),
        "kpis_used": agent2.get("kpis_used"),
        "recommendations": _build_recommendations(findings),
        "evidence": {
            "query_id": agent2.get("query_id"),
            "run_id": agent2.get("run_id"),
            "snapshot_date": agent2.get("snapshot_date"),
            "records_used": agent2.get("row_count"),
            "tool_versions": agent2.get("tool_versions"),
        },
        "workflow_id": agent2.get("workflow_id"),
        "scope": routing.get("scope"),
        "demand_window_days": routing.get("demand_window_days"),
        "visualization": agent2.get("visualization"),
    }


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


@app.post("/api/auth/login")
def login(body: LoginRequest) -> JSONResponse:
    with _db_lock:
        conn = get_conn()
        row = authenticate_user(conn, body.username, body.password)
    if not row:
        return JSONResponse({"detail": "Invalid username or password"}, status_code=401)
    token = create_access_token(
        user_id=int(row["user_id"]),
        username=str(row["username"]),
        role=str(row["role"]),
    )
    return JSONResponse(
        {
            "access_token": token,
            "token_type": "bearer",
            "user_id": row["user_id"],
            "username": row["username"],
            "role": row["role"],
        }
    )


@app.get("/api/auth/me")
def auth_me(request: Request) -> dict[str, Any]:
    return {
        "user_id": getattr(request.state, "user_id", None),
        "username": getattr(request.state, "username", ""),
        "role": getattr(request.state, "role", "Analyst"),
    }


@app.get("/api/health")
def health() -> dict[str, Any]:
    try:
        with _db_lock:
            c = get_conn()
            c.execute("SELECT 1").fetchone()
        db_ok = "connected"
    except Exception:
        db_ok = "error"
    return {
        "status": "ok" if db_ok == "connected" else "degraded",
        "db": db_ok,
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "app_version": APP_VERSION,
    }


@app.post("/api/chat")
def chat(request: Request, body: ChatRequest) -> JSONResponse:
    user_id = int(getattr(request.state, "user_id", 0))
    username = str(getattr(request.state, "username", ""))
    role = str(getattr(request.state, "role", "Analyst"))
    try:
        with _db_lock:
            conn = get_conn()
            _touch_session(conn, body.session_id, user_id, role)

            greeting = try_greeting_response(body.message)
            if greeting is not None:
                save_pending_tool(body.session_id, None)
                routing_greet = {
                    "workflow_id": "GREETING",
                    "scope": body.scope,
                    "demand_window_days": body.demand_window_days,
                    "date_filter": None,
                    "top_n": 10,
                    "clarification_needed": False,
                    "clarification_prompt": None,
                    "injection_detected": False,
                    "intent_classification": {
                        "intent": "GREETING",
                        "confidence": "high",
                        "requires_clarification": False,
                        "missing_fields": [],
                    },
                }
                out = {
                    "status": "ok",
                    "reason": None,
                    "user_message": greeting,
                    "routing": routing_greet,
                    "agent2": None,
                    "narrative": greeting,
                    "frontend": None,
                    "explain": None,
                    "supported_workflows": SUPPORTED_WORKFLOWS_TEXT,
                }
                _attach_tool_plan(out, conn, routing_greet, None)
                _attach_role_context(conn, body.session_id, role, out)
                _apply_safe_messages(out, None)
                _finalize_chat_out(out)
                _persist_session(body.session_id, out, user_id, username)
                return JSONResponse(out)

            routing = route_intent(body.message, body.scope, body.demand_window_days)

            pending = get_pending_tool(body.session_id)
            if pending:
                pwf = pending.get("workflow_id")
                rwf = routing.get("workflow_id")
                if rwf in ("GREETING", "OUT_OF_SCOPE") or (
                    pwf is not None and rwf is not None and pwf != rwf
                ):
                    save_pending_tool(body.session_id, None)

            if routing.get("workflow_id") == "GREETING":
                out = {
                    "status": "ok",
                    "reason": None,
                    "user_message": GREETING_REPLY,
                    "routing": routing,
                    "agent2": None,
                    "narrative": GREETING_REPLY,
                    "frontend": None,
                    "explain": None,
                    "supported_workflows": SUPPORTED_WORKFLOWS_TEXT,
                }
                _attach_tool_plan(out, conn, routing, None)
                _attach_role_context(conn, body.session_id, role, out)
                _apply_safe_messages(out, None)
                _finalize_chat_out(out)
                _persist_session(body.session_id, out, user_id, username)
                return JSONResponse(out)

            if routing.get("injection_detected"):
                out = {
                    "status": "refused",
                    "reason": "injection_detected",
                    "user_message": INJECTION_REPLY,
                    "routing": routing,
                    "agent2": None,
                    "narrative": INJECTION_REPLY,
                    "frontend": None,
                    "explain": None,
                    "supported_workflows": SUPPORTED_WORKFLOWS_TEXT,
                }
                _log_guard_event(
                    conn,
                    body.session_id,
                    "injection_guard",
                    {"message": body.message},
                    {"injection_detected": True},
                    "ok",
                )
                _attach_tool_plan(out, conn, routing, None)
                _attach_role_context(conn, body.session_id, role, out)
                _apply_safe_messages(out, None)
                _finalize_chat_out(out)
                _persist_session(body.session_id, out, user_id, username)
                return JSONResponse(out)

            if routing.get("clarification_needed"):
                clarify = routing.get("clarification_prompt") or (
                    AMBIGUOUS_STOCK_CLARIFY
                    + " You may also ask about one of the eight supported workflows (see list below)."
                )
                out = {
                    "status": "needs_clarification",
                    "reason": "needs_clarification",
                    "user_message": clarify,
                    "routing": routing,
                    "agent2": None,
                    "narrative": clarify,
                    "frontend": None,
                    "explain": _make_explain(conn, routing, role),
                    "supported_workflows": SUPPORTED_WORKFLOWS_TEXT,
                }
                _log_guard_event(
                    conn,
                    body.session_id,
                    "needs_clarification",
                    {"message": body.message, "routing": routing},
                    {},
                    "ok",
                )
                _attach_tool_plan(out, conn, routing, None)
                _attach_role_context(conn, body.session_id, role, out)
                _apply_safe_messages(out, None)
                _finalize_chat_out(out)
                _persist_session(body.session_id, out, user_id, username)
                return JSONResponse(out)

            if routing.get("workflow_id") == "OUT_OF_SCOPE":
                oos_full = f"{OUT_OF_SCOPE_REPLY}\n\n{SUPPORTED_WORKFLOWS_TEXT}"
                out = {
                    "status": "out_of_scope",
                    "reason": "OUT_OF_SCOPE",
                    "user_message": oos_full,
                    "routing": routing,
                    "agent2": None,
                    "narrative": oos_full,
                    "frontend": None,
                    "explain": _make_explain(conn, routing, role),
                    "supported_workflows": SUPPORTED_WORKFLOWS_TEXT,
                }
                _log_guard_event(
                    conn,
                    body.session_id,
                    "OUT_OF_SCOPE",
                    {"message": body.message},
                    {"workflow_id": "OUT_OF_SCOPE"},
                    "ok",
                )
                _attach_tool_plan(out, conn, routing, None)
                _attach_role_context(conn, body.session_id, role, out)
                _apply_safe_messages(out, None)
                _finalize_chat_out(out)
                _persist_session(body.session_id, out, user_id, username)
                return JSONResponse(out)

            if routing.get("workflow_id") in EXECUTABLE_WORKFLOWS:
                ready, missing, p_msg, p_ctx = evaluate_tool_execution_readiness(
                    scope=body.scope,
                    demand_window_days=body.demand_window_days,
                    parameters_confirmed=body.parameters_confirmed,
                    routing=routing,
                )
                if not ready:
                    save_pending_tool(
                        body.session_id,
                        pending_payload_for_session(routing, missing),
                    )
                    out = {
                        "status": "needs_clarification",
                        "reason": "missing_tool_parameters",
                        "user_message": p_msg,
                        "routing": routing,
                        "agent2": None,
                        "narrative": p_msg,
                        "frontend": None,
                        "explain": _make_explain(conn, routing, role),
                        "supported_workflows": SUPPORTED_WORKFLOWS_TEXT,
                        "missing_parameters": missing,
                        "clarification_context": p_ctx,
                    }
                    _log_guard_event(
                        conn,
                        body.session_id,
                        "parameter_clarification",
                        {
                            "message": body.message,
                            "routing": routing,
                            "missing_parameters": missing,
                        },
                        {"clarification_context": p_ctx},
                        "ok",
                    )
                    _attach_tool_plan(out, conn, routing, None)
                    _attach_role_context(conn, body.session_id, role, out)
                    _apply_safe_messages(out, None)
                    _finalize_chat_out(out)
                    _persist_session(body.session_id, out, user_id, username)
                    return JSONResponse(out)

                save_pending_tool(body.session_id, None)

            eff = merge_routing_with_ui(routing, body.scope, body.demand_window_days)
            agent2 = execute_pipeline(conn, eff, body.session_id, user_message=body.message)

            if agent2.get("error"):
                err_code = agent2["error"].get("code")
                if err_code == "INCOMPLETE_PARAMETERS":
                    tp = agent2.get("tool_plan") or {}
                    p = tp.get("params") or {}
                    miss = p.get("missing_parameters") or []
                    clarify = AMBIGUOUS_STOCK_CLARIFY + (
                        f" Missing: {', '.join(miss)}." if miss else ""
                    )
                    save_pending_tool(
                        body.session_id,
                        pending_payload_for_session(eff, [str(x) for x in miss]),
                    )
                    out = {
                        "status": "needs_clarification",
                        "reason": "incomplete_parameters",
                        "user_message": clarify,
                        "routing": eff,
                        "agent2": agent2,
                        "narrative": clarify,
                        "frontend": None,
                        "explain": _make_explain(conn, eff, role),
                        "supported_workflows": SUPPORTED_WORKFLOWS_TEXT,
                        "missing_parameters": [str(x) for x in miss],
                        "clarification_context": {
                            "missing_parameters": [str(x) for x in miss],
                            "location_codes": sorted(VALID_SCOPES),
                            "demand_window_presets": list(DEMAND_WINDOW_PRESETS),
                            "pending_workflow_id": eff.get("workflow_id"),
                        },
                    }
                    _log_guard_event(
                        conn,
                        body.session_id,
                        "incomplete_parameters",
                        {"message": body.message, "routing": eff},
                        {"tool_plan": tp},
                        "ok",
                    )
                    _attach_tool_plan(out, conn, eff, agent2)
                    _attach_role_context(conn, body.session_id, role, out)
                    _apply_safe_messages(out, agent2)
                    _finalize_chat_out(out)
                    _persist_session(body.session_id, out, user_id, username)
                    return JSONResponse(out)

                narrative = (
                    "Data temporarily unavailable, please retry."
                    if err_code == "SQL_ERROR"
                    else agent2["error"].get("message", "Error executing tools.")
                )
                out = {
                    "status": "error",
                    "reason": err_code,
                    "user_message": narrative,
                    "routing": eff,
                    "agent2": agent2,
                    "narrative": narrative,
                    "frontend": None,
                    "explain": _make_explain(conn, eff, role),
                    "supported_workflows": SUPPORTED_WORKFLOWS_TEXT,
                }
                _attach_tool_plan(out, conn, eff, agent2)
                _attach_role_context(conn, body.session_id, role, out)
                _apply_safe_messages(out, agent2)
                _finalize_chat_out(out)
                _persist_session(body.session_id, out, user_id, username)
                return JSONResponse(out)

            if agent2.get("row_count", 0) == 0:
                narrative = (
                    f"{NO_DATA_FRIENDLY}\n\n"
                    "No rows matched the approved tool query. Try adjusting scope or the demand window "
                    f"(demand window used: {eff.get('demand_window_days', 30)} days)."
                )
            else:
                narrative = compose_narrative(agent2)

            narrative = _coerce_user_visible_text(narrative, agent2)

            explain = _make_explain(conn, eff, role)
            if agent2.get("epsilon_applied"):
                explain["epsilon_note"] = (
                    f"Division uses epsilon {0.001} where average daily demand would otherwise be zero."
                )

            frontend = _build_frontend_cards(agent2, narrative, eff)
            out = {
                "status": "ok",
                "reason": None,
                "user_message": narrative,
                "routing": eff,
                "agent2": agent2,
                "narrative": narrative,
                "frontend": frontend,
                "explain": explain,
                "supported_workflows": SUPPORTED_WORKFLOWS_TEXT,
            }
            _attach_tool_plan(out, conn, eff, agent2)
            _attach_role_context(conn, body.session_id, role, out)
            _finalize_chat_out(out)
            _persist_session(body.session_id, out, user_id, username)
            return JSONResponse(out)
    except Exception as e:
        err_msg = "An unexpected error occurred."
        out_err = {
            "status": "error",
            "reason": "UNHANDLED",
            "user_message": err_msg,
            "detail": str(e),
            "agent2": None,
            "narrative": err_msg,
            "frontend": None,
            "explain": None,
            "tool_plan": {"tool": "", "query": "", "kpi": "", "params": {}},
        }
        _apply_safe_messages(out_err, None)
        _finalize_chat_out(out_err)
        return JSONResponse(out_err, status_code=500)


@app.get("/api/export/csv")
def export_csv(request: Request, session_id: str) -> StreamingResponse:
    data = get_session_payload(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="No export data for session")
    uid = int(getattr(request.state, "user_id", 0))
    if not _export_owner_ok(data, uid):
        raise HTTPException(status_code=403, detail="You do not have access to export this session")
    if not data.get("agent2"):
        raise HTTPException(status_code=404, detail="No export data for session")
    agent2 = data["agent2"]
    findings = agent2.get("findings") or []
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["rank", "sku", "location", "key_kpi_name", "key_kpi_value", "severity_score", "recommended_action"])
    for f in findings:
        w.writerow(
            [
                f.get("rank"),
                f.get("sku"),
                f.get("location"),
                f.get("key_kpi_name"),
                f.get("key_kpi_value"),
                f.get("severity_score"),
                f.get("recommended_action"),
            ]
        )
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="inventory_export_{session_id}.csv"'},
    )


@app.get("/api/export/json")
def export_json(request: Request, session_id: str) -> JSONResponse:
    data = get_session_payload(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="No export data for session")
    uid = int(getattr(request.state, "user_id", 0))
    if not _export_owner_ok(data, uid):
        raise HTTPException(status_code=403, detail="You do not have access to export this session")
    return JSONResponse(
        {
            "exported_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "session_id": session_id,
            "full_payload": data,
        }
    )


static_dir = Path(__file__).resolve().parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

_react_app = static_dir / "app"
_react_assets = _react_app / "assets"
if _react_assets.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_react_assets)), name="react_assets")


@app.get("/")
def index() -> HTMLResponse:
    """Serve React build (static/app) when present; else legacy static/index.html."""
    react_index = _react_app / "index.html"
    if react_index.is_file():
        html = react_index.read_text(encoding="utf-8")
        return HTMLResponse(
            content=html,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
            },
        )
    index_path = static_dir / "index.html"
    if not index_path.exists():
        return HTMLResponse(
            "<p>UI not built. Run: cd frontend && npm install && npm run build</p>",
            status_code=404,
        )
    html = index_path.read_text(encoding="utf-8")
    return HTMLResponse(
        content=html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )
