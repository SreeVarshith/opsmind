"""Summarize the answer evaluation into tables (Markdown + JSON).

    python -m eval.answer_report

Accuracy uses the judge score: 4 or 5 = correct. Every rate comes with a 95% bootstrap confidence
interval, because with ~40 questions a single number hides a lot of uncertainty.
"""
import json
import random
import statistics
from pathlib import Path

from eval.answer_eval import CONFIGS, OUT_DIR

REPORT_MD = Path("eval/results/answer_eval_report.md")
REPORT_JSON = Path("eval/results/answer_eval_summary.json")
LABELS = {"fast_groq": "Fast · gpt-oss-120b", "agent_groq": "Agent · gpt-oss-120b (+20b checks)",
          "fast_local": "Fast · Llama 3.2 3B (local)", "fast_groq_ranked": "Fast · gpt-oss-120b, ranked causes"}


def load(name: str) -> list[dict]:
    path = OUT_DIR / f"{name}.jsonl"
    return [json.loads(line) for line in path.open(encoding="utf-8")] if path.exists() else []


def bootstrap_ci(values: list[float], n_boot: int = 5000, seed: int = 0) -> tuple[float, float]:
    if not values:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    means = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(n_boot))
    return means[int(0.025 * n_boot)], means[int(0.975 * n_boot) - 1]


def pct(values: list[float]) -> str:
    if not values:
        return "n/a"
    lo, hi = bootstrap_ci(values)
    return f"{statistics.mean(values):.0%} ({lo:.0%}-{hi:.0%})"


def summarize(rows: list[dict]) -> dict:
    scored = [r for r in rows if r["judge_score"] is not None]
    correct = [1.0 if r["judge_score"] >= 4 else 0.0 for r in scored]
    lat = sorted(r["total_ms"] for r in rows)
    support = [r["support_rate"] for r in rows if r.get("support_rate") is not None]
    return {
        "n": len(rows),
        "correct": correct,
        "mean_score": statistics.mean(r["judge_score"] for r in scored) if scored else None,
        "runbook_retrieved": [float(r["runbook_retrieved"]) for r in rows],
        "runbook_cited": [float(r["runbook_cited"]) for r in rows],
        "citation_coverage": statistics.mean(r["citation_coverage"] for r in rows) if rows else None,
        "invalid_citations": sum(r["invalid_citations"] for r in rows),
        "support_rate": statistics.mean(support) if support else None,
        "revised": sum(1 for r in rows if r.get("revisions")),
        "p50_s": lat[len(lat) // 2] / 1000 if lat else None,
        "p95_s": lat[min(len(lat) - 1, int(0.95 * len(lat)))] / 1000 if lat else None,
        "score_dist": {s: sum(1 for r in scored if r["judge_score"] == s) for s in range(1, 6)},
    }


def paired(a_rows: list[dict], b_rows: list[dict]) -> dict:
    a = {r["ticket_id"]: r["judge_score"] for r in a_rows if r["judge_score"] is not None}
    b = {r["ticket_id"]: r["judge_score"] for r in b_rows if r["judge_score"] is not None}
    common = sorted(set(a) & set(b))
    return {"n": len(common), "b_better": sum(b[t] > a[t] for t in common),
            "same": sum(b[t] == a[t] for t in common), "a_better": sum(b[t] < a[t] for t in common)}


def main() -> None:
    data = {name: load(name) for name in CONFIGS}
    stats = {name: summarize(rows) for name, rows in data.items() if rows}

    lines = ["# Answer evaluation", "",
             f"Questions: {max((s['n'] for s in stats.values()), default=0)} synthetic tickets (seed 42), "
             "own ticket hidden from search. Judge: qwen3.8-27b, score 4-5 = correct. "
             "Ranges are 95% bootstrap confidence intervals.", "",
             "| Configuration | n | Correct | Mean score | Runbook found | Runbook cited | Cited sentences | "
             "Verified (agent) | Median time | p95 time |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for name, s in stats.items():
        verified = f"{s['support_rate']:.0%}" if s["support_rate"] is not None else "-"
        lines.append(
            f"| {LABELS[name]} | {s['n']} | {pct(s['correct'])} | {s['mean_score']:.2f} | "
            f"{pct(s['runbook_retrieved'])} | {pct(s['runbook_cited'])} | {s['citation_coverage']:.0%} | "
            f"{verified} | {s['p50_s']:.1f} s | {s['p95_s']:.1f} s |")

    lines += ["", "Score distribution (1 = wrong ... 5 = fully correct):", "",
              "| Configuration | 1 | 2 | 3 | 4 | 5 |", "|---|---|---|---|---|---|"]
    for name, s in stats.items():
        lines.append(f"| {LABELS[name]} | " + " | ".join(str(s["score_dist"][k]) for k in range(1, 6)) + " |")

    comparisons = []
    for a, b in (("fast_groq", "agent_groq"), ("fast_local", "fast_groq"), ("fast_groq", "fast_groq_ranked")):
        if data.get(a) and data.get(b):
            p = paired(data[a], data[b])
            comparisons.append((a, b, p))
    if comparisons:
        lines += ["", "Paired comparison on the same questions (judge score):", "",
                  "| A | B | Questions | B better | Same | A better |", "|---|---|---|---|---|---|"]
        for a, b, p in comparisons:
            lines.append(f"| {LABELS[a]} | {LABELS[b]} | {p['n']} | {p['b_better']} | {p['same']} | {p['a_better']} |")

    agent = stats.get("agent_groq")
    if agent:
        lines += ["", f"Agent revisions: {agent['revised']} of {agent['n']} answers were revised once."]
    invalid = {name: s["invalid_citations"] for name, s in stats.items()}
    lines += [f"Invalid (hallucinated) citation numbers: {invalid}"]

    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    REPORT_JSON.write_text(json.dumps({n: {k: v for k, v in s.items() if not isinstance(v, list)} | {
        "correct_rate": statistics.mean(s["correct"]) if s["correct"] else None,
        "correct_ci95": bootstrap_ci(s["correct"]),
        "runbook_retrieved_rate": statistics.mean(s["runbook_retrieved"]),
        "runbook_cited_rate": statistics.mean(s["runbook_cited"])} for n, s in stats.items()}
        | {"paired": {f"{a}_vs_{b}": p for a, b, p in comparisons}}, indent=2), encoding="utf-8")
    print("\n".join(lines))
    print(f"\nSaved {REPORT_MD} and {REPORT_JSON}")


if __name__ == "__main__":
    main()
