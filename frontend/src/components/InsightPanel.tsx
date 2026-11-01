import { CheckCircle2, ChevronDown, CircleAlert, CircleX, ExternalLink, Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { formatDuration } from "../lib/answer";
import type { Claim, Result, Source, Step } from "../lib/api";

const STEP_LABELS: Record<string, string> = {
  analyze: "Triage",
  retrieve: "Search",
  generate: "Draft",
  verify: "Fact-check",
  review: "Review",
  revise: "Revise",
  finalize: "Finish",
  write: "Write",
};
const AGENT_PLAN = ["analyze", "retrieve", "generate", "verify", "finalize"];
const FAST_PLAN = ["retrieve", "write"];

const TYPE_LABELS: Record<string, string> = {
  runbook: "Runbook",
  ticket: "Past ticket",
  postmortem: "Postmortem",
  log: "Log pattern",
  uploaded: "Your document",
};

export function StepsList(props: { mode: "agent" | "fast"; steps: Step[]; running: boolean; writing?: boolean }) {
  const { mode, steps, running, writing } = props;
  const done = new Set(steps.map((s) => s.step));
  const extra = steps.map((s) => s.step).filter((s) => !(mode === "agent" ? AGENT_PLAN : FAST_PLAN).includes(s));
  const plan = [...(mode === "agent" ? AGENT_PLAN : FAST_PLAN)];
  extra.forEach((s) => {
    if (!plan.includes(s)) plan.splice(plan.indexOf(mode === "agent" ? "finalize" : "write"), 0, s);
  });
  const finishedAll = !running;
  const current = plan.find((s) => !done.has(s));

  return (
    <ol className="grid grid-cols-[minmax(0,1fr)] gap-1.5" aria-label="Progress">
      {plan.map((name) => {
        const step = steps.find((s) => s.step === name);
        const finished = done.has(name) || (finishedAll && name === "write");
        const active = running && (name === current || (name === "write" && writing));
        return (
          <li key={name} className="flex items-center gap-2 text-[13px]">
            {finished ? (
              <CheckCircle2 size={15} className="shrink-0 text-good" aria-hidden />
            ) : active ? (
              <Loader2 size={15} className="shrink-0 animate-spin text-accent" aria-hidden />
            ) : (
              <span className="mx-[2px] size-[11px] shrink-0 rounded-full border border-line-strong" aria-hidden />
            )}
            <span className={finished || active ? "text-ink" : "text-ink-3"}>{STEP_LABELS[name] ?? name}</span>
            {step && step.ms > 0 && <span className="ml-auto text-xs text-ink-3">{formatDuration(step.ms)}</span>}
          </li>
        );
      })}
    </ol>
  );
}

function SourceCard(props: { source: Source; cited: boolean; active: boolean; onSelect: () => void }) {
  const { source, cited, active, onSelect } = props;
  const ref = useRef<HTMLLIElement>(null);
  useEffect(() => {
    if (active) ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [active]);
  const external = source.source.startsWith("http");
  return (
    <li
      ref={ref}
      className={`rounded-lg border bg-panel transition-colors ${active ? "border-accent" : "border-line"}`}
    >
      <button type="button" onClick={onSelect} aria-expanded={active} className="flex w-full gap-2 p-2.5 text-left">
        <span
          className={`mt-px grid size-5 shrink-0 place-items-center rounded text-[11px] font-semibold ${
            cited ? "bg-accent-soft text-accent-ink" : "bg-panel-2 text-ink-3"
          }`}
        >
          {source.number}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-medium">{source.title}</span>
          <span className="block truncate text-xs text-ink-3">
            {TYPE_LABELS[source.source_type] ?? source.source_type}
            {source.section ? ` · ${source.section}` : ""}
          </span>
        </span>
        <ChevronDown size={14} className={`mt-1 shrink-0 text-ink-3 transition-transform ${active ? "rotate-180" : ""}`} aria-hidden />
      </button>
      {active && (
        <div className="border-t border-line px-2.5 py-2 text-xs text-ink-2">
          <p className="m-0 break-words whitespace-pre-wrap">{source.snippet}</p>
          {external && (
            <a
              href={source.source}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-2 inline-flex items-center gap-1 font-medium text-accent-ink hover:underline"
            >
              Open source <ExternalLink size={12} aria-hidden />
            </a>
          )}
        </div>
      )}
    </li>
  );
}

const VERDICTS = {
  supported: { icon: CheckCircle2, color: "text-good", label: "Supported" },
  partial: { icon: CircleAlert, color: "text-warn", label: "Partly supported" },
  unsupported: { icon: CircleX, color: "text-bad", label: "Not found in sources" },
};

function ClaimRow({ claim }: { claim: Claim }) {
  const v = VERDICTS[claim.verdict];
  return (
    <li className="flex gap-2 text-xs">
      <v.icon size={14} className={`mt-0.5 shrink-0 ${v.color}`} aria-label={v.label} />
      <span className="text-ink-2">{claim.text.replace(/\[\d+\]/g, "")}</span>
    </li>
  );
}

function Section({ title, count, children }: { title: string; count?: number; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="mb-2 flex items-center gap-1.5 text-xs font-semibold tracking-wide text-ink-3 uppercase">
        {title}
        {count !== undefined && <span className="font-medium">({count})</span>}
      </h2>
      {children}
    </section>
  );
}

export function InsightPanel(props: {
  mode: "agent" | "fast";
  steps: Step[];
  sources: Source[];
  result: Result | null;
  running: boolean;
  writing: boolean;
  activeSource: number | null;
  onSelectSource: (n: number | null) => void;
}) {
  const { mode, steps, sources, result, running, writing, activeSource, onSelectSource } = props;
  const [showAllClaims, setShowAllClaims] = useState(false);
  const cited = new Set(result?.citations.map((c) => c.number));
  const claims = result?.claims ?? [];
  const flagged = claims.filter((c) => c.verdict !== "supported");
  const visibleClaims = showAllClaims ? claims : flagged;

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-5">
      <Section title={mode === "agent" ? "Agent steps" : "Steps"}>
        <StepsList mode={mode} steps={result?.trace ?? steps} running={running} writing={writing} />
      </Section>

      {sources.length > 0 && (
        <Section title="Sources" count={sources.length}>
          <ul className="grid grid-cols-[minmax(0,1fr)] gap-1.5">
            {sources.map((s) => (
              <SourceCard
                key={s.number}
                source={s}
                cited={cited.has(s.number)}
                active={activeSource === s.number}
                onSelect={() => onSelectSource(activeSource === s.number ? null : s.number)}
              />
            ))}
          </ul>
          {result && cited.size < sources.length && (
            <p className="mt-1.5 text-xs text-ink-3">
              {cited.size} of {sources.length} cited in the answer
            </p>
          )}
        </Section>
      )}

      {claims.length > 0 && (
        <Section title="Fact check">
          <p className="mb-2 text-xs text-ink-2">
            {flagged.length === 0
              ? `All ${claims.length} sentences were supported by the sources.`
              : `${flagged.length} of ${claims.length} sentences need a closer look.`}
          </p>
          {visibleClaims.length > 0 && <ul className="grid grid-cols-[minmax(0,1fr)] gap-2">{visibleClaims.map((c, i) => <ClaimRow key={i} claim={c} />)}</ul>}
          {flagged.length < claims.length && (
            <button
              type="button"
              onClick={() => setShowAllClaims(!showAllClaims)}
              className="mt-2 text-xs font-medium text-accent-ink hover:underline"
            >
              {showAllClaims ? "Show flagged only" : "Show every sentence"}
            </button>
          )}
        </Section>
      )}

      {result?.analysis?.category && (
        <Section title="Triage">
          <p className="m-0 text-xs text-ink-2">{result.analysis.summary}</p>
          <p className="mt-1.5 mb-0 text-xs text-ink-3">
            Category: <span className="text-ink-2">{result.analysis.category}</span>
          </p>
        </Section>
      )}
    </div>
  );
}
