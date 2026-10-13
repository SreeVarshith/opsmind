"""Send the same question to every provider through the running API and compare.

Usage (with the API running):  python scripts/compare_llms.py "your question"
"""
import sys

import httpx

API = "http://localhost:8000/chat"
QUESTION = sys.argv[1] if len(sys.argv) > 1 else "What does OOMKilled mean in Kubernetes and how do I fix it? Answer in 4 bullet points."

for provider in ["ollama", "openai_compat"]:
    r = httpx.post(API, json={"message": QUESTION, "provider": provider, "fallback": False}, timeout=180)
    print("=" * 70)
    if r.status_code != 200:
        print(f"{provider}: FAILED {r.status_code} -> {r.json()['detail']}")
        continue
    body = r.json()
    print(f"{body['provider']} | {body['model']} | {body['latency_ms']} ms")
    print("-" * 70)
    print(body["text"])
