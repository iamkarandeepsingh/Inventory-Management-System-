"""Approved read-only SQL templates (v1.0). Parameterized for DuckDB."""

from __future__ import annotations

SQL_UC1 = """
WITH latest_snapshot AS (
    SELECT i.sku, l.location_code, s.on_hand_qty, s.allocated_qty, s.reserved_qty,
           s.backorder_qty,
           (s.on_hand_qty - s.allocated_qty - s.reserved_qty) AS atp,
           s.item_id, s.location_id
    FROM fact_inventory_snapshot s
    JOIN dim_item i ON s.item_id = i.item_id
    JOIN dim_location l ON s.location_id = l.location_id
    WHERE s.snapshot_date = (SELECT MAX(snapshot_date) FROM fact_inventory_snapshot)
      AND (? = 'all' OR l.location_code = ?)
),
demand AS (
    SELECT item_id, location_id,
           SUM(demand_qty)::DOUBLE / ? AS avg_daily_demand
    FROM fact_demand_daily
    WHERE date >= ?
    GROUP BY item_id, location_id
)
SELECT ls.sku, ls.location_code, ls.atp, ls.backorder_qty,
       COALESCE(d.avg_daily_demand, 0) AS avg_daily_demand, i.unit_cost
FROM latest_snapshot ls
LEFT JOIN demand d ON ls.item_id = d.item_id AND ls.location_id = d.location_id
JOIN dim_item i ON ls.item_id = i.item_id
WHERE ls.atp <= 0
ORDER BY ls.atp ASC
LIMIT ?
"""

SQL_UC2 = """
SELECT i.sku, l.location_code, s.backorder_qty, s.on_hand_qty, s.allocated_qty,
       (s.on_hand_qty - s.allocated_qty - s.reserved_qty) AS atp, i.unit_cost,
       (s.backorder_qty * i.unit_cost) AS backorder_value
FROM fact_inventory_snapshot s
JOIN dim_item i ON s.item_id = i.item_id
JOIN dim_location l ON s.location_id = l.location_id
WHERE s.snapshot_date = (SELECT MAX(snapshot_date) FROM fact_inventory_snapshot)
  AND s.backorder_qty > 0
  AND (? = 'all' OR l.location_code = ?)
ORDER BY backorder_value DESC
LIMIT ?
"""

SQL_UC3 = """
WITH demand AS (
    SELECT item_id, location_id,
           SUM(demand_qty)::DOUBLE / ? AS avg_daily_demand
    FROM fact_demand_daily
    WHERE date >= ?
    GROUP BY item_id, location_id
)
SELECT i.sku, l.location_code, s.on_hand_qty,
       COALESCE(d.avg_daily_demand, 0) AS avg_daily_demand,
       s.on_hand_qty / GREATEST(COALESCE(d.avg_daily_demand, 0), 0.001) AS dos,
       (s.on_hand_qty - s.target_stock_qty) AS excess_qty,
       ((s.on_hand_qty - s.target_stock_qty) * i.unit_cost) AS excess_value,
       i.unit_cost
FROM fact_inventory_snapshot s
JOIN dim_item i ON s.item_id = i.item_id
JOIN dim_location l ON s.location_id = l.location_id
LEFT JOIN demand d ON s.item_id = d.item_id AND s.location_id = d.location_id
WHERE s.snapshot_date = (SELECT MAX(snapshot_date) FROM fact_inventory_snapshot)
  AND (? = 'all' OR l.location_code = ?)
  AND s.on_hand_qty / GREATEST(COALESCE(d.avg_daily_demand, 0), 0.001) > 60
ORDER BY dos DESC
LIMIT ?
"""

SQL_UC4 = """
WITH movement AS (
    SELECT item_id, location_id, SUM(demand_qty) AS movement_qty
    FROM fact_demand_daily
    WHERE date >= ?
    GROUP BY item_id, location_id
)
SELECT i.sku, l.location_code, s.on_hand_qty,
       COALESCE(m.movement_qty, 0) AS movement_qty,
       (s.on_hand_qty * i.unit_cost) AS value_at_risk,
       CASE WHEN COALESCE(m.movement_qty, 0) = 0 THEN 'Dead Stock' ELSE 'Slow Mover' END AS classification
FROM fact_inventory_snapshot s
JOIN dim_item i ON s.item_id = i.item_id
JOIN dim_location l ON s.location_id = l.location_id
LEFT JOIN movement m ON s.item_id = m.item_id AND s.location_id = m.location_id
WHERE s.snapshot_date = (SELECT MAX(snapshot_date) FROM fact_inventory_snapshot)
  AND (? = 'all' OR l.location_code = ?)
  AND s.on_hand_qty > 0
  AND COALESCE(m.movement_qty, 0) < 5
ORDER BY value_at_risk DESC
LIMIT ?
"""

SQL_UC5 = """
SELECT i.sku, l.location_code, s.on_hand_qty, s.allocated_qty, s.reserved_qty, i.unit_cost,
       CASE
         WHEN s.on_hand_qty < 0 THEN 'Negative on-hand quantity'
         WHEN (s.allocated_qty + s.reserved_qty) > s.on_hand_qty
           THEN 'Allocated + reserved exceeds on-hand'
         WHEN i.unit_cost <= 0 THEN 'Invalid unit cost'
         ELSE 'Unknown anomaly'
       END AS anomaly_type
FROM fact_inventory_snapshot s
JOIN dim_item i ON s.item_id = i.item_id
JOIN dim_location l ON s.location_id = l.location_id
WHERE s.snapshot_date = (SELECT MAX(snapshot_date) FROM fact_inventory_snapshot)
  AND (? = 'all' OR l.location_code = ?)
  AND (
    s.on_hand_qty < 0
    OR (s.allocated_qty + s.reserved_qty) > s.on_hand_qty
    OR i.unit_cost <= 0
  )
ORDER BY s.snapshot_date DESC
LIMIT ?
"""

