import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

export type FindingRow = {
  rank?: unknown;
  sku?: unknown;
  location?: unknown;
  key_kpi?: unknown;
  severity_score?: unknown;
  recommended_action?: unknown;
  action_color?: unknown;
};

function actionVariant(act: string): "escalate" | "monitor" | "investigate" | "outline" {
  if (act === "ESCALATE") return "escalate";
  if (act === "MONITOR") return "monitor";
  if (act === "INVESTIGATE") return "investigate";
  return "outline";
}

export function FindingsDataTable({
  rows,
  className,
  dense,
}: {
  rows: FindingRow[];
  className?: string;
  dense?: boolean;
}) {
  if (!rows.length) return null;
  return (
    <div className={cn("rounded-md border border-border bg-card", className)}>
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/50 hover:bg-muted/50">
            <TableHead className={cn(dense && "h-8 px-1.5")}>Rank</TableHead>
            <TableHead className={cn(dense && "h-8 px-1.5")}>SKU</TableHead>
            <TableHead className={cn(dense && "h-8 px-1.5")}>Location</TableHead>
            <TableHead className={cn(dense && "h-8 px-1.5")}>Key KPI</TableHead>
            <TableHead className={cn(dense && "h-8 px-1.5")}>Severity</TableHead>
            <TableHead className={cn(dense && "h-8 px-1.5")}>Action</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, i) => {
            const act = String(row.recommended_action ?? "");
            return (
              <TableRow key={i}>
                <TableCell className={cn("font-medium", dense && "px-1.5 py-1.5")}>{String(row.rank ?? "—")}</TableCell>
                <TableCell className={cn("font-mono", dense && "px-1.5 py-1.5")}>{String(row.sku ?? "—")}</TableCell>
                <TableCell className={cn(dense && "px-1.5 py-1.5")}>{String(row.location ?? "—")}</TableCell>
                <TableCell className={cn(dense && "px-1.5 py-1.5")}>{String(row.key_kpi ?? "—")}</TableCell>
                <TableCell className={cn("tabular-nums", dense && "px-1.5 py-1.5")}>
                  {String(row.severity_score ?? "—")}
                </TableCell>
                <TableCell className={cn(dense && "px-1.5 py-1.5")}>
                  <Badge variant={actionVariant(act)} className="text-[10px]">
                    {act || "—"}
                  </Badge>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
