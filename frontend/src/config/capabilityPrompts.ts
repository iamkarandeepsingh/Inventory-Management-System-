/**
 * Full catalog of example prompts aligned with governed workflows and UI.
 * See repo root capability_prompts.md for the same list with notes.
 */

export const CAPABILITY_PROMPTS = {
  uc1_stockout: [
    "Show stockouts and ATP-critical SKUs that need replenishment now",
    "Which items are out of stock or have zero ATP?",
  ],
  uc2_backorder: [
    "List backorders and unfulfilled orders ranked by financial exposure",
    "Show open backorders by value",
  ],
  uc3_overstock: [
    "Show overstock and high days of supply items",
    "Which SKUs have too much inventory versus demand?",
  ],
  uc4_slow: [
    "Show slow movers and dead stock with value at risk",
    "Non-moving inventory with exposure",
  ],
  uc5_anomaly: [
    "Show a table of inventory data quality anomalies",
    "Data quality issues: negative on-hand, invalid cost, allocation errors",
  ],
  uc6_cycle: [
    "Which SKUs should we cycle count next by priority score?",
    "Cycle count priority based on adjustments and variance",
  ],
  uc7_abc: [
    "Show ABC classification distribution by consumption value",
    "Run ABC analysis on annual consumption value",
  ],
  uc8_coverage: [
    "Show on-order coverage and stockout risk versus lead time",
    "Purchase order coverage and inbound exposure",
  ],
  demand_trend: [
    "Show demand trends over time for the selected location scope",
    "Show demand trends over time",
  ],
  greeting: ["Hi", "Hello", "Good morning"],
  ambiguous_then_refine: ["Show stock", "Check inventory"],
  out_of_scope: ["What is the weather today?"],
} as const;

/** Flat list for search / tooling */
export function allCapabilityPromptsFlat(): string[] {
  return Object.values(CAPABILITY_PROMPTS).flatMap((a) => [...a]);
}
