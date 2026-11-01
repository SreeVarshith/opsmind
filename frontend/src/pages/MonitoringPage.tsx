import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { ErrorNote, PageHeader } from "../components/Layout";
import { formatDate, formatDuration } from "../lib/answer";
import { metricsSummary, type MetricsSummary } from "../lib/api";

const WINDOWS = [
  { hours: 24, label: "24 hours" },
  { hours: 24 * 7, label: "7 days" },
  { hours: 24 * 30, label: "30 days" },
];

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-line bg-panel p-3.5">
      <div className="text-xs text-ink-2">{label}</div>
      <div className="mt-0.5 text-2xl font-semibold tracking-tight tabular-nums">{value}</div>
      {hint && <div className="text-xs text-ink-3">{hint}</div>}
    </div>
  );
}

/** One measure, one color; every bar is labeled directly, so identity never relies on color. */
function Bars({ title, data, order, keepCase }: { title: string; data: Record<string, number>; order?: string[]; keepCase?: boolean }) {
  const rows = Object.entries(data)
    .filter(([key]) => key !== "n/a")
    .sort(([a, x], [b, y]) => (order ? order.indexOf(a) - order.indexOf(b) : y - x));
  const max = Math.max(1, ...rows.map(([, v]) => v));
  return (
    <section className="rounded-xl border border-line bg-panel p-4">
      <h2 className="mb-3 text-sm font-semibold">{title}</h2>
      {rows.length === 0 && <p className="text-[13px] text-ink-2">No data in this period.</p>}
      <dl className="grid gap-2.5">
        {rows.map(([label, value]) => (
          <div key={label} title={`${label}: ${value}`} className="grid grid-cols-[minmax(0,7.5rem)_1fr_2rem] items-center gap-2 text-[13px]">
            <dt className={`truncate text-ink-2 ${keepCase ? "" : "capitalize"}`}>{label}</dt>
            <dd className="m-0 h-2 min-w-0 rounded-sm bg-panel-2">
              <div className="h-2 rounded-r-sm bg-accent" style={{ width: `${(value / max) * 100}%` }} />
            </dd>
            <span className="text-right font-medium tabular-nums">{value}</span>
          </div>
        ))}
      </dl>
    </section>
  );
}

export function MonitoringPage() {
  const [hours, setHours] = useState(24 * 7);
  const [data, setData] = useState<MetricsSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    metricsSummary(hours)
      .then((d) => !cancelled && setData(d))
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [hours]);

  const f = data?.feedback;
  const rated = f ? f.up + f.down : 0;
  const shortModel = (m: Record<string, number>) =>
    Object.fromEntries(Object.entries(m).map(([k, v]) => [k.split("/").pop() ?? k, v]));

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <PageHeader title="Monitoring" description="How OpsMind is being used, and how well it's answering." />
          <div role="group" aria-label="Time period" className="flex rounded-lg bg-panel-2 p-0.5">
            {WINDOWS.map((w) => (
              <button
                key={w.hours}
                type="button"
                aria-pressed={hours === w.hours}
                onClick={() => setHours(w.hours)}
                className={`rounded-md px-2.5 py-1 text-xs font-medium ${hours === w.hours ? "bg-panel text-ink shadow-sm" : "text-ink-2 hover:text-ink"}`}
              >
                {w.label}
              </button>
            ))}
          </div>
        </div>

        {error && <ErrorNote>{error}</ErrorNote>}
        {!data && !error && <Loader2 size={18} className="animate-spin text-accent" aria-label="Loading" />}

        {data && f && (
          <div className="grid gap-4">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
              <Tile label="Questions" value={String(data.total_queries)} hint={`${data.errors} failed`} />
              <Tile label="Median time" value={data.latency_ms.p50 != null ? formatDuration(data.latency_ms.p50) : "n/a"} />
              <Tile label="95th percentile" value={data.latency_ms.p95 != null ? formatDuration(data.latency_ms.p95) : "n/a"} />
              <Tile label="Avg. verified" value={data.mean_support_rate != null ? `${Math.round(data.mean_support_rate * 100)}%` : "n/a"} hint="Careful mode" />
              <Tile label="Marked helpful" value={rated ? `${Math.round((f.up / rated) * 100)}%` : "n/a"} hint={`${rated} rated · ${f.fixed} fixed`} />
            </div>

            <div className="grid gap-4 md:grid-cols-3">
              <Bars title="Answer confidence" data={data.by_confidence} order={["high", "medium", "low", "unverified", "none", "n/a"]} />
              <Bars title="Questions by mode" data={Object.fromEntries(Object.entries(data.by_endpoint).map(([k, v]) => [k === "agent" ? "Careful" : k === "ask" || k === "fast" ? "Fast" : k, v]))} />
              <Bars title="Models used" data={shortModel(data.by_model)} keepCase />
            </div>

            <section className="overflow-hidden rounded-xl border border-line bg-panel">
              <h2 className="px-4 pt-3.5 pb-2 text-sm font-semibold">Recent questions</h2>
              {data.recent.length === 0 ? (
                <p className="px-4 pb-4 text-[13px] text-ink-2">Questions will appear here once people start asking.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[640px] text-left text-[13px]">
                    <thead className="border-y border-line bg-panel-2 text-xs text-ink-2">
                      <tr>
                        {["Question", "User", "Mode", "Result", "Time", "When"].map((h) => (
                          <th key={h} scope="col" className="px-4 py-2 font-medium">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {data.recent.map((r) => (
                        <tr key={r.id}>
                          <td className="max-w-xs truncate px-4 py-2" title={r.question}>{r.question}</td>
                          <td className="px-4 py-2 text-ink-2">{r.username}</td>
                          <td className="px-4 py-2 text-ink-2">{r.endpoint === "agent" ? "Careful" : "Fast"}</td>
                          <td className="px-4 py-2 text-ink-2 capitalize">
                            {r.error ? <span className="text-bad">Failed</span> : r.confidence ?? "Answered"}
                          </td>
                          <td className="px-4 py-2 whitespace-nowrap text-ink-2 tabular-nums">{r.total_ms != null ? formatDuration(r.total_ms) : "-"}</td>
                          <td className="px-4 py-2 whitespace-nowrap text-ink-3">{formatDate(r.ts)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>
        )}
      </div>
    </div>
  );
}
