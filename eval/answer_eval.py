"""End-to-end answer evaluation: is the final answer actually right?

    python -m eval.answer_eval --config fast_groq            # one configuration (resumable)
    python -m eval.answer_eval --config all --n 40           # all configurations
    python -m eval.answer_report                             # summary tables

For each sampled ticket, the question is the ticket's title + description, and the reference is
its real root cause, resolution and source runbook. Two safeguards keep the numbers honest:

  1. Leakage: the ticket being asked about is hidden from search, otherwise OpsMind would simply
     retrieve the answer. Its sibling ticket (written from the same runbook) stays: that is a
     legitimate "similar past incident".
  2. Self-preference: the judge is Qwen (a different model family from the gpt-oss writers).

Every result is appended to eval/results/answers/<config>.jsonl right away, so a rate limit or a
crash loses nothing: rerunning skips questions that are already done.
"""
import argparse
import asyncio
import json
import random
import time
from pathlib import Path

from app.agents.incident_agent import IncidentAgent
from app.core.config import get_settings
from app.llm.base import LLMError, Message
from app.llm.json_utils import parse_json_object
from app.llm.openai_compat import OpenAICompatProvider
from app.llm.router import LLMRouter, build_providers
from app.rag.answer import Answerer, split_claims
from app.rag.retriever import Retriever, get_retriever
from app.rag.vector_store import SearchHit
from eval.retrieval_eval import load_eval_tickets

OUT_DIR = Path("eval/results/answers")
JUDGE_MODEL = "qwen/qwen3.8-27b"
JUDGE_SETTING = "qwen3.8-27b/no-reasoning/v1"  # stored with every score; rejudge if it changes
SEED = 42

CONFIGS = {  # name: (mode, provider)
    "fast_groq": ("fast", "openai_compat"),
    "agent_groq": ("agent", "openai_compat"),
    "fast_local": ("fast", "ollama"),
    "fast_groq_ranked": ("fast", "openai_compat"),   # same setup, after the prompt moved to ranked causes
}

JUDGE_PROMPT = """You grade answers from an IT incident-response assistant.
You get the engineer's question, the REFERENCE (what the real root cause and fix turned out to be),
and the assistant's ANSWER. Score how well the answer would lead the engineer to the right root cause
and fix:
5 = identifies the reference root cause and gives the reference fix (or an equivalent one)
4 = right root cause and a fix that would work, minor details missing
3 = partly right: plausible direction, but misses the key cause or the key fix step
2 = mostly generic advice that would not solve this specific problem
1 = wrong, misleading or harmful
Do not reward length. Extra correct detail is fine; wrong commands or wrong causes lower the score.
Reply with ONLY a JSON object: {"score": <1-5>, "reason": "<one sentence>"}"""


class ExcludingRetriever(Retriever):
    """Wraps the real retriever and hides specific documents (the ticket under test)."""

    def __init__(self, base: Retriever):
        super().__init__(base.store, base.reranker, base.mode, base.rerank, base.rerank_candidates)
        self.exclude: set[str] = set()

    def retrieve(self, query, top_k=5, *args, **kwargs) -> list[SearchHit]:
        hits = super().retrieve(query, top_k + len(self.exclude), *args, **kwargs)
        return [h for h in hits if h.doc_id not in self.exclude][:top_k]


def sample_tickets(n: int) -> list[dict]:
    tickets, _ = load_eval_tickets()
    return sorted(random.Random(SEED).sample(tickets, min(n, len(tickets))), key=lambda t: t["ticket_id"])


def ticket_doc_id(ticket_id: str) -> str:
    from app.ingestion.schema import make_id
    return make_id("ticket", ticket_id)


async def with_retry(make_call, what: str, attempts: int = 6):
    for i in range(attempts):
        try:
            return await make_call()
        except LLMError as e:
            wait = 30 if "429" in str(e) else 10
            print(f"    {what}: {str(e)[:80]}... waiting {wait}s ({i + 1}/{attempts})", flush=True)
            await asyncio.sleep(wait)
    raise RuntimeError(f"{what} failed {attempts} times")


def make_judge() -> OpenAICompatProvider:
    """Own connection for the judge: Qwen with thinking off. Groq's free tier allows Qwen only ~1,000
    output tokens per minute, and hidden reasoning tripled the tokens per judgment (138 vs 43)."""
    s = get_settings()
    return OpenAICompatProvider(s.api_base_url, s.api_key, JUDGE_MODEL, extra_params={"reasoning_effort": "none"})


async def judge(llm: OpenAICompatProvider, ticket: dict, answer: str) -> dict:
    reference = (f"Root cause: {ticket['root_cause']}\nResolution: {ticket['resolution']}\n"
                 f"Relevant runbook: {ticket['related_runbook']}")
    user = f"QUESTION:\n{ticket['title']}\n{ticket['description']}\n\nREFERENCE:\n{reference}\n\nANSWER:\n{answer}"

    async def call():
        res = await llm.generate([Message(role="system", content=JUDGE_PROMPT), Message(role="user", content=user)],
                                 temperature=0.0, max_tokens=400)
        out = parse_json_object(res.text)
        return {"score": int(out["score"]), "reason": str(out.get("reason", ""))[:300]}

    for _ in range(3):  # also retry when the judge returns broken JSON
        try:
            return await with_retry(call, "judge")
        except (ValueError, KeyError, TypeError):
            continue
    return {"score": None, "reason": "judge failed"}


