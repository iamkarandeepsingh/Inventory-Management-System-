"""
Agent 1 — Guardrail + intent router + response composition (Gemini).
Numeric claims in structured payloads come only from Agent 2; narrative is constrained to tool output.
"""

from __future__ import annotations

import json
import re
from typing import Any

import google.generativeai as genai

from config import GEMINI_API_KEY, GEMINI_MODEL, VALID_SCOPES

WORKFLOW_IDS = frozenset(
    {
        "UC-1",
        "UC-2",
        "UC-3",
        "UC-4",
        "UC-5",
        "UC-6",
        "UC-7",
        "UC-8",
        "OUT_OF_SCOPE",
        "GREETING",
    }
)

# Eleven-way user-query intents (returned in intent_classification).
INTENT_LABELS = frozenset(
    {
        "GREETING",
        "STOCKOUT_TRIAGE",
        "BACKORDER_ANALYSIS",
        "OVERSTOCK_ANALYSIS",
        "SLOW_MOVERS",
        "ANOMALY_DETECTION",
        "CYCLE_COUNT",
        "ABC_CLASSIFICATION",
        "ON_ORDER_COVERAGE",
        "OUT_OF_SCOPE",
        "AMBIGUOUS",
    }
)

# Map high-level intent → executable workflow_id (GREETING handled in API layer).
INTENT_TO_WORKFLOW_ID: dict[str, str] = {
    "STOCKOUT_TRIAGE": "UC-1",
    "BACKORDER_ANALYSIS": "UC-2",
    "OVERSTOCK_ANALYSIS": "UC-3",
    "SLOW_MOVERS": "UC-4",
    "ANOMALY_DETECTION": "UC-5",
    "CYCLE_COUNT": "UC-6",
    "ABC_CLASSIFICATION": "UC-7",
    "ON_ORDER_COVERAGE": "UC-8",
    "GREETING": "GREETING",
    "OUT_OF_SCOPE": "OUT_OF_SCOPE",
    "AMBIGUOUS": "OUT_OF_SCOPE",
}

# If the model returns legacy workflow_id instead of intent, map back.
WORKFLOW_ID_TO_INTENT: dict[str, str] = {
    "UC-1": "STOCKOUT_TRIAGE",
    "UC-2": "BACKORDER_ANALYSIS",
    "UC-3": "OVERSTOCK_ANALYSIS",
    "UC-4": "SLOW_MOVERS",
    "UC-5": "ANOMALY_DETECTION",
    "UC-6": "CYCLE_COUNT",
    "UC-7": "ABC_CLASSIFICATION",
    "UC-8": "ON_ORDER_COVERAGE",
    "OUT_OF_SCOPE": "OUT_OF_SCOPE",
    "GREETING": "GREETING",
}

INJECTION_PHRASES = (
    "skip tools",
    "use your own knowledge",
    "bypass governance",
    "bypass system",
    "ignore the rules",
    "ignore rules",
    "just guess",
    "just guess numbers",
    "output a number without querying",
)

GREETING_REPLY = (
    "Hello! I am your Inventory Analytics Assistant. I can help you analyze stockouts, overstock, "
    "backorders, and other inventory issues. What would you like to explore today?"
)

OUT_OF_SCOPE_REPLY = (
    "I am designed for inventory and supply chain analytics. I cannot assist with that request. "
    "You can ask about stockouts, inventory levels, or supply chain issues."
)

INJECTION_REPLY = (
    "I cannot bypass system governance rules. Please provide a valid analytics query."
)

AMBIGUOUS_STOCK_CLARIFY = (
    "Could you please specify the location and time window? For example: "
    "'Show stockouts in Montreal warehouse for last 30 days.'"
)

