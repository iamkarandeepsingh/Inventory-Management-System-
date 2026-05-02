"""
Generate synthetic supply-chain Excel (if missing) and load into DuckDB.
Row counts match specification.
"""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd

from auth import hash_password
from config import DATA_DIR, DUCKDB_PATH, EXCEL_PATH

RNG_SEED = 42


def _date_range() -> list[date]:
    start = date(2026, 1, 5)
    end = date(2026, 4, 4)
    days: list[date] = []
    d = start
    while d <= end:
        days.append(d)
        d += timedelta(days=1)
    return days


def build_dim_location() -> pd.DataFrame:
    rows = [
        (1, "Store-001", "Montreal Store"),
        (2, "Store-002", "Laval Store"),
        (3, "Store-003", "Longueuil Store"),
        (4, "DC-004", "Quebec City DC"),
        (5, "Store-005", "Ottawa Store"),
        (6, "DC-006", "Toronto DC"),
    ]
    return pd.DataFrame(rows, columns=["location_id", "location_code", "location_name"])


def build_dim_vendor() -> pd.DataFrame:
    rows = []
    for vid in range(1, 9):
        rows.append(
            (
                vid,
                f"Vendor {vid:03d}",
                int(7 + (vid % 5) * 3),
                int(10 + vid * 2),
            )
        )
    return pd.DataFrame(
        rows, columns=["vendor_id", "vendor_name", "default_lead_time_days", "min_order_qty"]
    )


def build_dim_item(vendor_df: pd.DataFrame) -> pd.DataFrame:
    rng = random.Random(RNG_SEED)
    cats = ["A", "B", "C", "D"]
    statuses = ["Active", "Active", "Active", "Discontinued"]
    rows = []
    for i in range(1, 61):
        vid = int(((i * 7) % 8) + 1)
        cost = round(0.5 + (i % 23) * 1.75 + rng.random() * 3, 2)
        rows.append(
            (
                i,
                f"SKU-{i:06d}",
                cost,
                cats[i % len(cats)],
                statuses[i % len(statuses)],
                vid,
            )
        )
    return pd.DataFrame(
        rows, columns=["item_id", "sku", "unit_cost", "category", "status", "vendor_id"]
    )