async def run_config(name: str, n: int, delay: float, limit: int | None = None) -> None:
    mode, provider = CONFIGS[name]
    s = get_settings()
    llm = LLMRouter(build_providers(s), s.llm_provider)
    judge_llm = make_judge()
    retriever = ExcludingRetriever(get_retriever())
    answerer = Answerer(retriever, llm, s.answer_top_k, s.answer_max_tokens, s.answer_quotas)
    agent = IncidentAgent(answerer, llm, s.agent_fast_model, s.agent_revise_below, s.agent_max_revisions,
                          s.answer_max_tokens)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{name}.jsonl"
    done = {json.loads(line)["ticket_id"] for line in out.open(encoding="utf-8")} if out.exists() else set()
    todo = [t for t in sample_tickets(n) if t["ticket_id"] not in done][:limit]
    print(f"[{name}] {len(done)} done, {len(todo)} to go", flush=True)

    for i, t in enumerate(todo, 1):
        retriever.exclude = {ticket_doc_id(t["ticket_id"])}
        question = f"{t['title']}\n{t['description']}"
        start = time.perf_counter()
        if mode == "fast":
            r = await with_retry(lambda: answerer.ask(question, provider=provider), "answer")
            extra = {"support_rate": None, "confidence": None, "revisions": 0}
            model = r.model
        else:
            r = await with_retry(lambda: agent.run(question, provider=provider), "agent")
            extra = {"support_rate": r.support_rate, "confidence": r.confidence, "revisions": r.revisions,
                     "claims": [c.model_dump() for c in r.claims]}
            model = next((m.split(": ", 1)[1] for m in reversed(r.models_used)
                          if m.startswith(("generate", "revise"))), None)
        total_ms = int((time.perf_counter() - start) * 1000)

        retrieved = [src.title for src in r.sources]
        cited = [c.title for c in r.citations]
        expected = t["related_runbook"]
        verdict = await judge(judge_llm, t, r.answer)
        row = {
            "ticket_id": t["ticket_id"], "config": name, "model": model, "expected_runbook": expected,
            "runbook_retrieved": any(f"[{expected}]" in x or x.startswith(expected) for x in retrieved),
            "runbook_cited": any(f"[{expected}]" in x or x.startswith(expected) for x in cited),
            "judge_score": verdict["score"], "judge_reason": verdict["reason"], "judge_setting": JUDGE_SETTING,
            "citation_coverage": r.citation_coverage, "n_claims": len(split_claims(r.answer)),
            "invalid_citations": len(r.invalid_citations), "total_ms": total_ms, "answer": r.answer,
            "sources": [x.model_dump() for x in r.sources], **extra,
        }
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"  [{name} {i}/{len(todo)}] {t['ticket_id']} score={verdict['score']} "
              f"runbook={'cited' if row['runbook_cited'] else 'found' if row['runbook_retrieved'] else 'missed'} "
              f"{total_ms / 1000:.1f}s", flush=True)
        await asyncio.sleep(delay)


async def rejudge(name: str, delay: float = 3) -> None:
    """Re-score saved answers whose judge setting differs from the current one (same answers, new judge)."""
    path = OUT_DIR / f"{name}.jsonl"
    if not path.exists():
        return
    rows = [json.loads(line) for line in path.open(encoding="utf-8")]
    tickets = {t["ticket_id"]: t for t in load_eval_tickets()[0]}
    judge_llm = make_judge()
    stale = [r for r in rows if r.get("judge_setting") != JUDGE_SETTING]
    print(f"[{name}] rejudging {len(stale)} of {len(rows)}", flush=True)
    for r in stale:
        verdict = await judge(judge_llm, tickets[r["ticket_id"]], r["answer"])
        r.update(judge_score=verdict["score"], judge_reason=verdict["reason"], judge_setting=JUDGE_SETTING)
        path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")
        await asyncio.sleep(delay)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", choices=[*CONFIGS, "all"], default="all")
    ap.add_argument("--n", type=int, default=40, help="number of tickets")
    ap.add_argument("--rejudge", action="store_true", help="re-score saved answers with the current judge")
    ap.add_argument("--limit", type=int, default=None, help="only run this many new questions")
    ap.add_argument("--delay", type=float, default=8, help="seconds between questions (free-tier pacing)")
    args = ap.parse_args()
    for name in (CONFIGS if args.config == "all" else [args.config]):
        if args.rejudge:
            asyncio.run(rejudge(name))
        else:
            asyncio.run(run_config(name, args.n, args.delay, args.limit))
