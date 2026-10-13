"""Retrieval benchmark: can we find the right runbook for a ticket?

    python -m eval.retrieval_eval --ablation               # all configurations + markdown table
    python -m eval.retrieval_eval --mode hybrid --rerank   # one configuration

Each synthetic ticket was written from one runbook (`related_runbook`). We use the ticket's
title + description as the query, search only runbooks, and check at which rank the source
runbook appears. Chunks are collapsed to their runbook first (one runbook = many sections).

Metrics:
  Recall@k  share of tickets whose runbook is in the top k results (higher is better)
  MRR       mean of 1/rank; rewards putting the right runbook first (1.0 = always rank 1)
"""
import argparse
import json
import statistics
import time
from datetime import datetime
from pathlib import Path

from app.rag.reranker import get_reranker
from app.rag.retriever import Retriever
from app.rag.vector_store import get_vector_store

TICKETS = Path("data/raw/tickets/tickets.jsonl")
RESULTS = Path("eval/results")
KS = (1, 3, 5, 10)
CHUNKS_TO_FETCH = 40      # enough chunks to cover 10+ distinct runbooks
RERANK_CANDIDATES = 50

ABLATION = [  # (name, mode, rerank)
    ("dense", "dense", False),
    ("sparse_bm25", "sparse", False),
    ("hybrid_rrf", "hybrid", False),
    ("dense+rerank", "dense", True),
    ("hybrid_rrf+rerank", "hybrid", True),
]


def load_eval_tickets() -> tuple[list[dict], int]:
    rows = [json.loads(line) for line in TICKETS.read_text(encoding="utf-8").splitlines() if line.strip()]
    # Drop tickets that leak the alert name: they would make retrieval artificially easy.
    clean = [r for r in rows if r["related_runbook"].lower() not in (r["title"] + r["description"]).lower()]
    return clean, len(rows) - len(clean)


def evaluate(retriever: Retriever, tickets: list[dict], mode: str, rerank: bool) -> tuple[dict, list]:
    ranks, latencies, misses = [], [], []
    for t in tickets:
        start = time.perf_counter()
        hits = retriever.retrieve(f"{t['title']}\n{t['description']}", top_k=CHUNKS_TO_FETCH,
                                  source_types=["runbook"], mode=mode, rerank=rerank)
        latencies.append((time.perf_counter() - start) * 1000)

        alerts = list(dict.fromkeys(h.metadata["alert"] for h in hits))  # dedupe, keep order
        rank = alerts.index(t["related_runbook"]) + 1 if t["related_runbook"] in alerts else None
        ranks.append(rank)
        if rank != 1:
            misses.append({"ticket": t["ticket_id"], "expected": t["related_runbook"],
                           "rank": rank, "got": alerts[:3]})

    n = len(ranks)
    metrics = {f"recall@{k}": sum(1 for r in ranks if r and r <= k) / n for k in KS}
    metrics["mrr"] = sum(1 / r for r in ranks if r) / n
    metrics["p50_latency_ms"] = statistics.median(latencies)
    return metrics, misses


def save(name: str, n: int, metrics: dict, misses: list) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"{name}.json").write_text(json.dumps(
        {"name": name, "date": datetime.now().isoformat(timespec="seconds"),
         "n_tickets": n, "metrics": metrics, "misses": misses}, indent=2))


def table(rows: list[tuple[str, dict]]) -> str:
    head = "| Method | R@1 | R@3 | R@5 | R@10 | MRR | p50 latency |\n|---|---|---|---|---|---|---|"
    lines = [f"| {name} | " + " | ".join(f"{m[f'recall@{k}']:.3f}" for k in KS)
             + f" | {m['mrr']:.3f} | {m['p50_latency_ms']:.0f} ms |" for name, m in rows]
    return "\n".join([head, *lines])


def main(configs: list[tuple[str, str, bool]]) -> None:
    tickets, dropped = load_eval_tickets()
    store = get_vector_store()
    reranker = get_reranker() if any(r for _, _, r in configs) else None
    retriever = Retriever(store, reranker, rerank_candidates=RERANK_CANDIDATES)
    print(f"Evaluating on {len(tickets)} tickets ({dropped} leaky tickets excluded)")

    rows = []
    for name, mode, rerank in configs:
        metrics, misses = evaluate(retriever, tickets, mode, rerank)
        save(name, len(tickets), metrics, misses)
        rows.append((name, metrics))
        print(f"  {name:<20} R@1 {metrics['recall@1']:.3f}  R@5 {metrics['recall@5']:.3f}  "
              f"MRR {metrics['mrr']:.3f}  {metrics['p50_latency_ms']:.0f} ms")
    store.close()

    print("\n" + table(rows))
    print(f"\nPer-run details (including misses) saved in {RESULTS}/")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ablation", action="store_true", help="run every configuration")
    ap.add_argument("--mode", choices=["dense", "sparse", "hybrid"], default="hybrid")
    ap.add_argument("--rerank", action="store_true")
    ap.add_argument("--name", default=None, help="label for a single run")
    args = ap.parse_args()
    if args.ablation:
        main(ABLATION)
    else:
        main([(args.name or f"{args.mode}{'+rerank' if args.rerank else ''}", args.mode, args.rerank)])
