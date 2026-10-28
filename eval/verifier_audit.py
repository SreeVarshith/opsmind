"""Check the checker: how often does the agent's fact-checker agree with a human?

    python -m eval.verifier_audit sample            # 1. pick claims to label -> eval/labels/verifier_sample.jsonl
    streamlit run eval/label_app.py                 # 2. label them in the browser (verifier verdict hidden)
    python -m eval.verifier_audit score             # 3. agreement, confusion matrix, Cohen's kappa

The sample over-represents claims the verifier flagged, because those are rare but are exactly the
decisions that change what the user sees. Labelling is blind: the verifier's verdict is stored but not
shown, so it cannot bias the human.
"""
import json
import random
import sys
from collections import Counter
from pathlib import Path

from app.ingestion.pipeline import read_jsonl
from app.rag.chunking import chunk_documents
from eval.answer_eval import OUT_DIR

SAMPLE = Path("eval/labels/verifier_sample.jsonl")
VERDICTS = ["supported", "partial", "unsupported"]
SEED = 7


def full_source_texts() -> dict[tuple[str, str | None], str]:
    """(title, section) -> full chunk text, so the labeller sees whole sources, not 300-char snippets."""
    return {(c.title, c.section): c.text for c in chunk_documents(read_jsonl())}


def sample(n: int = 50) -> None:
    rows = [json.loads(line) for line in (OUT_DIR / "agent_groq.jsonl").open(encoding="utf-8")]
    texts = full_source_texts()
    claims = []
    for r in rows:
        sources = [{"number": s["number"], "title": s["title"], "section": s["section"],
                    "text": texts.get((s["title"], s["section"]), s["snippet"])} for s in r["sources"]]
        for i, c in enumerate(r.get("claims", [])):
            claims.append({"id": f"{r['ticket_id']}-{i}", "ticket_id": r["ticket_id"], "claim": c["text"],
                           "verifier_verdict": c["verdict"], "sources": sources, "human_label": None})
    rng = random.Random(SEED)
    flagged = [c for c in claims if c["verifier_verdict"] != "supported"]
    supported = [c for c in claims if c["verifier_verdict"] == "supported"]
    picked = rng.sample(flagged, min(len(flagged), n // 2))
    picked += rng.sample(supported, min(len(supported), n - len(picked)))
    rng.shuffle(picked)
    SAMPLE.parent.mkdir(parents=True, exist_ok=True)
    if SAMPLE.exists() and any(json.loads(line).get("human_label") for line in SAMPLE.open(encoding="utf-8")):
        sys.exit(f"{SAMPLE} already has human labels; refusing to overwrite them.")
    with SAMPLE.open("w", encoding="utf-8") as f:
        for c in picked:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"{len(claims)} claims in agent answers ({len(flagged)} flagged by the verifier).")
    print(f"Sampled {len(picked)} ({sum(c['verifier_verdict'] != 'supported' for c in picked)} flagged) -> {SAMPLE}")


def cohen_kappa(pairs: list[tuple[str, str]]) -> float:
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(ca[k] * cb[k] for k in VERDICTS) / (n * n)
    return (observed - expected) / (1 - expected) if expected < 1 else 1.0


def score() -> None:
    rows = [json.loads(line) for line in SAMPLE.open(encoding="utf-8")]
    done = [r for r in rows if r["human_label"] in VERDICTS]
    if not done:
        sys.exit("No human labels yet. Run: streamlit run eval/label_app.py")
    pairs = [(r["human_label"], r["verifier_verdict"]) for r in done]
    print(f"Labelled: {len(done)} of {len(rows)} claims\n")
    print(f"Exact agreement: {sum(h == v for h, v in pairs) / len(pairs):.0%}")
    print(f"Cohen's kappa:   {cohen_kappa(pairs):.2f}  (0 = chance, 0.4-0.6 moderate, >0.6 substantial)\n")
    print("Confusion matrix (rows = human, columns = verifier):")
    print(f"{'':>13}" + "".join(f"{v:>13}" for v in VERDICTS))
    for h in VERDICTS:
        print(f"{h:>13}" + "".join(f"{sum(1 for a, b in pairs if a == h and b == v):>13}" for v in VERDICTS))
    # The decision that matters to users: is this statement unsafe to trust ("unsupported")?
    tp = sum(1 for h, v in pairs if h == "unsupported" and v == "unsupported")
    flagged = sum(1 for _, v in pairs if v == "unsupported")
    actual = sum(1 for h, _ in pairs if h == "unsupported")
    print(f"\nFlagging unsupported claims: precision {tp / flagged:.0%} " if flagged else "\nVerifier flagged none ",
          end="")
    print(f"recall {tp / actual:.0%}" if actual else "(no human-unsupported claims)")


if __name__ == "__main__":
    {"sample": sample, "score": score}[sys.argv[1] if len(sys.argv) > 1 else "score"]()