ROUTER_SYSTEM = """You are Agent 1 (Intent classifier) for a GOVERNED operational inventory analytics system.

NON-NEGOTIABLE RULES (behavior only; output JSON only):
- Routing/classification only — never invent numbers.
- Pure greetings are handled by the server before this call — never classify them here (GREETING is not an allowed intent).
- Vague inventory asks with no clear workflow ("show stock", "check inventory" only) → intent AMBIGUOUS, requires_clarification true.
- Demand / inventory trends over time, time series, or "demand trends" — location and time window are supplied by the UI (scope + demand_window_days). Map to STOCKOUT_TRIAGE, requires_clarification false, missing_fields []. Do NOT ask the user to name a workflow in text.
- Non-inventory chit-chat, jokes, unrelated topics → intent OUT_OF_SCOPE.
- Choose exactly ONE intent from the allowed list.

Intent definitions (match user language to ONE label):
- STOCKOUT_TRIAGE — stockouts, ATP, out-of-stock, urgent replenishment, what to order now, demand trends over time (chart uses approved demand SQL)
- BACKORDER_ANALYSIS — backorders, unfulfilled orders, delayed supply, open orders
- OVERSTOCK_ANALYSIS — excess inventory, too much stock, high days of supply, overstock
- SLOW_MOVERS — slow movers, dead stock, non-moving, low movement, value at risk
- ANOMALY_DETECTION — data quality, negative inventory, cost/quantity anomalies
- CYCLE_COUNT — cycle count priority, physical count, inventory accuracy, what to count next
- ABC_CLASSIFICATION — ABC analysis, item classification by consumption value
- ON_ORDER_COVERAGE — PO/on-order coverage, inbound, purchase orders, coverage days
- OUT_OF_SCOPE — not inventory/supply-chain analytics
- AMBIGUOUS — inventory-related but unclear which workflow or missing critical constraints

confidence: one of "high", "medium", "low".
requires_clarification: true only if the ask is truly vague (e.g. only "check inventory"). False for demand-trend / time-series asks when UI already sent scope and demand_window_days.
missing_fields: usually []; never include "workflow" for demand-trend asks — the app selects the governed workflow.

GREETING messages are handled by the application before this model runs — never output intent GREETING (it is not in the enum).

CRITICAL: Output a single JSON object with EXACTLY these keys and no others. No markdown, no prose, no code fences.

Required JSON schema:
{
  "intent": "STOCKOUT_TRIAGE|BACKORDER_ANALYSIS|OVERSTOCK_ANALYSIS|SLOW_MOVERS|ANOMALY_DETECTION|CYCLE_COUNT|ABC_CLASSIFICATION|ON_ORDER_COVERAGE|OUT_OF_SCOPE|AMBIGUOUS",
  "confidence": "high|medium|low",
  "requires_clarification": false,
  "missing_fields": []
}
"""


COMPOSER_SYSTEM = """You are a GOVERNED AI agent for operational inventory analytics. You receive JSON from approved tools ONLY.

STRICT RULES:
- You MUST NOT generate or guess any numeric values. Every number must already appear in the tool JSON (findings, row_count, parameters, evidence).
- If row_count is 0 or findings are empty, state that no tool rows matched — do not invent KPIs or counts.
- Tone: professional, clear, structured, no fluff.

MANDATORY RESPONSE STRUCTURE (use these headings in plain text):
1. Summary — 2–5 sentences; executive tone; no SKU-by-SKU lists (the client renders governed tables).
2. Findings — at most one short paragraph highlighting themes only; do NOT enumerate every row when findings exist.
3. KPIs — ONLY include if the tool JSON contains KPI/formula data or numeric values you quote verbatim from the JSON.
4. Recommendations — numbered; ESCALATE first, then MONITOR, then INVESTIGATE when those appear in findings.
5. Evidence — reference query_id, run_id, snapshot_date, workflow_id from the JSON when present.

Output plain text (not JSON)."""


def detect_injection(message: str) -> bool:
    low = message.lower()
    return any(p in low for p in INJECTION_PHRASES)


# Whole-word denylist (avoids "order" matching inside "border", etc.).
_GREETING_DENY_WORDS = frozenset(
    {
        "stock",
        "stocks",
        "inventory",
        "sku",
        "skus",
        "order",
        "orders",
        "warehouse",
        "replenish",
        "backorder",
        "atp",
        "supply",
        "demand",
        "shipment",
        "cycle",
        "abc",
        "anomaly",
        "overstock",
        "purchase",
        "inbound",
        "coverage",
        "location",
        "store",
        "stores",
        "montreal",
        "show",
        "check",
        "analyze",
        "report",
        "replenishment",
        "stockout",
        "stockouts",
    }
)

# Phrases that disqualify a greeting even when individual words look benign.
_GREETING_DENY_PHRASES = (
    "slow mover",
    "dead stock",
    "cycle count",
    "physical count",
    "dc-004",
    "dc-006",
    "store-001",
    "store-002",
    "store-003",
    "store-005",
)


