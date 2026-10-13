"""Retrieval benchmark: can we find the right runbook for a ticket?

    python -m eval.retrieval_eval --name dense_baseline

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

from app.ingestion.text import normalize_text
from app.rag.vector_store import get_vector_store

TICKETS = Path("data/raw/tickets/tickets.jsonl")
RESULTS = Path("eval/results")
KS = (1, 3, 5, 10)
CHUNKS_TO_FETCH = 40  # enough chunks to cover 10+ distinct runbooks


def load_eval_tickets() -> tuple[list[dict], int]:
    rows = [json.loads(line) for line in TICKETS.read_text(encoding="utf-8").splitlines() if line.strip()]
    # Drop tickets that leak the alert name: they would make retrieval artificially easy.
    clean = [r for r in rows if r["related_runbook"].lower() not in (r["title"] + r["description"]).lower()]
    return clean, len(rows) - len(clean)


def rank_of(target: str, alerts_in_order: list[str]) -> int | None:
    return alerts_in_order.index(target) + 1 if target in alerts_in_order else None


def main(name: str) -> None:
    tickets, dropped = load_eval_tickets()
    store = get_vector_store()
    ranks, latencies, misses = [], [], []

    for t in tickets:
        query = normalize_text(f"{t['title']}\n{t['description']}")
        start = time.perf_counter()
        hits = store.search(query, top_k=CHUNKS_TO_FETCH, source_types=["runbook"])
        latencies.append((time.perf_counter() - start) * 1000)

        alerts = list(dict.fromkeys(h.metadata["alert"] for h in hits))  # dedupe, keep order
        rank = rank_of(t["related_runbook"], alerts)
        ranks.append(rank)
        if rank != 1:
            misses.append({"ticket": t["ticket_id"], "expected": t["related_runbook"],
                           "rank": rank, "got": alerts[:3]})
    store.close()

    n = len(ranks)
    metrics = {f"recall@{k}": sum(1 for r in ranks if r and r <= k) / n for k in KS}
    metrics["mrr"] = sum(1 / r for r in ranks if r) / n
    metrics["p50_latency_ms"] = statistics.median(latencies)

    print(f"\n{name}: {n} tickets ({dropped} leaky tickets excluded)")
    for key, value in metrics.items():
        print(f"  {key:<16}{value:.3f}" if "latency" not in key else f"  {key:<16}{value:.0f} ms")

    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{name}.json"
    out.write_text(json.dumps({"name": name, "date": datetime.now().isoformat(timespec="seconds"),
                               "n_tickets": n, "metrics": metrics, "misses": misses}, indent=2))
    print(f"Saved to {out}  (misses listed there for error analysis)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="dense_baseline", help="label for this experiment")
    main(ap.parse_args().name)
