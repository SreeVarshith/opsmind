"""Generate realistic synthetic IT tickets, each grounded in one real runbook.

    python -m scripts.generate_tickets              # 2 tickets per runbook
    python -m scripts.generate_tickets --limit 5    # quick test on 5 runbooks

Why synthetic? Real company tickets are private. Each generated ticket stores
`related_runbook` (the runbook it was written from), which gives us a free labelled
dataset for evaluation later: "given this ticket, did retrieval find the right runbook?"

The script is resumable: runbooks that already have tickets are skipped, so if the free
API rate limit stops it halfway, just run it again.
"""
import argparse
import asyncio
import json
import random
import re
from pathlib import Path

from app.core.config import get_settings
from app.ingestion.runbooks import load_runbooks
from app.llm.base import LLMError, Message
from app.llm.openai_compat import OpenAICompatProvider

OUT = Path("data/raw/tickets/tickets.jsonl")
SERVICES = ["checkout-api", "payments-service", "user-auth", "search-api", "inventory-db",
            "notifications-worker", "reporting-etl", "web-frontend", "order-service", "monitoring-stack"]

PROMPT = """You write realistic IT incident tickets for a company's internal helpdesk.

Here is a runbook for the alert "{alert}" (component: {component}):
---
{runbook}
---

Write {n} DIFFERENT tickets that an engineer would file when this problem happened in
production at a company. Use the service names {services}. Rules:
- "title": short, how a stressed engineer would write it (do NOT copy the alert name)
- "description": 2-4 sentences of symptoms in the engineer's own words. Include one realistic
  error message, kubectl output or log line. Do not name the runbook or the alert.
- "root_cause": the actual cause that was found (one sentence, specific)
- "resolution": the concrete steps that fixed it (2-3 sentences, mention commands if relevant)
- "priority": one of P1, P2, P3, P4
- "service": one of the service names above

Return ONLY a JSON object: {{"tickets": [{{"title": ..., "description": ..., "root_cause": ...,
"resolution": ..., "priority": ..., "service": ...}}]}}"""


def parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    return json.loads(text[text.find("{"): text.rfind("}") + 1])


def already_done() -> tuple[set[str], int]:
    if not OUT.exists():
        return set(), 0
    rows = [json.loads(line) for line in OUT.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {r["related_runbook"] for r in rows}, len(rows)


async def generate(limit: int | None, per_runbook: int, model: str, delay: float) -> None:
    s = get_settings()
    # Writing tickets needs little reasoning; "low" saves most of the free tokens-per-minute budget.
    llm = OpenAICompatProvider(s.api_base_url, s.api_key, model, extra_params={"reasoning_effort": "low"})
    runbooks = load_runbooks(Path("data/raw/runbooks"))
    done, next_num = already_done()
    todo = [r for r in runbooks if r.metadata["alert"] not in done][:limit]
    print(f"{len(done)} runbooks already have tickets, generating for {len(todo)} more with {model}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    for i, rb in enumerate(todo, 1):
        prompt = PROMPT.format(alert=rb.metadata["alert"], component=rb.metadata["component"],
                               runbook=rb.text[:1500], n=per_runbook,
                               services=", ".join(random.sample(SERVICES, 3)))
        for attempt in range(5):
            try:
                res = await llm.generate([Message(role="user", content=prompt)], temperature=0.9, max_tokens=1500)
                tickets = parse_json(res.text)["tickets"]
                break
            except LLMError as e:
                wait = 30 if "429" in str(e) else 5
                print(f"  {rb.metadata['alert']}: {str(e)[:90]}... retrying in {wait}s", flush=True)
                await asyncio.sleep(wait)
            except (ValueError, KeyError) as e:
                print(f"  {rb.metadata['alert']}: bad JSON ({e}), retrying", flush=True)
                await asyncio.sleep(delay)
        else:
            print(f"  skipped {rb.metadata['alert']} after 5 attempts")
            continue

        with OUT.open("a", encoding="utf-8") as f:
            for t in tickets[:per_runbook]:
                next_num += 1
                t["ticket_id"] = f"INC-{next_num:04d}"
                t["related_runbook"] = rb.metadata["alert"]
                f.write(json.dumps(t, ensure_ascii=False) + "\n")
        print(f"[{i}/{len(todo)}] {rb.metadata['alert']}: {len(tickets[:per_runbook])} tickets ({res.latency_ms} ms)",
              flush=True)
        await asyncio.sleep(delay)  # stay under the free tier's tokens-per-minute limit


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="only process this many runbooks")
    ap.add_argument("--per-runbook", type=int, default=2)
    ap.add_argument("--model", default="openai/gpt-oss-20b",
                    help="smaller model by default to save free-tier quota for the main app")
    ap.add_argument("--delay", type=float, default=10, help="seconds to wait between requests")
    args = ap.parse_args()
    asyncio.run(generate(args.limit, args.per_runbook, args.model, args.delay))