def is_pure_greeting_message(message: str) -> bool:
    """
    Deterministic greeting detection — used before the Gemini router so GREETING
    never invokes the intent classification model.
    """
    raw = message.strip()
    if not raw:
        return False
    low = raw.lower()
    low = low.replace("g'day", "gday").replace("g day", "gday")
    if any(p in low for p in _GREETING_DENY_PHRASES):
        return False
    words_alnum = re.findall(r"[a-z0-9]+", low)
    if any(w in _GREETING_DENY_WORDS for w in words_alnum):
        return False
    t = re.sub(r"[^\w\s]", " ", low)
    t = " ".join(t.split())
    if not t:
        return False
    if len(t) > 120:
        return False

    exact = frozenset(
        {
            "hi",
            "hello",
            "hey",
            "yo",
            "howdy",
            "gday",
            "hi there",
            "hello there",
            "hey there",
            "good morning",
            "good afternoon",
            "good evening",
            "good night",
            "morning",
            "evening",
        }
    )
    if t in exact:
        return True

    # Short salutation-only lines, e.g. "hi everyone", "hello team"
    allow = frozenset(
        {
            "hi",
            "hello",
            "hey",
            "yo",
            "howdy",
            "gday",
            "there",
            "everyone",
            "team",
            "all",
            "folks",
            "good",
            "morning",
            "afternoon",
            "evening",
            "night",
        }
    )
    words = t.split()
    if 1 <= len(words) <= 5 and all(w in allow for w in words):
        if "good" in words and not any(
            x in words for x in ("morning", "afternoon", "evening", "night")
        ):
            return False
        return True

    if re.match(
        r"^(hi|hello|hey|howdy|g\s*day|yo)\s*,?\s*(there|everyone|team|all|folks)?\s*!*$",
        t,
        re.IGNORECASE,
    ):
        return True
    if re.match(r"^good\s+(morning|afternoon|evening|night)(\s+[!.\s]*)?$", t, re.IGNORECASE):
        return True
    return False


def try_greeting_response(message: str) -> str | None:
    """Pure greetings (no analytics) → fixed reply; no tools, no Gemini router."""
    if is_pure_greeting_message(message):
        return GREETING_REPLY
    return None


def _ambiguous_inventory_query(low: str) -> bool:
    s = " ".join(low.split())
    if s in ("show stock", "check inventory", "show inventory", "check stock"):
        return True
    if re.fullmatch(r"(show|check)\s+(stock|inventory)", s):
        return True
    return False


def _is_demand_trend_query(message: str) -> bool:
    """
    Demand / time-series asks — scope and demand_window_days come from the UI.
    Route to STOCKOUT_TRIAGE so tools run without false 'missing workflow' clarification.
    """
    low = message.lower()
    if "demand" in low and ("trend" in low or "trends" in low):
        return True
    if "demand" in low and any(p in low for p in ("over time", "time series", "historical", "timeline")):
        return True
    if "selected location scope" in low and "demand" in low:
        return True
    return False


def _intent_for_demand_trend() -> dict[str, Any]:
    return {
        "intent": "STOCKOUT_TRIAGE",
        "confidence": "high",
        "requires_clarification": False,
        "missing_fields": [],
    }


def _parse_json_text(text: str) -> dict[str, Any]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)
    return json.loads(text)


def _normalize_intent_classification(raw: dict[str, Any]) -> dict[str, Any]:
    """Build the four-field intent payload; coerce invalid values."""
    intent = raw.get("intent")
    if (intent not in INTENT_LABELS) and raw.get("workflow_id") in WORKFLOW_ID_TO_INTENT:
        intent = WORKFLOW_ID_TO_INTENT[raw["workflow_id"]]
    if intent not in INTENT_LABELS:
        intent = "AMBIGUOUS"
    conf = raw.get("confidence", "medium")
    if conf not in ("high", "medium", "low"):
        conf = "medium"
    missing = raw.get("missing_fields")
    if not isinstance(missing, list):
        missing = []
    else:
        missing = [str(x) for x in missing if x is not None and str(x).strip()]
    requires_clar = bool(raw.get("requires_clarification"))
    if intent == "AMBIGUOUS":
        requires_clar = True
    return {
        "intent": intent,
        "confidence": conf,
        "requires_clarification": requires_clar,
        "missing_fields": missing,
    }


