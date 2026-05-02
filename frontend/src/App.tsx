import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import {
  LayoutDashboard,
  Moon,
  Send,
  Sun,
  Loader2,
  Download,
  FileJson,
  Shield,
  Sparkles,
  Settings2,
  BarChart3,
  Zap,
  LogOut,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { FindingsDataTable, type FindingRow } from "@/components/FindingsDataTable";
import { VisualizationPanel, type VisualizationPayload } from "@/components/VisualizationPanel";
import { SUGGESTED_PROMPTS } from "@/config/suggestedPrompts";
import { cn } from "@/lib/utils";
import { authHeaders, clearToken, getToken, parseJwtPayload } from "./auth";

export type ExecutiveInsights = {
  headline?: string;
  subhead?: string;
  metrics?: { label: string; value: string }[];
  bullets?: string[];
  scope_echo?: string;
  source?: string;
};

type ChatMsg = {
  id: string;
  role: "user" | "assistant";
  text: string;
  time: Date;
  /** When set, findings render as a table; narrative list is stripped from text. */
  findingsTable?: FindingRow[];
  executiveInsights?: ExecutiveInsights | null;
};

/** Remove duplicated "Findings" prose when we show a structured table instead. */
function narrativeSummaryOnly(full: string): string {
  const t = full.trim();
  const cutNumbered = t.search(/\n\s*2\.\s*Findings\b/i);
  if (cutNumbered !== -1) return t.slice(0, cutNumbered).trim();
  const cutHeading = t.search(/\n\s*Findings\s*\n/i);
  if (cutHeading !== -1) return t.slice(0, cutHeading).trim();
  return t;
}

const WELCOME =
  "Welcome. I am your governed Inventory Analytics Assistant — responses use approved SQL and rule engines only; KPIs are never invented.\n\n" +
  "Before each analysis, choose **location scope** and **demand window** below, then enable **Confirm parameters** when using **all locations** (network-wide). No KPIs run until those values are explicit.\n\n" +
  "Use the quick prompts below or ask in your own words. Each run returns an executive snapshot, visualization, findings table, and evidence suitable for leadership review.\n\n" +
  "What would you like to analyze first?";

function pickAgentMessage(data: Record<string, unknown> | null): string {
  if (!data || typeof data !== "object") return "Invalid response from server.";
  const direct =
    (data.narrative ?? data.user_message ?? data.message ?? data.assistant_message) as string | undefined;
  const t = direct != null ? String(direct).trim() : "";
  if (t && t !== "undefined" && t !== "null") return t;
  const detail = data.detail;
  if (detail != null) {
    if (typeof detail === "string") return detail;
  }
  if (data.status === "out_of_scope" && data.supported_workflows)
    return String(data.supported_workflows);
  return "No response. Check the network tab for /api/chat.";
}

function formatTs(d: Date) {
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function LoadingDots() {
  return (
    <div className="flex items-center gap-1.5 px-1 py-0.5">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-2 w-2 animate-bounce rounded-full bg-muted-foreground/70"
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </div>
  );
}

function ExecutiveInsightsBlock({ ex, compact }: { ex: ExecutiveInsights; compact?: boolean }) {
  const m = ex.metrics || [];
  return (
    <div className={cn("corp-surface", compact ? "p-3" : "p-4")}>
      <div className="mb-3 flex items-start justify-between gap-2">
        <div>
          <p className={cn("font-semibold tracking-tight text-foreground", compact ? "text-sm" : "text-base")}>
            {ex.headline}
          </p>
          {ex.subhead ? <p className="mt-1 text-xs text-muted-foreground">{ex.subhead}</p> : null}
        </div>
        <BarChart3 className="h-5 w-5 shrink-0 text-primary/80" />
      </div>
      {m.length ? (
        <div
          className={cn(
            "grid gap-2",
            compact ? "grid-cols-2 sm:grid-cols-3" : "grid-cols-2 sm:grid-cols-3 lg:grid-cols-5"
          )}
        >
          {m.map((k, i) => (
            <div key={i} className="corp-metric">
              <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">{k.label}</p>
              <p className={cn("font-semibold tabular-nums text-foreground", compact ? "text-sm" : "text-lg")}>
                {k.value}
              </p>
            </div>
          ))}
        </div>
      ) : null}
      {ex.bullets?.length ? (
        <ul className={cn("mt-3 space-y-1.5 text-muted-foreground", compact ? "text-xs" : "text-sm")}>
          {ex.bullets.map((b, i) => (
            <li key={i} className="flex gap-2">
              <Zap className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
              <span>{b}</span>
            </li>
          ))}
        </ul>
      ) : null}
      <p className="mt-3 border-t border-border/60 pt-2 text-[10px] text-muted-foreground">
        Counts and metrics are computed only from governed tool output ({ex.source || "tool_result"}).
      </p>
    </div>
  );
}

function ResultsDashboard({ data }: { data: Record<string, unknown> | null }) {
  if (!data) {
    return (
      <p className="text-sm text-muted-foreground">
        Ask a question to populate the governed results dashboard.
      </p>
    );
  }
  const fe = data.frontend as Record<string, unknown> | null | undefined;
  const analyst = data.analyst_extras as { headline?: string; bullets?: string[] } | undefined;
  const supervisor = data.supervisor_extras as { headline?: string; bullets?: string[] } | undefined;
  const auditor = data.auditor_extras as { recent_tool_calls?: unknown[] } | undefined;
  const role = data.user_role as string | undefined;

  if (!fe && data.status !== "ok") {
    return (
      <div className="space-y-4">
        <Card>
          <CardHeader>
            <CardTitle>Status</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm whitespace-pre-wrap">{pickAgentMessage(data)}</p>
            {data.supported_workflows && (
              <p className="mt-2 text-xs text-muted-foreground">{String(data.supported_workflows)}</p>
            )}
          </CardContent>
        </Card>
      </div>
    );
  }

  if (!fe) {
    return <p className="text-sm text-muted-foreground whitespace-pre-wrap">{pickAgentMessage(data)}</p>;
  }

  const table = (fe.findings_table as FindingRow[]) || [];
  const recs = (fe.recommendations as string[]) || [];
  const kpis = fe.kpis_used as { formula?: string; version?: string } | undefined;
  const ev = fe.evidence as Record<string, unknown> | undefined;
  const viz = fe.visualization as VisualizationPayload | null | undefined;
  const summaryText =
    table.length > 0 ? narrativeSummaryOnly(String(fe.summary || "")) : String(fe.summary || "");
  const exec = fe.executive_insights as ExecutiveInsights | undefined;

  return (
    <div className="space-y-5 pr-2">
      {exec ? <ExecutiveInsightsBlock ex={exec} /> : null}

      {role === "Analyst" && analyst?.bullets?.length ? (
        <Card className="corp-surface border-primary/25 bg-primary/[0.04]">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-primary">
              <Sparkles className="h-4 w-4" />
              {analyst.headline || "Insight focus"}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="list-disc space-y-1 pl-4 text-sm">
              {analyst.bullets.map((b, i) => (
                <li key={i}>{b}</li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}

      {role === "Supervisor" && supervisor?.bullets?.length ? (
        <Card className="corp-surface border-sky-500/25 bg-sky-500/[0.06]">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sky-700 dark:text-sky-300">
              <Sparkles className="h-4 w-4" />
              {supervisor.headline || "Supervisory insights (read-only)"}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="list-disc space-y-1 pl-4 text-sm">
              {supervisor.bullets.map((b, i) => (
                <li key={i}>{b}</li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}

      {role === "Auditor" && auditor?.recent_tool_calls?.length ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Shield className="h-4 w-4" />
              Audit trail (recent tool calls)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-48 rounded-md border border-border p-2">
              <pre className="text-[10px] leading-relaxed text-muted-foreground">
                {JSON.stringify(auditor.recent_tool_calls, null, 2)}
              </pre>
            </ScrollArea>
          </CardContent>
        </Card>
      ) : null}

      <Card className="corp-surface border-0 shadow-none ring-0">
        <CardHeader className="pb-2">
          <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Narrative summary
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm leading-relaxed text-foreground/90 whitespace-pre-wrap">{summaryText}</p>
        </CardContent>
      </Card>

      <div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Visualization</p>
        {viz ? (
          <VisualizationPanel viz={viz} />
        ) : (
          <div className="corp-surface border-dashed py-10 text-center">
            <BarChart3 className="mx-auto mb-2 h-8 w-8 text-muted-foreground/50" />
            <p className="px-4 text-xs text-muted-foreground">
              Charts appear here after each successful governed run (line, bar, pie, or table). Sample data is labeled
              when no rows match your filters.
            </p>
          </div>
        )}
      </div>

      <Card className="corp-surface border-0 shadow-none ring-0">
        <CardHeader className="pb-2">
          <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Findings (governed table)
          </CardTitle>
        </CardHeader>
        <CardContent>
          {table.length ? (
            <FindingsDataTable rows={table} />
          ) : (
            <p className="text-sm text-muted-foreground">No rows (see summary).</p>
          )}
        </CardContent>
      </Card>

      <Card className="corp-surface border-0 shadow-none ring-0">
        <CardHeader className="pb-2">
          <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            KPI definitions (tool-backed)
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <p className="text-sm text-muted-foreground whitespace-pre-wrap">{kpis?.formula || "—"}</p>
          <p className="text-xs text-muted-foreground">Version: {kpis?.version || "—"}</p>
        </CardContent>
      </Card>

      <Card className="corp-surface border-0 shadow-none ring-0">
        <CardHeader className="pb-2">
          <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Recommendations
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ol className="list-decimal space-y-2 pl-4 text-sm">
            {recs.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ol>
        </CardContent>
      </Card>

      <Card className="corp-surface border-0 shadow-none ring-0">
        <CardHeader className="pb-2">
          <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Evidence & lineage
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-1 text-xs font-mono text-muted-foreground">
          <p>query_id: {String(ev?.query_id ?? "—")}</p>
          <p>run_id: {String(ev?.run_id ?? "—")}</p>
          <p>snapshot_date: {String(ev?.snapshot_date ?? "—")}</p>
          <p>records_used: {String(ev?.records_used ?? "—")}</p>
          <p>tool_versions: {JSON.stringify(ev?.tool_versions || {})}</p>
          {role === "Auditor" && (
            <>
              <Separator className="my-2" />
              <p className="text-[10px] uppercase tracking-wide text-foreground">Extended (Auditor)</p>
              <ScrollArea className="h-32 rounded border border-border p-2">
                <pre className="text-[10px]">
                  {JSON.stringify(
                    (data.auditor_extras as { evidence_extension?: unknown })?.evidence_extension,
                    null,
                    2
                  )}
                </pre>
              </ScrollArea>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function ExplainView({ data }: { data: Record<string, unknown> | null }) {
  if (!data?.explain) {
    return <p className="text-sm text-muted-foreground">No explain payload yet.</p>;
  }
  const ex = data.explain as Record<string, unknown>;
  const role = data.user_role as string | undefined;
  return (
    <div className="space-y-4">
      {role === "Admin" && (
        <Card className="border-amber-500/30">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-amber-600 dark:text-amber-400">
              <Settings2 className="h-4 w-4" />
              KPI threshold reference (Admin)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-64 rounded-md border border-border">
              <pre className="p-3 text-[11px] leading-relaxed">
                {JSON.stringify(ex.kpi_threshold_explainer ?? ex.thresholds_loaded, null, 2)}
              </pre>
            </ScrollArea>
          </CardContent>
        </Card>
      )}
      <Card>
        <CardHeader>
          <CardTitle>Full explain JSON</CardTitle>
        </CardHeader>
        <CardContent>
          <ScrollArea className="h-[min(70vh,520px)] rounded-md border border-border">
            <pre className="p-3 text-[11px] leading-relaxed">{JSON.stringify(data.explain, null, 2)}</pre>
          </ScrollArea>
        </CardContent>
      </Card>
    </div>
  );
}

function ExportView({
  sessionId,
  onUnauthorized,
}: {
  sessionId: string;
  onUnauthorized: () => void;
}) {
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const download = async (path: string, filename: string) => {
    setErr(null);
    setBusy(true);
    try {
      const r = await fetch(path, { headers: { ...authHeaders() } });
      if (r.status === 401) {
        onUnauthorized();
        return;
      }
      if (!r.ok) {
        const t = await r.text();
        setErr(t || `HTTP ${r.status}`);
        return;
      }
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setErr("Download failed");
    } finally {
      setBusy(false);
    }
  };

  const csv = `/api/export/csv?session_id=${encodeURIComponent(sessionId)}`;
  const json = `/api/export/json?session_id=${encodeURIComponent(sessionId)}`;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Export governed session</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-wrap gap-3">
        <Button
          type="button"
          variant="secondary"
          disabled={busy}
          onClick={() => download(csv, `inventory_export_${sessionId}.csv`)}
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
          Download CSV
        </Button>
        <Button
          type="button"
          variant="secondary"
          disabled={busy}
          onClick={() => download(json, `inventory_export_${sessionId}.json`)}
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileJson className="h-4 w-4" />}
          Download JSON
        </Button>
        {err ? <p className="w-full text-xs text-destructive">{err}</p> : null}
        <p className="w-full text-xs text-muted-foreground">
          Exports reflect the last analysis saved for this browser session (your account only).
        </p>
      </CardContent>
    </Card>
  );
}

type AppProps = { onLogout: () => void };

export default function App({ onLogout }: AppProps) {
  const [dark, setDark] = useState(() => {
    if (typeof localStorage === "undefined") return true;
    const v = localStorage.getItem("inv-theme");
    if (v === "light") return false;
    if (v === "dark") return true;
    return true;
  });
  const [mainTab, setMainTab] = useState("chat");
  const [messages, setMessages] = useState<ChatMsg[]>([
    { id: "welcome", role: "assistant", text: WELCOME, time: new Date() },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [last, setLast] = useState<Record<string, unknown> | null>(null);
  const [health, setHealth] = useState("…");
  const [scope, setScope] = useState<string>("");
  const [dwd, setDwd] = useState<number | null>(null);
  const [parametersConfirmed, setParametersConfirmed] = useState(false);
  const [who, setWho] = useState<{ username: string; role: string }>(() => {
    const t = getToken();
    const p = t ? parseJwtPayload(t) : null;
    return {
      username: (p?.username as string) || "",
      role: (p?.role as string) || "Analyst",
    };
  });
  const sessionId = useRef(`sess-${Math.random().toString(36).slice(2, 12)}`);
  const scrollRef = useRef<HTMLDivElement>(null);

  const handleUnauthorized = useCallback(() => {
    clearToken();
    onLogout();
  }, [onLogout]);

  useEffect(() => {
    const t = getToken();
    const p = t ? parseJwtPayload(t) : null;
    setWho({
      username: (p?.username as string) || "",
      role: (p?.role as string) || "Analyst",
    });
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("inv-theme", dark ? "dark" : "light");
  }, [dark]);

  const refreshHealth = useCallback(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then((j: { db?: string }) => setHealth(j.db === "connected" ? "Connected" : j.db || "error"))
      .catch(() => setHealth("error"));
  }, []);

  useEffect(() => {
    refreshHealth();
    const t = setInterval(refreshHealth, 30000);
    return () => clearInterval(t);
  }, [refreshHealth]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, loading]);

  const submitChat = useCallback(
    async (rawText: string) => {
      const text = rawText.trim();
      if (!text || loading) return;
      setInput("");
      setMessages((m) => [...m, { id: crypto.randomUUID(), role: "user", text, time: new Date() }]);
      setLoading(true);
      try {
        const r = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders() },
          body: JSON.stringify({
            message: text,
            scope: scope === "" ? null : scope,
            demand_window_days: dwd === null ? null : dwd,
            session_id: sessionId.current,
            parameters_confirmed: parametersConfirmed,
          }),
        });
        if (r.status === 401) {
          handleUnauthorized();
          return;
        }
        const data = (await r.json()) as Record<string, unknown>;
        setLast(data);
        const fe = data.frontend as {
          findings_table?: FindingRow[];
          executive_insights?: ExecutiveInsights;
        } | null;
        const ft = fe?.findings_table;
        const exec = fe?.executive_insights;
        const reply = pickAgentMessage(data);
        const hasTable = data.status === "ok" && Array.isArray(ft) && ft.length > 0;
        const showExec = data.status === "ok" && exec && (exec.metrics?.length || exec.bullets?.length);
        setMessages((m) => [
          ...m,
          {
            id: crypto.randomUUID(),
            role: "assistant",
            text: hasTable
              ? narrativeSummaryOnly(reply) ||
                "Governed tool run complete. Findings are shown in the table below."
              : reply,
            time: new Date(),
            findingsTable: hasTable ? ft : undefined,
            executiveInsights: showExec ? exec : undefined,
          },
        ]);
      } catch {
        setMessages((m) => [
          ...m,
          { id: crypto.randomUUID(), role: "assistant", text: "Network error.", time: new Date() },
        ]);
      } finally {
        setLoading(false);
      }
    },
    [dwd, handleUnauthorized, loading, parametersConfirmed, scope]
  );

  const send = () => submitChat(input);

  const wf = (last?.routing as Record<string, unknown> | undefined)?.workflow_id;

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-card/80 px-4 py-3 backdrop-blur-sm">
        <div className="flex items-center gap-2">
          <LayoutDashboard className="h-5 w-5 text-primary" />
          <div>
            <h1 className="text-sm font-semibold tracking-tight">Inventory Analytics Agent</h1>
            <p className="text-xs text-muted-foreground">Enterprise intelligence · Governed SQL · Audit-ready</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="hidden text-right sm:block">
            <p className="text-xs font-medium text-foreground">{who.username || "—"}</p>
            <p className="text-[10px] text-muted-foreground">{who.role}</p>
          </div>
          <Button type="button" variant="outline" size="sm" className="h-8 gap-1.5 text-xs" onClick={() => onLogout()}>
            <LogOut className="h-3.5 w-3.5" />
            Log out
          </Button>
          <div className="flex items-center gap-2">
            {dark ? <Moon className="h-3.5 w-3.5 text-muted-foreground" /> : <Sun className="h-3.5 w-3.5 text-muted-foreground" />}
            <Switch checked={dark} onCheckedChange={setDark} aria-label="Toggle dark mode" />
          </div>
          <Badge variant={health === "Connected" ? "default" : "outline"} className="text-[10px]">
            DB {health}
          </Badge>
          {wf ? (
            <Badge variant="secondary" className="font-mono text-[10px]">
              {String(wf)}
            </Badge>
          ) : null}
        </div>
      </header>

      <Tabs value={mainTab} onValueChange={setMainTab} className="flex flex-1 flex-col min-h-0">
        <div className="border-b border-border bg-card/50 px-4 pt-3">
          <TabsList className="w-full max-w-md">
            <TabsTrigger value="chat" className="flex-1">
              Chat
            </TabsTrigger>
            <TabsTrigger value="explain" className="flex-1">
              Explain
            </TabsTrigger>
            <TabsTrigger value="export" className="flex-1">
              Export
            </TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="chat" className="mt-0 flex-1 min-h-0 data-[state=inactive]:hidden">
          <div className="grid h-[calc(100vh-8.5rem)] min-h-[420px] grid-cols-1 lg:grid-cols-[1fr_1.05fr]">
            <div className="flex min-h-0 flex-col border-b border-border lg:border-b-0 lg:border-r">
              <div className="border-b border-border bg-muted/30 px-3 py-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Conversation
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto" ref={scrollRef as RefObject<HTMLDivElement>}>
                <div className="space-y-3 p-4">
                  {last &&
                  last.status === "needs_clarification" &&
                  (last.reason === "missing_tool_parameters" || last.reason === "incomplete_parameters") ? (
                    <Card className="border-amber-500/40 bg-amber-500/[0.06]">
                      <CardHeader className="py-3 pb-2">
                        <CardTitle className="text-xs font-semibold text-amber-800 dark:text-amber-200">
                          Parameters required before tools run
                        </CardTitle>
                      </CardHeader>
                      <CardContent className="space-y-2 pb-3 pt-0 text-xs text-amber-950/90 dark:text-amber-50/90">
                        <p className="font-medium">Missing or unconfirmed:</p>
                        <ul className="list-disc pl-4">
                          {Array.isArray(last.missing_parameters)
                            ? (last.missing_parameters as string[]).map((x) => <li key={x}>{x}</li>)
                            : null}
                        </ul>
                        {(last.clarification_context as { location_codes?: string[] })?.location_codes?.length ? (
                          <p className="text-[11px] text-muted-foreground">
                            Locations:{" "}
                            {(last.clarification_context as { location_codes: string[] }).location_codes.join(", ")}
                          </p>
                        ) : null}
                        <p className="text-[11px] text-muted-foreground">
                          Set scope and demand window below, then send your reply inline (same chat).
                        </p>
                      </CardContent>
                    </Card>
                  ) : null}
                  {messages.map((m) => (
                    <div
                      key={m.id}
                      className={cn("flex flex-col gap-1", m.role === "user" ? "items-end" : "items-start")}
                    >
                      <div
                        className={cn(
                          "max-w-[min(92%,42rem)] rounded-2xl px-4 py-2.5 text-sm leading-relaxed shadow-sm",
                          m.role === "user"
                            ? "rounded-br-md bg-primary text-primary-foreground"
                            : "rounded-bl-md border border-border bg-card text-card-foreground"
                        )}
                      >
                        {m.role === "assistant" &&
                        (m.executiveInsights?.metrics?.length || m.findingsTable?.length) ? (
                          <div className="space-y-3">
                            {m.executiveInsights?.metrics?.length ? (
                              <ExecutiveInsightsBlock ex={m.executiveInsights} compact />
                            ) : null}
                            <p className="whitespace-pre-wrap text-foreground/90">{m.text}</p>
                            {m.findingsTable?.length ? (
                              <div>
                                <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                                  Findings (governed tool output)
                                </p>
                                <FindingsDataTable rows={m.findingsTable} dense />
                              </div>
                            ) : null}
                          </div>
                        ) : (
                          <p className="whitespace-pre-wrap">{m.text}</p>
                        )}
                      </div>
                      <span className="px-1 text-[10px] text-muted-foreground">{formatTs(m.time)}</span>
                    </div>
                  ))}
                  {loading && (
                    <div className="flex flex-col items-start gap-1">
                      <div className="rounded-2xl rounded-bl-md border border-border bg-card px-4 py-3">
                        <LoadingDots />
                      </div>
                    </div>
                  )}
                </div>
              </div>
              <div className="space-y-2 border-t border-border bg-gradient-to-b from-muted/20 to-card/40 p-3">
                <div className="flex flex-wrap gap-1.5">
                  <p className="w-full text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Quick prompts
                  </p>
                  <div className="flex max-h-[4.5rem] w-full flex-wrap gap-1.5 overflow-y-auto pr-1">
                    {SUGGESTED_PROMPTS.map((sp) => (
                      <Button
                        key={sp.id}
                        type="button"
                        variant="secondary"
                        size="sm"
                        className="h-7 rounded-full border border-border/80 px-2.5 text-[10px] font-medium"
                        disabled={loading}
                        title={sp.hint}
                        onClick={() => submitChat(sp.prompt)}
                      >
                        {sp.label}
                      </Button>
                    ))}
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <select
                    value={scope}
                    onChange={(e) => setScope(e.target.value)}
                    className="h-8 flex-1 min-w-[120px] rounded-md border border-border bg-background px-2 text-xs"
                  >
                    <option value="">— Location scope —</option>
                    <option value="all">All locations (network)</option>
                    <option value="DC-004">DC-004</option>
                    <option value="DC-006">DC-006</option>
                    <option value="Store-001">Store-001</option>
                    <option value="Store-002">Store-002</option>
                    <option value="Store-003">Store-003</option>
                    <option value="Store-005">Store-005</option>
                  </select>
                  <select
                    value={dwd === null ? "" : String(dwd)}
                    onChange={(e) => {
                      const v = e.target.value;
                      setDwd(v === "" ? null : Number(v));
                    }}
                    className="h-8 flex-1 min-w-[100px] rounded-md border border-border bg-background px-2 text-xs"
                  >
                    <option value="">— Demand window —</option>
                    <option value={7}>7d demand</option>
                    <option value={14}>14d demand</option>
                    <option value={30}>30d demand</option>
                    <option value={60}>60d demand</option>
                    <option value={90}>90d demand</option>
                  </select>
                </div>
                <div className="flex items-center justify-between gap-2 rounded-md border border-border/80 bg-muted/20 px-2 py-1.5">
                  <span className="text-[11px] text-muted-foreground">
                    Confirm when using <span className="font-medium text-foreground">all locations</span>
                  </span>
                  <Switch
                    checked={parametersConfirmed}
                    onCheckedChange={setParametersConfirmed}
                    aria-label="Confirm parameters for all-locations runs"
                  />
                </div>
                <div className="flex gap-2">
                  <input
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
                    placeholder="Ask in plain language, or use a quick prompt above…"
                    className="h-10 flex-1 rounded-lg border border-border bg-background px-3 text-sm"
                  />
                  <Button size="default" className="h-10 shrink-0 rounded-lg px-4" onClick={send} disabled={loading}>
                    {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                  </Button>
                </div>
              </div>
            </div>

            <div className="flex min-h-0 flex-col bg-muted/15">
              <div className="border-b border-border bg-muted/30 px-3 py-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Executive dashboard
              </div>
              <ScrollArea className="flex-1">
                <div className="p-4">
                  <ResultsDashboard data={last} />
                </div>
              </ScrollArea>
            </div>
          </div>
        </TabsContent>

        <TabsContent value="explain" className="mt-0 flex-1 overflow-auto p-4 data-[state=inactive]:hidden">
          <ExplainView data={last} />
        </TabsContent>

        <TabsContent value="export" className="mt-0 flex-1 overflow-auto p-4 data-[state=inactive]:hidden">
          <ExportView sessionId={sessionId.current} onUnauthorized={handleUnauthorized} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
