/** Pure helpers for displaying answers. Kept free of React so they are easy to test. */

/** Same styles the backend normalizes; applied while streaming, before the final answer arrives. */
export function normalizeCitations(text: string): string {
  return text
    .replace(/【\s*(\d+)\s*(?:†[^】]*)?】/g, "[$1]")
    .replace(/\(\s*sources?\s+(\d+(?:\s*,\s*\d+)*)\s*\)/gi, "[$1]")
    .replace(/\[\^(\d+)\]/g, "[$1]");
}

function expand(group: string): number[] {
  return group.split(",").flatMap((part) => {
    const [a, b] = part.split("-").map((x) => parseInt(x, 10));
    if (b === undefined) return [a];
    return b >= a && b - a < 20 ? Array.from({ length: b - a + 1 }, (_, i) => a + i) : [a, b];
  });
}

/**
 * Turn [1] and [2, 3] into Markdown links ([1](#cite-1)) so they render as clickable chips.
 * Code is left alone: `items[0]` in a kubectl command is not a citation.
 */
export function linkCitations(markdown: string): string {
  return markdown
    .split(/(```[\s\S]*?(?:```|$)|`[^`\n]*`)/g)
    .map((part, i) =>
      i % 2
        ? part
        : part.replace(/\[(\d+(?:\s*[,-]\s*\d+)*)\](?!\()/g, (_, group: string) =>
            expand(group.replace(/\s/g, ""))
              .map((n) => `[${n}](#cite-${n})`)
              .join(""),
          ),
    )
    .join("");
}

/** Parse complete Server-Sent Event frames from a buffer; returns events and the unfinished rest. */
export function parseSseBuffer<T = unknown>(buffer: string): { events: T[]; rest: string } {
  const frames = buffer.split("\n\n");
  const rest = frames.pop() ?? "";
  const events: T[] = [];
  for (const frame of frames) {
    for (const line of frame.split("\n")) {
      if (line.startsWith("data: ")) events.push(JSON.parse(line.slice(6)) as T);
    }
  }
  return { events, rest };
}

export function formatDuration(ms: number): string {
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export function formatDate(seconds: number): string {
  return new Date(seconds * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