def _routing_from_intent_classification(
    ic: dict[str, Any],
    ui_scope: str | None,
    ui_demand_window_days: int | None,
    *,
    injection_detected: bool,
    date_filter: Any | None = None,
    top_n: int = 10,
) -> dict[str, Any]:
    """Merge normalized intent with UI execution parameters."""
    intent = ic["intent"]
    workflow_id = INTENT_TO_WORKFLOW_ID.get(intent, "OUT_OF_SCOPE")
    clarification_needed = (not injection_detected) and (
        intent == "AMBIGUOUS" or bool(ic.get("requires_clarification"))
    )
    clarification_prompt = None
    if clarification_needed:
        clarification_prompt = AMBIGUOUS_STOCK_CLARIFY
        if ic.get("missing_fields"):
            clarification_prompt += " Missing: " + ", ".join(ic["missing_fields"]) + "."

    if ui_scope is not None and str(ui_scope).strip() in VALID_SCOPES:
        scope: str | None = str(ui_scope).strip()
    else:
        scope = None

    if ui_demand_window_days is not None:
        try:
            demand_window_days: int | None = int(ui_demand_window_days)
        except (TypeError, ValueError):
            demand_window_days = None
    else:
        demand_window_days = None

    return {
        "workflow_id": workflow_id,
        "scope": scope,
        "demand_window_days": demand_window_days,
        "date_filter": date_filter,
        "top_n": int(top_n),
        "clarification_needed": clarification_needed,
        "clarification_prompt": clarification_prompt,
        "injection_detected": injection_detected,
        "intent_classification": {
            "intent": ic["intent"],
            "confidence": ic["confidence"],
            "requires_clarification": ic["requires_clarification"],
            "missing_fields": ic["missing_fields"],
        },
    }


def _keyword_intent_classify(message: str) -> dict[str, Any]:
    """Offline / no-key fallback: deterministic intent labels."""
    low = message.lower()
    if _ambiguous_inventory_query(low):
        return {
            "intent": "AMBIGUOUS",
            "confidence": "medium",
            "requires_clarification": True,
            "missing_fields": [],
        }
    if _is_demand_trend_query(message):
        return _intent_for_demand_trend()
    if any(
        k in low
        for k in (
            "stockout",
            "out of stock",
            "atp",
            "replenish",
            "order now",
            "available to promise",
        )
    ):
        return {
            "intent": "STOCKOUT_TRIAGE",
            "confidence": "high",
            "requires_clarification": False,
            "missing_fields": [],
        }
    if any(k in low for k in ("backorder", "back order", "unfulfilled", "open order")):
        return {
            "intent": "BACKORDER_ANALYSIS",
            "confidence": "high",
            "requires_clarification": False,
            "missing_fields": [],
        }
    if any(k in low for k in ("overstock", "days of supply", "too much stock", "excess")):
        return {
            "intent": "OVERSTOCK_ANALYSIS",
            "confidence": "high",
            "requires_clarification": False,
            "missing_fields": [],
        }
    if any(k in low for k in ("slow mover", "dead stock", "non-moving", "no sales")):
        return {
            "intent": "SLOW_MOVERS",
            "confidence": "high",
            "requires_clarification": False,
            "missing_fields": [],
        }
    if any(k in low for k in ("anomaly", "data quality", "negative inventory", "invalid cost")):
        return {
            "intent": "ANOMALY_DETECTION",
            "confidence": "high",
            "requires_clarification": False,
            "missing_fields": [],
        }
    if any(k in low for k in ("cycle count", "count next", "physical count", "inventory accuracy")):
        return {
            "intent": "CYCLE_COUNT",
            "confidence": "high",
            "requires_clarification": False,
            "missing_fields": [],
        }
    if any(k in low for k in ("abc", "classification", "consumption value")):
        return {
            "intent": "ABC_CLASSIFICATION",
            "confidence": "medium",
            "requires_clarification": False,
            "missing_fields": [],
        }
    if any(
        k in low
        for k in ("on order", "purchase order", "po coverage", "inbound", "coverage days")
    ):
        return {
            "intent": "ON_ORDER_COVERAGE",
            "confidence": "high",
            "requires_clarification": False,
            "missing_fields": [],
        }
    return {
        "intent": "OUT_OF_SCOPE",
        "confidence": "medium",
        "requires_clarification": False,
        "missing_fields": [],
    }


def _keyword_route(message: str, ui_scope: str | None, ui_demand_window_days: int | None) -> dict[str, Any]:
    ic = _normalize_intent_classification(_keyword_intent_classify(message))
    return _routing_from_intent_classification(ic, ui_scope, ui_demand_window_days, injection_detected=False)


