import { describe, expect, it } from "vitest";
import { linkCitations, normalizeCitations, parseSseBuffer } from "./answer";

describe("linkCitations", () => {
  it("links single, grouped and ranged citations", () => {
    expect(linkCitations("A [1] b [2, 3] c [4-5]")).toBe(
      "A [1](#cite-1) b [2](#cite-2)[3](#cite-3) c [4](#cite-4)[5](#cite-5)",
    );
  });

  it("leaves code alone", () => {
    const text = "Run `kubectl get -o jsonpath='{.items[0]}'` [1]\n```\nx = arr[7]\n```\nDone [2]";
    expect(linkCitations(text)).toBe(
      "Run `kubectl get -o jsonpath='{.items[0]}'` [1](#cite-1)\n```\nx = arr[7]\n```\nDone [2](#cite-2)",
    );
  });

  it("does not touch an unfinished code block while streaming", () => {
    expect(linkCitations("a [1]\n```\nb[2]")).toBe("a [1](#cite-1)\n```\nb[2]");
  });

  it("does not rewrite real links", () => {
    expect(linkCitations("[1](https://example.com)")).toBe("[1](https://example.com)");
  });
});

describe("normalizeCitations", () => {
  it("rewrites other citation styles", () => {
    expect(normalizeCitations("x【1†L1-L4】y【2】z[^3]")).toBe("x[1]y[2]z[3]");
    expect(normalizeCitations("a (source 2) b (Sources 1, 3)")).toBe("a [2] b [1, 3]");
  });
});

describe("parseSseBuffer", () => {
  it("keeps an unfinished frame for the next chunk", () => {
    const { events, rest } = parseSseBuffer('data: {"a":1}\n\ndata: {"b":2}\n\ndata: {"c"');
    expect(events).toEqual([{ a: 1 }, { b: 2 }]);
    expect(rest).toBe('data: {"c"');
  });
});