def build_fact_inventory_snapshot(
    item_df: pd.DataFrame, loc_df: pd.DataFrame, days: list[date]
) -> pd.DataFrame:
    rng = random.Random(RNG_SEED + 1)
    rows = []
    for snapshot_date in days:
        for _, it in item_df.iterrows():
            for _, lo in loc_df.iterrows():
                base = int(5 + (it.item_id + lo.location_id * 3) % 40)
                noise = rng.randint(-3, 8)
                on_hand = max(0, base + noise - (snapshot_date.day % 7))
                if rng.random() < 0.02:
                    on_hand = rng.randint(0, 3)
                if rng.random() < 0.015:
                    on_hand = -rng.randint(1, 3)
                allocated = min(on_hand, rng.randint(0, max(1, on_hand // 3)))
                reserved = min(max(0, on_hand - allocated), rng.randint(0, 4))
                backorder = 0
                if on_hand <= allocated + reserved and rng.random() < 0.12:
                    backorder = rng.randint(1, 25)
                safety = int(3 + (it.item_id % 5))
                reorder_pt = int(safety + 5 + (lo.location_id % 4))
                target = int(reorder_pt + 15 + (it.item_id % 10))
                rows.append(
                    (
                        snapshot_date,
                        int(it.item_id),
                        int(lo.location_id),
                        on_hand,
                        allocated,
                        reserved,
                        backorder,
                        safety,
                        reorder_pt,
                        target,
                    )
                )
    return pd.DataFrame(
        rows,
        columns=[
            "snapshot_date",
            "item_id",
            "location_id",
            "on_hand_qty",
            "allocated_qty",
            "reserved_qty",
            "backorder_qty",
            "safety_stock_qty",
            "reorder_point_qty",
            "target_stock_qty",
        ],
    )


def build_fact_demand_daily(
    item_df: pd.DataFrame, loc_df: pd.DataFrame, days: list[date]
) -> pd.DataFrame:
    rng = random.Random(RNG_SEED + 2)
    rows = []
    for d in days:
        for _, it in item_df.iterrows():
            for _, lo in loc_df.iterrows():
                demand = max(0, int(rng.gauss(2 + (it.item_id % 7) * 0.3, 1.2)))
                if rng.random() < 0.08:
                    demand = 0
                fulfilled = min(demand, demand - rng.randint(0, min(2, demand)))
                rows.append((d, int(it.item_id), int(lo.location_id), demand, fulfilled))
    return pd.DataFrame(
        rows, columns=["date", "item_id", "location_id", "demand_qty", "fulfilled_qty"]
    )


def build_fact_po_header(loc_df: pd.DataFrame, vendor_df: pd.DataFrame) -> pd.DataFrame:
    rng = random.Random(RNG_SEED + 3)
    rows = []
    for pid in range(1, 121):
        vid = int((pid % 8) + 1)
        ship_to = int((pid % 6) + 1)
        order_date = date(2026, 1, 5) + timedelta(days=pid % 80)
        eta = order_date + timedelta(days=rng.randint(5, 40))
        st = rng.choice(["Open", "Closed", "Partially Received", "Open"])
        rows.append((pid, vid, ship_to, order_date, eta, st))
    return pd.DataFrame(
        rows,
        columns=[
            "po_id",
            "vendor_id",
            "ship_to_location_id",
            "order_date",
            "expected_receipt_date",
            "status",
        ],
    )


def build_fact_po_line(header_df: pd.DataFrame, item_df: pd.DataFrame) -> pd.DataFrame:
    rng = random.Random(RNG_SEED + 4)
    rows = []
    line_no = 1
    for _, h in header_df.iterrows():
        n_lines = int(1 + (h.po_id % 4))
        for _ in range(n_lines):
            iid = int((line_no % 60) + 1)
            ordered = rng.randint(10, 200)
            received = 0 if h.status == "Open" else rng.randint(0, ordered)
            if h.status == "Partially Received":
                received = int(ordered * 0.4)
            unit_cost = float(item_df.loc[item_df.item_id == iid, "unit_cost"].iloc[0])
            pl_status = "Open" if received < ordered else "Closed"
            rows.append((int(h.po_id), line_no, iid, ordered, received, unit_cost, pl_status))
            line_no += 1
            if len(rows) >= 307:
                return pd.DataFrame(
                    rows,
                    columns=[
                        "po_id",
                        "line_no",
                        "item_id",
                        "ordered_qty",
                        "received_qty",
                        "unit_cost",
                        "status",
                    ],
                )
    while len(rows) < 307:
        h = header_df.iloc[len(rows) % len(header_df)]
        iid = int((len(rows) % 60) + 1)
        ordered = rng.randint(10, 120)
        rows.append((int(h.po_id), line_no, iid, ordered, 0, 5.0, "Open"))
        line_no += 1
    return pd.DataFrame(
        rows,
        columns=[
            "po_id",
            "line_no",
            "item_id",
            "ordered_qty",
            "received_qty",
            "unit_cost",
            "status",
        ],
    )


def build_fact_inventory_adjustment(
    item_df: pd.DataFrame, loc_df: pd.DataFrame
) -> pd.DataFrame:
    rng = random.Random(RNG_SEED + 5)
    reasons = ["SHRINK", "FOUND", "CORRECT", "DAMAGE"]
    rows = []
    for aid in range(1, 501):
        iid = int((aid % 60) + 1)
        lid = int((aid % 6) + 1)
        d = date(2026, 1, 5) + timedelta(days=aid % 85)
        adj = rng.randint(-8, 8)
        rows.append((aid, d, iid, lid, adj, reasons[aid % len(reasons)]))
    return pd.DataFrame(
        rows, columns=["adj_id", "date", "item_id", "location_id", "adj_qty", "reason_code"]
    )


def build_fact_cycle_count(item_df: pd.DataFrame, loc_df: pd.DataFrame) -> pd.DataFrame:
    rng = random.Random(RNG_SEED + 6)
    rows = []
    for cid in range(1, 401):
        iid = int((cid % 60) + 1)
        lid = int((cid % 6) + 1)
        cd = date(2026, 1, 5) + timedelta(days=cid % 85)
        sys_q = rng.randint(5, 120)
        counted = sys_q + rng.randint(-5, 5)
        var_q = counted - sys_q
        uc = float(item_df.loc[item_df.item_id == iid, "unit_cost"].iloc[0])
        var_val = round(abs(var_q) * uc, 2)
        rows.append((cid, cd, iid, lid, sys_q, counted, var_q, var_val))
    return pd.DataFrame(
        rows,
        columns=[
            "count_id",
            "count_date",
            "item_id",
            "location_id",
            "system_qty",
            "counted_qty",
            "variance_qty",
            "variance_value",
        ],
    )


def build_config_kpi_threshold() -> pd.DataFrame:
    rows = [
        (
            "DOS",
            json.dumps({"epsilon": 0.001}),
            7.0,
            60.0,
            json.dumps({}),
            date(2026, 1, 1),
        ),
        (
            "STOCKOUT_SEVERITY",
            json.dumps({}),
            0.0,
            1.0,
            json.dumps({"atp_weight": 0.6, "demand_weight": 0.4}),
            date(2026, 1, 1),
        ),
        (
            "BACKORDER_SEVERITY",
            json.dumps({}),
            0.0,
            1.0,
            json.dumps({"qty_weight": 1.0}),
            date(2026, 1, 1),
        ),
        (
            "CYCLE_COUNT_PRIORITY",
            json.dumps({}),
            0.0,
            1.0,
            json.dumps({"value_at_risk": 0.5, "variance_history": 0.3, "adjustment_freq": 0.2}),
            date(2026, 1, 1),
        ),
        (
            "ABC",
            json.dumps({"A": 80, "B": 95, "C": 100}),
            80.0,
            95.0,
            json.dumps({"A_pct": 80, "B_pct": 95}),
            date(2026, 1, 1),
        ),
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "kpi_name",
            "param_json",
            "threshold_low",
            "threshold_high",
            "severity_weights",
            "effective_from",
        ],
    )


def ensure_excel() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if EXCEL_PATH.exists():
        return
    days = _date_range()
    loc = build_dim_location()
    vendor = build_dim_vendor()
    item = build_dim_item(vendor)
    snap = build_fact_inventory_snapshot(item, loc, days)
    demand = build_fact_demand_daily(item, loc, days)
    po_h = build_fact_po_header(loc, vendor)
    po_l = build_fact_po_line(po_h, item)
    adj = build_fact_inventory_adjustment(item, loc)
    cc = build_fact_cycle_count(item, loc)
    cfg = build_config_kpi_threshold()
    with pd.ExcelWriter(EXCEL_PATH, engine="openpyxl") as writer:
        item.to_excel(writer, sheet_name="dim_item", index=False)
        loc.to_excel(writer, sheet_name="dim_location", index=False)
        vendor.to_excel(writer, sheet_name="dim_vendor", index=False)
        snap.to_excel(writer, sheet_name="fact_inventory_snapshot", index=False)
        demand.to_excel(writer, sheet_name="fact_demand_daily", index=False)
        po_h.to_excel(writer, sheet_name="fact_po_header", index=False)
        po_l.to_excel(writer, sheet_name="fact_po_line", index=False)
        adj.to_excel(writer, sheet_name="fact_inventory_adjustment", index=False)
        cc.to_excel(writer, sheet_name="fact_cycle_count", index=False)
        cfg.to_excel(writer, sheet_name="config_kpi_threshold", index=False)


def load_excel_to_duckdb(conn: duckdb.DuckDBPyConnection) -> None:
    ensure_excel()
    xl = pd.ExcelFile(EXCEL_PATH)
    for sheet in xl.sheet_names:
        df = pd.read_excel(EXCEL_PATH, sheet_name=sheet)
        conn.execute(f'DROP TABLE IF EXISTS "{sheet}"')
        conn.register("_df_tmp", df)
        conn.execute(f'CREATE TABLE "{sheet}" AS SELECT * FROM _df_tmp')
        conn.unregister("_df_tmp")


def _audit_session_columns(conn: duckdb.DuckDBPyConnection) -> set[str]:
    rows = conn.execute("PRAGMA table_info('audit_chat_session')").fetchall()
    return {str(r[1]) for r in rows}


def ensure_dim_user(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dim_user (
            user_id INTEGER PRIMARY KEY,
            username VARCHAR UNIQUE NOT NULL,
            password_hash VARCHAR NOT NULL,
            role VARCHAR NOT NULL
        )
        """
    )
    n = conn.execute("SELECT COUNT(*) FROM dim_user").fetchone()[0]
    if int(n or 0) == 0:
        seed = [
            (1, "analyst", "Analyst"),
            (2, "supervisor", "Supervisor"),
            (3, "auditor", "Auditor"),
            (4, "admin", "Admin"),
        ]
        for uid, uname, role in seed:
            hp = hash_password(f"{uname}123")
            conn.execute(
                """
                INSERT INTO dim_user (user_id, username, password_hash, role)
                VALUES (?, ?, ?, ?)
                """,
                [uid, uname, hp, role],
            )


def ensure_audit_tables(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_chat_session (
            session_id VARCHAR PRIMARY KEY,
            user_role VARCHAR,
            started_at TIMESTAMP,
            ended_at TIMESTAMP,
            app_version VARCHAR
        )
        """
    )
    cols = _audit_session_columns(conn)
    if "user_id" not in cols:
        conn.execute("ALTER TABLE audit_chat_session ADD COLUMN user_id INTEGER")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_tool_call (
            tool_call_id VARCHAR PRIMARY KEY,
            session_id VARCHAR,
            timestamp TIMESTAMP,
            tool_name VARCHAR,
            input_json VARCHAR,
            output_json VARCHAR,
            evidence_refs VARCHAR,
            status VARCHAR,
            error_message VARCHAR
        )
        """
    )


def init_database() -> duckdb.DuckDBPyConnection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(DUCKDB_PATH))
    load_excel_to_duckdb(conn)
    ensure_dim_user(conn)
    ensure_audit_tables(conn)
    return conn


def print_startup_stats(conn: duckdb.DuckDBPyConnection) -> None:
    tables = [
        "dim_item",
        "dim_location",
        "dim_vendor",
        "fact_inventory_snapshot",
        "fact_demand_daily",
        "fact_po_header",
        "fact_po_line",
        "fact_inventory_adjustment",
        "fact_cycle_count",
        "config_kpi_threshold",
    ]
    for t in tables:
        n = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        print(f"  {t}: {n} rows")
    latest = conn.execute(
        "SELECT MAX(snapshot_date) FROM fact_inventory_snapshot"
    ).fetchone()[0]
    print(f"  Latest snapshot_date: {latest}")
