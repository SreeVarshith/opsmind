import { CheckCircle2, CircleAlert, Loader2, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

const INCIDENTS = [
  {
    alert: "etcdNoLeader",
    service: "control-plane",
    message: "etcd cluster reports no leader and kubectl commands time out",
    cause: "Quorum was lost: control-plane members can't reach each other",
    command: "etcdctl endpoint health -w table",
    sources: ["etcdNoLeader runbook", "INC-0028"],
  },
  {
    alert: "KubePodCrashLooping",
    service: "checkout-api",
    message: "Pods keep restarting. Last state: Terminated, reason: OOMKilled",
    cause: "The container is exceeding its memory limit",
    command: "kubectl -n $NAMESPACE describe pod $POD",
    sources: ["KubePodCrashLooping runbook", "INC-0105"],
  },
];

const STEPS = ["Triage", "Search", "Draft", "Fact-check"];
const TICK_MS = 750;
const HOLD_TICKS = 8; // how long the finished answer stays on screen

function reducedMotion(): boolean {
  return typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** A looping, purely decorative example of what the product does. No data is loaded. */
export function IncidentPreview() {
  const [tick, setTick] = useState(() => (reducedMotion() ? STEPS.length : 0));
  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (reducedMotion()) return;
    const timer = setInterval(() => {
      setTick((t) => {
        if (t < STEPS.length + HOLD_TICKS) return t + 1;
        setIndex((i) => (i + 1) % INCIDENTS.length);
        return 0;
      });
    }, TICK_MS);
    return () => clearInterval(timer);
  }, []);

  const incident = INCIDENTS[index];
  const answered = tick >= STEPS.length;

  return (
    <figure aria-label="Example of OpsMind answering an incident" className="m-0 w-full max-w-md">
      <div className="overflow-hidden rounded-xl border border-line bg-bg">
        <div className="flex items-center gap-2 border-b border-line bg-panel px-3.5 py-2.5">
          <CircleAlert size={15} className="shrink-0 text-bad" aria-hidden />
          <span className="truncate font-mono text-xs font-semibold">{incident.alert}</span>
          <span className="ml-auto shrink-0 rounded bg-bad-soft px-1.5 py-0.5 text-[11px] font-medium text-bad">firing</span>
        </div>

        <div className="grid gap-3 p-3.5">
          <p className="m-0 ml-auto max-w-[90%] rounded-2xl rounded-br-sm bg-panel-2 px-3 py-1.5 text-[13px]">
            {incident.message}
          </p>

          <ol className="m-0 flex list-none flex-wrap items-center gap-x-3 gap-y-1 p-0">
            {STEPS.map((step, i) => {
              const done = i < tick;
              const active = i === tick;
              return (
                <li key={step} className={`flex items-center gap-1 text-xs ${done || active ? "text-ink" : "text-ink-3"}`}>
                  {done ? (
                    <CheckCircle2 size={13} className="text-good" aria-hidden />
                  ) : active ? (
                    <Loader2 size={13} className="animate-spin text-accent" aria-hidden />
                  ) : (
                    <span className="mx-px size-[11px] rounded-full border border-line-strong" aria-hidden />
                  )}
                  {step}
                </li>
              );
            })}
          </ol>

          <div
            className={`rounded-lg border border-line bg-panel p-3 transition-opacity duration-500 ${
              answered ? "opacity-100" : "opacity-0"
            }`}
          >
            <div className="mb-2 inline-flex items-center gap-1 rounded bg-good-soft px-1.5 py-0.5 text-[11px] font-medium text-good">
              <ShieldCheck size={12} aria-hidden /> High confidence
            </div>
            <p className="m-0 text-[13px] font-medium">Most likely cause</p>
            <p className="m-0 text-[13px] text-ink-2">
              {incident.cause}
              <span className="ml-1 inline-grid size-4 place-items-center rounded bg-accent-soft align-[1px] text-[10px] font-semibold text-accent-ink">
                1
              </span>
            </p>
            <code className="mt-2 block truncate rounded-md bg-panel-2 px-2 py-1.5 font-mono text-xs">{incident.command}</code>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {incident.sources.map((source, i) => (
                <span key={source} className="inline-flex items-center gap-1 rounded border border-line px-1.5 py-0.5 text-[11px] text-ink-2">
                  <span className="font-semibold text-accent-ink">{i + 1}</span> {source}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>
      <figcaption className="mt-2 text-center text-xs text-ink-3">Example incident</figcaption>
    </figure>
  );
}
