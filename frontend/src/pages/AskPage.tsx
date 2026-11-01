import {
  CircleCheck,
  CircleHelp,
  Cloud,
  Laptop,
  Loader2,
  Plus,
  Send,
  ShieldAlert,
  ShieldCheck,
  ShieldQuestion,
  Sparkles,
  Square,
  ThumbsDown,
  ThumbsUp,
  Wrench,
  Zap,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { ErrorNote } from "../components/Layout";
import { InsightPanel } from "../components/InsightPanel";
import { Markdown } from "../components/Markdown";
import { formatDuration, normalizeCitations } from "../lib/answer";
import {
  getConversation,
  sendFeedback,
  streamAnswer,
  type Result,
  type Source,
  type Step,
  type StoredMessage,
} from "../lib/api";

type Mode = "agent" | "fast";
type Provider = "openai_compat" | "ollama";

interface Turn {
  key: string;
  question: string;
  mode: Mode;
  steps: Step[];
  sources: Source[];
  draft: string;
  result: Result | null;
  running: boolean;
  error: string | null;
  messageId: string | null;
  rating: "up" | "down" | null;
  fixed: boolean | null;
}

const EXAMPLES = [
  "Pods in checkout-api keep restarting and kubectl shows OOMKilled",
  "etcd cluster reports no leader and kubectl commands time out",
  "Prometheus is not sending alerts to Alertmanager",
  "A node shows NotReady and pods are stuck in Terminating",
];

const CONFIDENCE = {
  high: { icon: ShieldCheck, label: "High confidence", tone: "bg-good-soft text-good" },
  medium: { icon: ShieldQuestion, label: "Medium confidence", tone: "bg-warn-soft text-warn" },
  low: { icon: ShieldAlert, label: "Low confidence", tone: "bg-bad-soft text-bad" },
  unverified: { icon: CircleHelp, label: "Not verified", tone: "bg-panel-2 text-ink-2" },
  none: { icon: CircleHelp, label: "No sources found", tone: "bg-panel-2 text-ink-2" },
};

function turnsFromMessages(messages: StoredMessage[]): Turn[] {
  const turns: Turn[] = [];
  for (let i = 0; i < messages.length - 1; i += 1) {
    const [q, a] = [messages[i], messages[i + 1]];
    if (q.role !== "user" || a.role !== "assistant" || !a.result) continue;
    turns.push({
      key: a.id,
      question: q.content,
      mode: a.mode === "fast" ? "fast" : "agent",
      steps: a.result.trace ?? [],
      sources: a.result.sources,
      draft: a.content,
      result: a.result,
      running: false,
      error: null,
      messageId: a.id,
      rating: a.rating,
      fixed: a.fixed,
    });
  }
  return turns;
}

function Toggle<T extends string>(props: {
  label: string;
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string; icon: ReactNode; title: string }[];
}) {
  return (
    <div role="group" aria-label={props.label} className="flex rounded-lg bg-panel-2 p-0.5">
      {props.options.map((o) => (
        <button
          key={o.value}
          type="button"
          title={o.title}
          aria-pressed={props.value === o.value}
          onClick={() => props.onChange(o.value)}
          className={`flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium transition-colors ${
            props.value === o.value ? "bg-panel text-ink shadow-sm" : "text-ink-2 hover:text-ink"
          }`}
        >
          {o.icon}
          {o.label}
        </button>
      ))}
    </div>
  );
}

