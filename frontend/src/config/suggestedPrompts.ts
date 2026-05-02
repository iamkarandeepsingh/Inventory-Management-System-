/** One-click prompts for demos, reports, and governed workflows. */

export type SuggestedPrompt = { id: string; label: string; prompt: string; hint?: string };

export const SUGGESTED_PROMPTS: SuggestedPrompt[] = [
  {
    id: "stockout",
    label: "Stockout triage",
    prompt: "Show stockouts and ATP-critical SKUs that need replenishment now",
    hint: "UC-1 · table + bar chart",
  },
  {
    id: "trend",
    label: "Demand trend",
    prompt: "Show demand trends over time for the selected location scope",
    hint: "Uses Scope + Demand window dropdowns (not city names). Line chart from approved SQL.",
  },
  {
    id: "backorder",
    label: "Backorders",
    prompt: "List backorders and unfulfilled orders ranked by financial exposure",
    hint: "UC-2",
  },
  {
    id: "overstock",
    label: "Overstock / DOS",
    prompt: "Show overstock and high days of supply items",
    hint: "UC-3",
  },
  {
    id: "slow",
    label: "Slow movers",
    prompt: "Show slow movers and dead stock with value at risk",
    hint: "UC-4",
  },
  {
    id: "anomaly",
    label: "Data anomalies",
    prompt: "Show a table of inventory data quality anomalies",
    hint: "UC-5 · table view",
  },
  {
    id: "cycle",
    label: "Cycle count",
    prompt: "Which SKUs should we cycle count next by priority score?",
    hint: "UC-6",
  },
  {
    id: "abc",
    label: "ABC distribution",
    prompt: "Show ABC classification distribution by consumption value",
    hint: "UC-7 · pie-friendly",
  },
  {
    id: "coverage",
    label: "On-order coverage",
    prompt: "Show on-order coverage and stockout risk versus lead time",
    hint: "UC-8",
  },
];