def route_intent(
    message: str,
    ui_scope: str | None,
    ui_demand_window_days: int | None,
) -> dict[str, Any]:
    if detect_injection(message):
        ic_inj = _normalize_intent_classification(
            {
                "intent": "OUT_OF_SCOPE",
                "confidence": "high",
                "requires_clarification": False,
                "missing_fields": [],
            }
        )
        return _routing_from_intent_classification(
            ic_inj, ui_scope, ui_demand_window_days, injection_detected=True
        )

    if try_greeting_response(message) is not None:
        ic_g = _normalize_intent_classification(
            {
                "intent": "GREETING",
                "confidence": "high",
                "requires_clarification": False,
                "missing_fields": [],
            }
        )
        return _routing_from_intent_classification(ic_g, ui_scope, ui_demand_window_days, injection_detected=False)

    if _is_demand_trend_query(message):
        ic_trend = _normalize_intent_classification(_intent_for_demand_trend())
        return _routing_from_intent_classification(ic_trend, ui_scope, ui_demand_window_days, injection_detected=False)

    if not GEMINI_API_KEY:
        return _keyword_route(message, ui_scope, ui_demand_window_days)

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(
        GEMINI_MODEL,
        generation_config={
            "response_mime_type": "application/json",
            "temperature": 0.1,
        },
    )
    scope_txt = (
        "(not set — user must choose location scope before tools run)"
        if ui_scope is None
        else str(ui_scope)
    )
    dwd_txt = (
        "(not set — user must choose demand window before tools run)"
        if ui_demand_window_days is None
        else str(ui_demand_window_days)
    )
    user = (
        f"User message: {message}\n"
        f"UI scope (informational; execution uses this from the server): {scope_txt}\n"
        f"UI demand_window_days: {dwd_txt}\n"
    )
    try:
        resp = model.generate_content([ROUTER_SYSTEM, user])
        text = (resp.text or "").strip()
        data = _parse_json_text(text)
    except Exception:
        return _keyword_route(message, ui_scope, ui_demand_window_days)

    if bool(data.get("injection_detected")):
        ic_inj = _normalize_intent_classification(
            {
                "intent": "OUT_OF_SCOPE",
                "confidence": "high",
                "requires_clarification": False,
                "missing_fields": [],
            }
        )
        return _routing_from_intent_classification(
            ic_inj, ui_scope, ui_demand_window_days, injection_detected=True
        )

    ic = _normalize_intent_classification(data)
    # GREETING is never a valid router output; server handles it without Gemini.
    if ic["intent"] == "GREETING":
        return _keyword_route(message, ui_scope, ui_demand_window_days)

    if _is_demand_trend_query(message):
        ic = _normalize_intent_classification(_intent_for_demand_trend())

    if ui_demand_window_days is None:
        dwd = None
    else:
        try:
            dwd = int(data.get("demand_window_days", ui_demand_window_days))
        except (TypeError, ValueError):
            dwd = int(ui_demand_window_days)
    try:
        top_n = int(data.get("top_n", 10))
    except (TypeError, ValueError):
        top_n = 10

    return _routing_from_intent_classification(
        ic,
        ui_scope,
        dwd,
        injection_detected=False,
        date_filter=data.get("date_filter"),
        top_n=top_n,
    )


def compose_narrative(agent2_payload: dict[str, Any]) -> str:
    if not GEMINI_API_KEY:
        return _deterministic_narrative(agent2_payload)
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(
        GEMINI_MODEL,
        generation_config={"temperature": 0.2},
    )
    try:
        resp = model.generate_content(
            [
                COMPOSER_SYSTEM,
                "Tool results JSON:\n" + json.dumps(agent2_payload, default=str),
            ]
        )
        raw = (resp.text or "").strip()
        if raw.lower() in ("undefined", "null"):
            raw = ""
        return raw or _deterministic_narrative(agent2_payload)
    except Exception:
        return _deterministic_narrative(agent2_payload)


def _deterministic_narrative(agent2: dict[str, Any]) -> str:
    rc = agent2.get("row_count", 0)
    wf = agent2.get("workflow_id")
    snap = agent2.get("snapshot_date")
    err = agent2.get("error")
    if err:
        return f"Analysis could not complete ({err.get('code', 'error')}): {err.get('message', '')}"
    if rc == 0:
        return (
            "No data available to answer this query.\n\n"
            "No rows matched the approved tool query for this workflow. "
            "Try adjusting scope or the demand window, or choose another supported workflow."
        )
    return (
        f"Analysis returned {rc} row(s) for workflow {wf} at snapshot {snap}. "
        "See structured findings and evidence for KPI-backed values."
    )


SUPPORTED_WORKFLOWS_TEXT = (
    "Supported workflows: UC-1 Stockout Triage; UC-2 Backorder Analysis; "
    "UC-3 Overstock / Days of Supply; UC-4 Slow Movers / Dead Stock; "
    "UC-5 Data Anomaly Detection; UC-6 Cycle Count Priority; "
    "UC-7 ABC Classification; UC-8 On-Order Coverage."
)


def merge_routing_with_ui(
    routing: dict[str, Any],
    ui_scope: str | None,
    ui_demand_window_days: int | None,
) -> dict[str, Any]:
    out = dict(routing)
    if ui_scope is not None and ui_scope in VALID_SCOPES:
        out["scope"] = ui_scope
    if ui_demand_window_days is not None:
        out["demand_window_days"] = int(ui_demand_window_days)
    return out