function FeedbackBar({ turn, onChange }: { turn: Turn; onChange: (rating: Turn["rating"], fixed: Turn["fixed"]) => void }) {
  const base = "flex items-center gap-1.5 rounded-md px-2 py-1 text-xs transition-colors";
  const off = "text-ink-3 hover:bg-panel-2 hover:text-ink";
  return (
    <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Rate this answer">
      <button
        type="button"
        aria-pressed={turn.rating === "up"}
        aria-label="Helpful"
        title="Helpful"
        onClick={() => onChange(turn.rating === "up" ? null : "up", turn.fixed)}
        className={`${base} ${turn.rating === "up" ? "bg-good-soft text-good" : off}`}
      >
        <ThumbsUp size={14} aria-hidden />
      </button>
      <button
        type="button"
        aria-pressed={turn.rating === "down"}
        aria-label="Not helpful"
        title="Not helpful"
        onClick={() => onChange(turn.rating === "down" ? null : "down", turn.fixed)}
        className={`${base} ${turn.rating === "down" ? "bg-bad-soft text-bad" : off}`}
      >
        <ThumbsDown size={14} aria-hidden />
      </button>
      <button
        type="button"
        aria-pressed={turn.fixed === true}
        onClick={() => onChange(turn.rating, turn.fixed === true ? null : true)}
        className={`${base} ${turn.fixed === true ? "bg-good-soft font-medium text-good" : off}`}
      >
        <Wrench size={13} aria-hidden />
        This fixed it
      </button>
    </div>
  );
}

function AnswerMeta({ turn }: { turn: Turn }) {
  const r = turn.result;
  if (!r) return null;
  const ms = r.total_ms ?? r.timings?.total_ms;
  const items = [
    r.support_rate != null ? `${Math.round(r.support_rate * 100)}% verified` : null,
    `${Math.round(r.citation_coverage * 100)}% cited`,
    r.revisions ? "revised once" : null,
    ms != null ? formatDuration(ms) : null,
  ].filter(Boolean);
  return <span className="text-xs text-ink-3">{items.join(" · ")}</span>;
}

