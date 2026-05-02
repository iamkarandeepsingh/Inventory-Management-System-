# Capability showcase — copy-paste prompts

Use **Scope** and **Demand window** in the UI for location and time; you do not need to spell them in every message unless you want to reinforce intent.

---

## 1. UC-1 — Stockout triage / ATP / replenishment

- Show stockouts and ATP-critical SKUs that need replenishment now  
- Which items are out of stock or have zero ATP?  
- Stockout triage for urgent ordering  

---

## 2. UC-2 — Backorder analysis

- List backorders and unfulfilled orders ranked by financial exposure  
- Show open backorders by value  
- What is backordered and where?  

---

## 3. UC-3 — Overstock / days of supply

- Show overstock and high days of supply items  
- Which SKUs have too much inventory versus demand?  
- Days of supply over target  

---

## 4. UC-4 — Slow movers / dead stock

- Show slow movers and dead stock with value at risk  
- Non-moving inventory with exposure  
- Low movement items ranked by risk  

---

## 5. UC-5 — Data anomaly detection (table-friendly)

- Show a table of inventory data quality anomalies  
- Data quality issues: negative on-hand, invalid cost, allocation errors  
- List anomaly findings for audit  

---

## 6. UC-6 — Cycle count priority

- Which SKUs should we cycle count next by priority score?  
- Physical count priority based on adjustments and variance  
- Cycle count queue for accuracy program  

---

## 7. UC-7 — ABC classification (pie-friendly)

- Show ABC classification distribution by consumption value  
- Run ABC analysis on annual consumption value  
- Pareto / ABC breakdown of SKUs  

---

## 8. UC-8 — On-order / PO coverage

- Show on-order coverage and stockout risk versus lead time  
- Purchase order coverage and inbound exposure  
- Coverage days below lead time  

---

## 9. Demand trends (line chart — approved demand SQL)

- Show demand trends over time for the selected location scope  
- Show demand trends over time  
- Historical demand time series for the current scope  

---

## 10. Greeting (no tools)

- Hi  
- Hello  
- Good morning  

---

## 11. Clarification path (intentionally vague — expect a follow-up question)

- Show stock  
- Check inventory  

Then answer with something specific, e.g.:  
`Show stockouts for DC-004 with 30 day demand window` (still use UI scope/window as needed).

---

## 12. Out-of-scope (expect refusal)

- What is the weather today?  
- Write me a poem  

---

## 13. UI capabilities (not chat prompts)

| Capability        | Where |
|-------------------|--------|
| **Explain** (rules, thresholds, versions) | **Explain** tab after a run |
| **Admin thresholds** | Role **Admin** → **Explain** tab |
| **Audit trail** | Role **Auditor** → results panel |
| **Insight bullets** | Role **Analyst** → results panel |
| **CSV / JSON export** | **Export** tab |
| **Dark mode** | Header toggle |
| **Visualization** | Results panel after successful tool run (line / bar / pie / table; sample if no rows) |

---

## 14. One-shot demo sequence (for a deck)

1. Demand trend: `Show demand trends over time for the selected location scope`  
2. Stockouts: `Show stockouts and ATP-critical SKUs that need replenishment now`  
3. ABC: `Show ABC classification distribution by consumption value`  
4. Anomalies: `Show a table of inventory data quality anomalies`  
5. Switch role to **Auditor** → repeat (1) to capture audit JSON  
6. Switch role to **Admin** → **Explain** tab for threshold reference  
