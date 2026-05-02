import { useMemo } from "react";
import {
  ArcElement,
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Filler,
  Legend,
  LinearScale,
  LineElement,
  PointElement,
  Title,
  Tooltip,
} from "chart.js";
import { Bar, Line, Pie } from "react-chartjs-2";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  ArcElement,
  Title,
  Tooltip,
  Legend,
  Filler
);

export type VisualizationPayload = {
  graph_type: "line" | "bar" | "pie" | "table";
  title: string;
  x_axis: string;
  y_axis: string;
  data: unknown[];
  sample_data?: boolean;
  disclaimer?: string | null;
  viz_version?: string;
};

function useChartColors() {
  const dark = typeof document !== "undefined" && document.documentElement.classList.contains("dark");
  return {
    fg: dark ? "#e2e8f0" : "#334155",
    grid: dark ? "rgba(148,163,184,0.15)" : "rgba(100,116,139,0.2)",
    primary: dark ? "#60a5fa" : "#2563eb",
    accent: dark ? "#34d399" : "#059669",
  };
}

export function VisualizationPanel({ viz }: { viz: VisualizationPayload | null | undefined }) {
  const colors = useChartColors();

  const chartOptions = useMemo(
    () => ({
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          labels: { color: colors.fg, font: { size: 11 } },
        },
        title: { display: false },
        tooltip: {
          titleColor: colors.fg,
          bodyColor: colors.fg,
          backgroundColor: "rgba(15,23,42,0.92)",
          borderColor: colors.grid,
          borderWidth: 1,
        },
      },
      scales:
        viz?.graph_type === "pie"
          ? undefined
          : {
              x: {
                ticks: { color: colors.fg, maxRotation: 45, minRotation: 0, font: { size: 10 } },
                grid: { color: colors.grid },
                title: {
                  display: !!viz?.x_axis,
                  text: viz?.x_axis || "",
                  color: colors.fg,
                  font: { size: 11 },
                },
              },
              y: {
                ticks: { color: colors.fg, font: { size: 10 } },
                grid: { color: colors.grid },
                title: {
                  display: !!viz?.y_axis,
                  text: viz?.y_axis || "",
                  color: colors.fg,
                  font: { size: 11 },
                },
              },
            },
    }),
    [colors, viz?.graph_type, viz?.x_axis, viz?.y_axis]
  );

  const lineConfig = useMemo(() => {
    if (!viz || viz.graph_type !== "line") return null;
    const pts = (viz.data || []) as { x?: string; y?: number }[];
    return {
      labels: pts.map((p) => String(p.x ?? "")),
      datasets: [
        {
          label: viz.y_axis || "Series",
          data: pts.map((p) => Number(p.y ?? 0)),
          borderColor: colors.primary,
          backgroundColor: `${colors.primary}33`,
          fill: true,
          tension: 0.25,
          pointRadius: 3,
        },
      ],
    };
  }, [viz, colors.primary]);

  const barConfig = useMemo(() => {
    if (!viz || viz.graph_type !== "bar") return null;
    const pts = (viz.data || []) as { label?: string; value?: number }[];
    return {
      labels: pts.map((p) => String(p.label ?? "")),
      datasets: [
        {
          label: viz.y_axis || "Value",
          data: pts.map((p) => Number(p.value ?? 0)),
          backgroundColor: `${colors.primary}cc`,
          borderColor: colors.primary,
          borderWidth: 1,
          borderRadius: 4,
        },
      ],
    };
  }, [viz, colors.primary]);

  const pieConfig = useMemo(() => {
    if (!viz || viz.graph_type !== "pie") return null;
    const pts = (viz.data || []) as { label?: string; value?: number }[];
    const palette = ["#2563eb", "#059669", "#d97706", "#dc2626", "#7c3aed", "#0891b2"];
    return {
      labels: pts.map((p) => String(p.label ?? "")),
      datasets: [
        {
          data: pts.map((p) => Number(p.value ?? 0)),
          backgroundColor: pts.map((_, i) => palette[i % palette.length]),
          borderColor: "hsl(var(--card))",
          borderWidth: 2,
        },
      ],
    };
  }, [viz]);

  if (!viz || !viz.graph_type) return null;

  return (
    <Card className={viz.sample_data ? "border-amber-500/40 bg-amber-500/5" : ""}>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-semibold normal-case tracking-normal text-foreground">
          Visualization
        </CardTitle>
        <p className="text-xs text-muted-foreground">{viz.title}</p>
      </CardHeader>
      <CardContent className="space-y-3">
        {viz.disclaimer ? (
          <p className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs leading-relaxed text-amber-900 dark:text-amber-100">
            {viz.disclaimer}
          </p>
        ) : null}
        {viz.graph_type === "table" ? (
          <div className="overflow-x-auto rounded-md border border-border">
            {!viz.data?.length ? (
              <p className="p-4 text-xs text-muted-foreground">No rows to display.</p>
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border bg-muted/40">
                    {typeof viz.data[0] === "object" && viz.data[0] !== null
                      ? Object.keys(viz.data[0] as object).map((k) => (
                          <th key={k} className="p-2 text-left font-medium text-muted-foreground">
                            {k}
                          </th>
                        ))
                      : null}
                  </tr>
                </thead>
                <tbody>
                  {(viz.data as Record<string, unknown>[]).map((row, i) => (
                    <tr key={i} className="border-b border-border/80">
                      {Object.values(row).map((cell, j) => (
                        <td key={j} className="p-2 font-mono">
                          {String(cell ?? "—")}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        ) : (
          <div className="h-64 w-full">
            {viz.graph_type === "line" && lineConfig ? (
              <Line data={lineConfig} options={chartOptions} />
            ) : null}
            {viz.graph_type === "bar" && barConfig ? (
              <Bar data={barConfig} options={chartOptions} />
            ) : null}
            {viz.graph_type === "pie" && pieConfig ? (
              <Pie
                data={pieConfig}
                options={{
                  ...chartOptions,
                  plugins: {
                    ...chartOptions.plugins,
                    legend: { position: "right" as const, labels: { color: colors.fg, font: { size: 11 } } },
                  },
                }}
              />
            ) : null}
          </div>
        )}
        <p className="text-[10px] text-muted-foreground">
          Charts are for visualization only. KPIs and findings above remain governed tool outputs.
          {viz.viz_version ? ` · ${viz.viz_version}` : ""}
        </p>
      </CardContent>
    </Card>
  );
}