export function AskPage() {
  const [params, setParams] = useSearchParams();
  const conversationParam = params.get("c");
  const [conversationId, setConversationId] = useState<string | null>(conversationParam);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState<Mode>("agent");
  const [provider, setProvider] = useState<Provider>("openai_compat");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [activeSource, setActiveSource] = useState<number | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const justSaved = useRef<string | null>(null);

  const running = turns.some((t) => t.running);
  const selected = turns.find((t) => t.key === selectedKey) ?? turns[turns.length - 1] ?? null;

  const patchTurn = useCallback((key: string, patch: (t: Turn) => Partial<Turn>) => {
    setTurns((all) => all.map((t) => (t.key === key ? { ...t, ...patch(t) } : t)));
  }, []);

  // Open a saved conversation, or reset when "New incident" clears the URL.
  useEffect(() => {
    if (conversationParam === justSaved.current && conversationParam) return;
    abort.current?.abort();
    setLoadError(null);
    setConversationId(conversationParam);
    setSelectedKey(null);
    setActiveSource(null);
    if (!conversationParam) {
      setTurns([]);
      return;
    }
    let cancelled = false;
    getConversation(conversationParam)
      .then((c) => {
        if (!cancelled) setTurns(turnsFromMessages(c.messages));
      })
      .catch((e: Error) => {
        if (!cancelled) setLoadError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [conversationParam]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns.length, selected?.draft.length === 0, selected?.result]);

  const ask = async (text: string) => {
    const q = text.trim();
    if (q.length < 3 || running) return;
    const key = crypto.randomUUID();
    const askedMode = mode;
    setQuestion("");
    setSelectedKey(null);
    setActiveSource(null);
    setTurns((all) => [
      ...all,
      { key, question: q, mode: askedMode, steps: [], sources: [], draft: "", result: null, running: true, error: null, messageId: null, rating: null, fixed: null },
    ]);
    const controller = new AbortController();
    abort.current = controller;
    try {
      await streamAnswer(
        { question: q, conversation_id: conversationId, mode: askedMode, provider },
        (e) => {
          if (e.type === "step") patchTurn(key, (t) => ({ steps: [...t.steps, { step: e.step, ms: e.ms, detail: e.detail }] }));
          else if (e.type === "sources") patchTurn(key, () => ({ sources: e.sources }));
          else if (e.type === "token") patchTurn(key, (t) => ({ draft: t.draft + e.text }));
          else if (e.type === "result") patchTurn(key, () => ({ result: e.result, sources: e.result.sources, draft: e.result.answer, running: false }));
          else if (e.type === "saved") {
            patchTurn(key, () => ({ messageId: e.message_id }));
            setConversationId(e.conversation_id);
            justSaved.current = e.conversation_id;
            setParams({ c: e.conversation_id }, { replace: true });
          } else if (e.type === "error") patchTurn(key, () => ({ error: e.detail, running: false }));
        },
        controller.signal,
      );
      patchTurn(key, (t) => (t.running ? { running: false, error: t.result ? null : "The answer stopped early. Try again." } : {}));
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") {
        patchTurn(key, () => ({ running: false, error: "Stopped." }));
      } else {
        patchTurn(key, () => ({ running: false, error: e instanceof Error ? e.message : "Something went wrong." }));
      }
    }
    input.current?.focus();
  };

  const rate = (turn: Turn, rating: Turn["rating"], fixed: Turn["fixed"]) => {
    if (!turn.messageId) return;
    patchTurn(turn.key, () => ({ rating, fixed }));
    sendFeedback(turn.messageId, rating, fixed).catch(() => patchTurn(turn.key, () => ({ rating: turn.rating, fixed: turn.fixed })));
  };

  const newIncident = () => {
    abort.current?.abort();
    justSaved.current = null;
    setParams({});
    setTurns([]);
    setConversationId(null);
    setQuestion("");
    input.current?.focus();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void ask(question);
    }
  };

  const cite = (turn: Turn, n: number) => {
    setSelectedKey(turn.key);
    setActiveSource((cur) => (cur === n && selected?.key === turn.key ? null : n));
  };

  const panel = selected && (
    <InsightPanel
      mode={selected.mode}
      steps={selected.steps}
      sources={selected.sources}
      result={selected.result}
      running={selected.running}
      writing={selected.draft.length > 0}
      activeSource={activeSource}
      onSelectSource={setActiveSource}
    />
  );

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-3 border-b border-line bg-panel px-4 py-2.5">
          <h1 className="truncate text-sm font-semibold">
            {turns.length ? turns[0].question : "New incident"}
          </h1>
          {(turns.length > 0 || conversationId) && (
            <button
              type="button"
              onClick={newIncident}
              className="flex shrink-0 items-center gap-1.5 rounded-lg border border-line-strong px-2.5 py-1 text-xs font-medium hover:bg-panel-2"
            >
              <Plus size={14} aria-hidden /> New incident
            </button>
          )}
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-3xl px-4 py-5">
            {loadError && <ErrorNote>{loadError}</ErrorNote>}
            {turns.length === 0 && !loadError && (
              <div className="pt-[8vh] text-center">
                <span className="inline-grid rounded-xl bg-accent-soft p-3 text-accent-ink">
                  <Sparkles size={22} aria-hidden />
                </span>
                <h2 className="mt-3 text-xl font-semibold tracking-tight">What's going wrong?</h2>
                <p className="mx-auto mt-1 max-w-md text-ink-2">
                  Paste an error or describe the symptoms. You'll get likely causes and fixes, linked to their sources.
                </p>
                <ul className="mx-auto mt-6 grid max-w-2xl gap-2 text-left sm:grid-cols-2">
                  {EXAMPLES.map((ex) => (
                    <li key={ex}>
                      <button
                        type="button"
                        onClick={() => void ask(ex)}
                        className="h-full w-full rounded-xl border border-line bg-panel p-3 text-left text-[13px] text-ink-2 transition-colors hover:border-line-strong hover:text-ink"
                      >
                        {ex}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="grid grid-cols-[minmax(0,1fr)] gap-6">
              {turns.map((turn) => {
                const confidence = turn.result?.confidence ? CONFIDENCE[turn.result.confidence] : null;
                const isSelected = turn.key === selected?.key;
                return (
                  <article key={turn.key} className="grid grid-cols-[minmax(0,1fr)] gap-3">
                    <div className="ml-auto max-w-[85%] rounded-2xl rounded-br-sm bg-panel-2 px-3.5 py-2 break-words whitespace-pre-wrap">
                      {turn.question}
                    </div>
                    <div
                      onClick={() => setSelectedKey(turn.key)}
                      className={`min-w-0 rounded-xl border bg-panel p-4 ${
                        isSelected && turns.length > 1 ? "border-line-strong" : "border-line"
                      }`}
                    >
                      {confidence && (
                        <div className={`mb-3 inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium ${confidence.tone}`}>
                          <confidence.icon size={14} aria-hidden />
                          {confidence.label}
                        </div>
                      )}
                      {turn.draft ? (
                        <div className={turn.running ? "caret" : ""}>
                          <Markdown
                            text={turn.result ? turn.result.answer : normalizeCitations(turn.draft)}
                            onCite={(n) => cite(turn, n)}
                            activeCite={isSelected ? activeSource : null}
                          />
                        </div>
                      ) : (
                        turn.running && (
                          <div className="flex items-center gap-2 text-[13px] text-ink-2" role="status">
                            <Loader2 size={15} className="animate-spin text-accent" aria-hidden />
                            {turn.mode === "agent" ? "Working through the incident..." : "Searching your knowledge base..."}
                          </div>
                        )
                      )}
                      {turn.error && <ErrorNote>{turn.error}</ErrorNote>}
                      {turn.result && turn.messageId && (
                        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-2.5">
                          <FeedbackBar turn={turn} onChange={(rating, fixed) => rate(turn, rating, fixed)} />
                          <AnswerMeta turn={turn} />
                        </div>
                      )}
                    </div>
                    {isSelected && panel && (
                      <div className="rounded-xl border border-line bg-bg p-3 lg:hidden">{panel}</div>
                    )}
                  </article>
                );
              })}
            </div>
            <div ref={bottom} />
          </div>
        </div>

        <div className="border-t border-line bg-panel px-4 py-3">
          <div className="mx-auto w-full max-w-3xl">
            <div className="rounded-xl border border-line-strong bg-panel transition-colors focus-within:border-accent">
              <textarea
                ref={input}
                rows={2}
                maxLength={8000}
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={onKeyDown}
                aria-label="Describe the incident"
                placeholder={turns.length ? "Ask a follow-up, like: what if that doesn't work?" : "CrashLoopBackOff on the payments pods after the last deploy"}
                className="block w-full resize-none bg-transparent px-3 py-2.5 outline-none placeholder:text-ink-3"
              />
              <div className="flex flex-wrap items-center gap-2 px-2 pb-2">
                <Toggle<Mode>
                  label="Answer mode"
                  value={mode}
                  onChange={setMode}
                  options={[
                    { value: "agent", label: "Careful", icon: <CircleCheck size={13} aria-hidden />, title: "Fact-checks every sentence. A few seconds slower." },
                    { value: "fast", label: "Fast", icon: <Zap size={13} aria-hidden />, title: "Writes the answer live, without a fact check." },
                  ]}
                />
                <Toggle<Provider>
                  label="Model"
                  value={provider}
                  onChange={setProvider}
                  options={[
                    { value: "openai_compat", label: "Cloud", icon: <Cloud size={13} aria-hidden />, title: "Groq: best quality" },
                    { value: "ollama", label: "Local", icon: <Laptop size={13} aria-hidden />, title: "Llama 3B on this computer: offline, slower and less accurate" },
                  ]}
                />
                {running ? (
                  <button
                    type="button"
                    onClick={() => abort.current?.abort()}
                    className="ml-auto flex items-center gap-1.5 rounded-lg border border-line-strong px-3 py-1.5 text-xs font-medium hover:bg-panel-2"
                  >
                    <Square size={12} aria-hidden /> Stop
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => void ask(question)}
                    disabled={question.trim().length < 3}
                    className="ml-auto flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-panel hover:bg-accent-hover disabled:opacity-40"
                  >
                    <Send size={13} aria-hidden /> Send
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {panel && (
        <aside aria-label="Answer details" className="hidden w-80 shrink-0 overflow-y-auto border-l border-line bg-bg p-4 lg:block">
          {panel}
        </aside>
      )}
    </div>
  );
}
