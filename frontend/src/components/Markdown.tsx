import { Check, Copy } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { linkCitations } from "../lib/answer";

function CodeBlock({ children }: { children?: ReactNode }) {
  const ref = useRef<HTMLPreElement>(null);
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(ref.current?.innerText ?? "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked: the text is still selectable */
    }
  };
  return (
    <div className="group relative mb-3">
      <pre ref={ref} className="overflow-x-auto rounded-lg border border-line bg-panel-2 p-3 pr-10">
        {children}
      </pre>
      <button
        type="button"
        onClick={copy}
        aria-label={copied ? "Copied" : "Copy command"}
        title={copied ? "Copied" : "Copy"}
        className="absolute top-1.5 right-1.5 rounded-md bg-panel-2 p-1.5 text-ink-3 hover:bg-panel hover:text-ink"
      >
        {copied ? <Check size={14} aria-hidden /> : <Copy size={14} aria-hidden />}
      </button>
    </div>
  );
}

export function Markdown(props: { text: string; onCite?: (n: number) => void; activeCite?: number | null }) {
  const { text, onCite, activeCite } = props;
  const components: Components = {
    pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
    a: ({ href, children }) => {
      const cite = href?.match(/^#cite-(\d+)$/);
      if (cite) {
        const n = Number(cite[1]);
        return (
          <button
            type="button"
            onClick={() => onCite?.(n)}
            aria-label={`Show source ${n}`}
            className={`mx-[1px] inline-flex min-w-[18px] items-center justify-center rounded px-1 align-[1px] text-[11px] leading-[16px] font-semibold transition-colors ${
              activeCite === n
                ? "bg-accent text-panel"
                : "bg-accent-soft text-accent-ink hover:bg-accent hover:text-panel"
            }`}
          >
            {n}
          </button>
        );
      }
      return (
        <a href={href} target="_blank" rel="noopener noreferrer">
          {children}
        </a>
      );
    },
  };
  return (
    <div className="answer">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {linkCitations(text)}
      </ReactMarkdown>
    </div>
  );
}
