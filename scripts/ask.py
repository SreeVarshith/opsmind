"""Ask OpsMind a question from the terminal (the API must be running).

    python scripts/ask.py "Pods keep restarting with OOMKilled, what do I do?"
    python scripts/ask.py "etcd has no leader" --provider ollama
"""
import argparse
import sys

import httpx

ap = argparse.ArgumentParser()
ap.add_argument("question")
ap.add_argument("--provider", choices=["ollama", "openai_compat"], default=None)
ap.add_argument("--top-k", type=int, default=None)
ap.add_argument("--url", default="http://localhost:8000/ask")
args = ap.parse_args()

sys.stdout.reconfigure(encoding="utf-8")
r = httpx.post(args.url, json={"question": args.question, "provider": args.provider, "top_k": args.top_k},
               timeout=180)
if r.status_code != 200:
    sys.exit(f"Error {r.status_code}: {r.text}")
res = r.json()

print(res["answer"])
print("\n" + "-" * 70)
print("Sources cited:")
for c in res["citations"]:
    section = f" - {c['section']}" if c["section"] else ""
    print(f"  [{c['number']}] ({c['source_type']}) {c['title']}{section}\n      {c['source']}")
if res["invalid_citations"]:
    print(f"  WARNING: cited sources that do not exist: {res['invalid_citations']}")
t = res["timings"]
print(f"\nGrounded: {res['grounded']} | citation coverage {res['citation_coverage']:.0%} | "
      f"{res['provider']} / {res['model']} | "
      f"search {t['retrieval_ms']} ms + LLM {t['generation_ms']} ms = {t['total_ms']} ms")