SQL_UC6 = """
WITH adj_freq AS (
    SELECT item_id, location_id, COUNT(*) AS adj_count
    FROM fact_inventory_adjustment
    WHERE date >= ?
    GROUP BY item_id, location_id
),
variance_hist AS (
    SELECT item_id, location_id,
           SUM(ABS(variance_qty)) AS total_variance_qty,
           SUM(variance_value) AS total_variance_value
    FROM fact_cycle_count
    WHERE count_date >= ?
    GROUP BY item_id, location_id
)
SELECT i.sku, l.location_code,
       (s.on_hand_qty * i.unit_cost) AS value_at_risk,
       COALESCE(a.adj_count, 0) AS adj_frequency,
       COALESCE(v.total_variance_value, 0) AS variance_value,
       (0.5 * (s.on_hand_qty * i.unit_cost) / 10000.0
         + 0.3 * COALESCE(v.total_variance_value, 0) / 5000.0
         + 0.2 * COALESCE(a.adj_count, 0) / 10.0) AS priority_score
FROM fact_inventory_snapshot s
JOIN dim_item i ON s.item_id = i.item_id
JOIN dim_location l ON s.location_id = l.location_id
LEFT JOIN adj_freq a ON s.item_id = a.item_id AND s.location_id = a.location_id
LEFT JOIN variance_hist v ON s.item_id = v.item_id AND s.location_id = v.location_id
WHERE s.snapshot_date = (SELECT MAX(snapshot_date) FROM fact_inventory_snapshot)
  AND (? = 'all' OR l.location_code = ?)
ORDER BY priority_score DESC
LIMIT ?
"""

SQL_UC7 = """
WITH acv AS (
    SELECT d.item_id, SUM(d.demand_qty) AS demand_365d,
           SUM(d.demand_qty) * MAX(i.unit_cost) AS acv
    FROM fact_demand_daily d
    JOIN dim_item i ON d.item_id = i.item_id
    WHERE d.date >= ?
    GROUP BY d.item_id
),
ranked AS (
    SELECT i.sku, a.acv,
           SUM(a.acv) OVER (ORDER BY a.acv DESC) AS cumulative_acv,
           SUM(a.acv) OVER () AS total_acv
    FROM acv a
    JOIN dim_item i ON a.item_id = i.item_id
)
SELECT sku,
       ROUND(acv, 2) AS acv,
       ROUND(100.0 * cumulative_acv / total_acv, 2) AS cumulative_pct,
       CASE
         WHEN 100.0 * cumulative_acv / total_acv <= 80 THEN 'A'
         WHEN 100.0 * cumulative_acv / total_acv <= 95 THEN 'B'
         ELSE 'C'
       END AS abc_class
FROM ranked
ORDER BY acv DESC
LIMIT ?
"""

SQL_UC8 = """
WITH demand AS (
    SELECT item_id, location_id,
           SUM(demand_qty)::DOUBLE / ? AS avg_daily_demand
    FROM fact_demand_daily
    WHERE date >= ?
    GROUP BY item_id, location_id
),
inbound AS (
    SELECT pl.item_id, ph.ship_to_location_id AS location_id,
           SUM(pl.ordered_qty - pl.received_qty) AS inbound_open_qty,
           MIN(ph.expected_receipt_date) AS next_eta
    FROM fact_po_line pl
    JOIN fact_po_header ph ON pl.po_id = ph.po_id
    WHERE ph.status IN ('Open', 'Partially Received') AND pl.status = 'Open'
    GROUP BY pl.item_id, ph.ship_to_location_id
)
SELECT i.sku, l.location_code, s.on_hand_qty,
       COALESCE(ib.inbound_open_qty, 0) AS inbound_open_qty,
       COALESCE(d.avg_daily_demand, 0) AS avg_daily_demand,
       (s.on_hand_qty + COALESCE(ib.inbound_open_qty, 0))
         / GREATEST(COALESCE(d.avg_daily_demand, 0), 0.001) AS coverage_days,
       ib.next_eta, v.default_lead_time_days
FROM fact_inventory_snapshot s
JOIN dim_item i ON s.item_id = i.item_id
JOIN dim_location l ON s.location_id = l.location_id
JOIN dim_vendor v ON i.vendor_id = v.vendor_id
LEFT JOIN demand d ON s.item_id = d.item_id AND s.location_id = d.location_id
LEFT JOIN inbound ib ON s.item_id = ib.item_id AND s.location_id = ib.location_id
WHERE s.snapshot_date = (SELECT MAX(snapshot_date) FROM fact_inventory_snapshot)
  AND (? = 'all' OR l.location_code = ?)
  AND (s.on_hand_qty + COALESCE(ib.inbound_open_qty, 0))
        / GREATEST(COALESCE(d.avg_daily_demand, 0), 0.001) < v.default_lead_time_days
ORDER BY coverage_days ASC
LIMIT ?
"""

QUERY_BY_WORKFLOW = {
    "UC-1": ("q-uc1-001", SQL_UC1),
    "UC-2": ("q-uc2-001", SQL_UC2),
    "UC-3": ("q-uc3-001", SQL_UC3),
    "UC-4": ("q-uc4-001", SQL_UC4),
    "UC-5": ("q-uc5-001", SQL_UC5),
    "UC-6": ("q-uc6-001", SQL_UC6),
    "UC-7": ("q-uc7-001", SQL_UC7),
    "UC-8": ("q-uc8-001", SQL_UC8),
}
