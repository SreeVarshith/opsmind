"""The incident agent: a LangGraph workflow that answers carefully instead of in one shot.

    analyze -> retrieve -> generate -> verify --(enough claims supported?)--> finalize
                              ^                   |
                              +---- revise <------+  (at most `max_revisions` times)

- analyze:  understand the problem (category, summary) and write a better search query
- retrieve: balanced sources for the original question + the improved query
- generate: draft an answer with [n] citations (same prompt as /ask)
- verify:   a second LLM checks every sentence against the sources: supported / partial / unsupported
- revise:   if too much is unsupported, send the draft back with the list of problems
- finalize: attach a confidence level and flag any statement that is still not supported
"""
import operator
import time
from functools import lru_cache
from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from app.core.config import get_settings
from app.llm.base import LLMError, Message
from app.llm.json_utils import parse_json_object
from app.llm.router import LLMRouter, get_router
from app.rag.answer import (
    NO_SOURCES_ANSWER,
    Answerer,
    Citation,
    build_messages,
    check_citations,
    citation_coverage,
    format_sources,
    get_answerer,
    normalize_citations,
    split_claims,
    to_citation,
)
from app.rag.vector_store import SearchHit

CATEGORIES = ["kubernetes-workload", "kubernetes-control-plane", "etcd", "node", "prometheus", "alertmanager",
              "networking", "storage", "application", "other"]

ANALYZE_PROMPT = f"""You triage IT incidents. Read the engineer's message and reply with ONLY a JSON object:
{{"category": one of {CATEGORIES},
 "summary": "one sentence: what is failing and the key symptom",
 "search_query": "a short search query with the technical terms an on-call runbook would use
                  (component names, alert-style names, error strings). Max 25 words."}}"""

VERIFY_PROMPT = """You are a strict fact-checker for an incident-response assistant.
For each numbered claim, decide whether the numbered sources support it:
- "supported": a source states this (or it follows directly from a source)
- "partial": a source supports part of it, but some detail (a number, command or cause) is not in any source
- "unsupported": no source says this, or a source contradicts it
Judge against the sources only, not your own knowledge. A claim does not need its own citation to be
supported; check all sources. Reply with ONLY a JSON object:
{"results": [{"id": 1, "verdict": "supported", "sources": [2]}, ...]}  (one entry per claim, same ids)"""

VERDICT_SCORE = {"supported": 1.0, "partial": 0.5, "unsupported": 0.0}


class ClaimCheck(BaseModel):
    text: str
    verdict: Literal["supported", "partial", "unsupported"]
    sources: list[int]


class Step(BaseModel):
    step: str
    ms: int
    detail: str


class AgentState(TypedDict, total=False):
    question: str
    service: str | None
    provider: str | None
    access: list[str] | None
    analysis: dict[str, Any]
    search_query: str
    hits: list[SearchHit]
    draft: str
    feedback: str | None
    claims: list[ClaimCheck]
    support_rate: float | None
    revisions: int
    models_used: Annotated[list[str], operator.add]
    trace: Annotated[list[Step], operator.add]
    final_answer: str
    confidence: str


class AgentResult(BaseModel):
    question: str
    answer: str
    confidence: Literal["high", "medium", "low", "unverified", "none"]
    support_rate: float | None          # weighted share of claims the verifier found supported
    citation_coverage: float
    claims: list[ClaimCheck]
    analysis: dict[str, Any]
    search_query: str
    citations: list[Citation]
    sources: list[Citation]
    invalid_citations: list[int]
    revisions: int
    models_used: list[str]
    trace: list[Step]
    total_ms: int


def _ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


class IncidentAgent:
    def __init__(self, answerer: Answerer, llm: LLMRouter, fast_model: str | None = None,
                 revise_below: float = 0.7, max_revisions: int = 1, max_tokens: int = 1200):
        self.answerer = answerer
        self.llm = llm
        self.fast = {"openai_compat": fast_model} if fast_model else None
        self.revise_below = revise_below
        self.max_revisions = max_revisions
        self.max_tokens = max_tokens
        self.graph = self._build()

    # ---------- nodes ----------
    async def analyze(self, state: AgentState) -> dict:
        start = time.perf_counter()
        try:
            res = await self.llm.generate(
                [Message(role="system", content=ANALYZE_PROMPT), Message(role="user", content=state["question"])],
                provider=state.get("provider"), models=self.fast, temperature=0.0, max_tokens=600)
            analysis = parse_json_object(res.text)
            query = str(analysis.get("search_query") or "").strip()
            used = [f"analyze: {res.model}"]
            detail = f"{analysis.get('category')}: {analysis.get('summary')}"
        except (LLMError, ValueError) as e:  # triage is a helper: on failure, search with the question itself
            analysis, query, used, detail = {}, "", [], f"skipped ({str(e)[:80]})"
        return {"analysis": analysis, "search_query": query, "models_used": used,
                "trace": [Step(step="analyze", ms=_ms(start), detail=detail)]}

    async def retrieve(self, state: AgentState) -> dict:
        start = time.perf_counter()
        # Keep the original wording (exact error strings help BM25) and add the triage query.
        query = state["question"] + ("\n" + state["search_query"] if state.get("search_query") else "")
        hits = self.answerer.gather_sources(query, None, None, state.get("service"), state.get("access"))
        titles = ", ".join(h.metadata.get("alert") or h.title[:30] for h in hits[:3])
        return {"hits": hits, "trace": [Step(step="retrieve", ms=_ms(start), detail=f"{len(hits)} sources: {titles}...")]}

    async def generate(self, state: AgentState) -> dict:
        start = time.perf_counter()
        res = await self.llm.generate(build_messages(state["question"], state["hits"], state.get("feedback")),
                                      provider=state.get("provider"), temperature=0.1, max_tokens=self.max_tokens)
        draft = normalize_citations(res.text).strip()
        label = "revise" if state.get("feedback") else "generate"
        return {"draft": draft, "models_used": [f"{label}: {res.model}"],
                "trace": [Step(step=label, ms=_ms(start), detail=f"{len(split_claims(draft))} claims, "
                                                                 f"coverage {citation_coverage(draft):.0%}")]}

    async def verify(self, state: AgentState) -> dict:
        start = time.perf_counter()
        claims = split_claims(state["draft"])
        if not claims:
            return {"claims": [], "support_rate": 0.0,
                    "trace": [Step(step="verify", ms=_ms(start), detail="no claims found")]}
        numbered = "\n".join(f"{i}. {c}" for i, c in enumerate(claims, 1))
        try:
            res = await self.llm.generate(
                [Message(role="system", content=VERIFY_PROMPT),
                 Message(role="user", content=f"Sources:\n\n{format_sources(state['hits'])}\n\n---\nClaims:\n{numbered}")],
                provider=state.get("provider"), models=self.fast, temperature=0.0, max_tokens=1500)
            by_id = {int(r["id"]): r for r in parse_json_object(res.text).get("results", [])}
        except (LLMError, ValueError, KeyError, TypeError) as e:
            return {"claims": [], "support_rate": None,
                    "trace": [Step(step="verify", ms=_ms(start), detail=f"unavailable ({str(e)[:80]})")]}

        checks = []
        for i, text in enumerate(claims, 1):
            r = by_id.get(i, {})
            verdict = r.get("verdict") if r.get("verdict") in VERDICT_SCORE else "unsupported"
            srcs = [int(s) for s in r.get("sources", []) if str(s).isdigit() and 1 <= int(s) <= len(state["hits"])]
            checks.append(ClaimCheck(text=text, verdict=verdict, sources=srcs))
        rate = round(sum(VERDICT_SCORE[c.verdict] for c in checks) / len(checks), 3)
        counts = {v: sum(1 for c in checks if c.verdict == v) for v in VERDICT_SCORE}
        return {"claims": checks, "support_rate": rate, "models_used": [f"verify: {res.model}"],
                "trace": [Step(step="verify", ms=_ms(start), detail=f"support {rate:.0%} {counts}")]}

    async def revise(self, state: AgentState) -> dict:
        problems = [c for c in state["claims"] if c.verdict != "supported"]
        feedback = "\n".join(f"- [{c.verdict}] {c.text}" for c in problems)
        feedback += ("\nRewrite the answer. Remove every statement the sources do not support, or rewrite it "
                     "so it says only what a source says, and cite that source. Keep supported content.")
        return {"feedback": feedback, "revisions": state.get("revisions", 0) + 1,
                "trace": [Step(step="review", ms=0, detail=f"{len(problems)} claims sent back for revision")]}

    async def finalize(self, state: AgentState) -> dict:
        if not state.get("hits"):
            return {"final_answer": NO_SOURCES_ANSWER, "confidence": "none",
                    "trace": [Step(step="finalize", ms=0, detail="no sources found")]}
        rate = state.get("support_rate")
        answer = state["draft"]
        if rate is None:
            confidence = "unverified"
        else:
            confidence = "high" if rate >= 0.8 else "medium" if rate >= 0.5 else "low"
            unsupported = [c.text for c in state["claims"] if c.verdict == "unsupported"]
            if confidence == "low":
                answer = ("> **Low confidence:** most of this answer could not be verified against the "
                          "knowledge base. Treat it as a starting point and check it yourself.\n\n" + answer)
            if unsupported:
                answer += "\n\n---\n**Not found in the sources (verify before acting):**\n" + "\n".join(
                    f"- {c}" for c in unsupported)
        return {"final_answer": answer, "confidence": confidence,
                "trace": [Step(step="finalize", ms=0, detail=f"confidence {confidence}")]}

    # ---------- routing ----------
    def _after_retrieve(self, state: AgentState) -> str:
        return "generate" if state.get("hits") else "finalize"

    def _after_verify(self, state: AgentState) -> str:
        rate = state.get("support_rate")
        if rate is not None and rate < self.revise_below and state.get("revisions", 0) < self.max_revisions:
            return "revise"
        return "finalize"

    def _build(self):
        g = StateGraph(AgentState)
        for name in ("analyze", "retrieve", "generate", "verify", "revise", "finalize"):
            g.add_node(name, getattr(self, name))
        g.add_edge(START, "analyze")
        g.add_edge("analyze", "retrieve")
        g.add_conditional_edges("retrieve", self._after_retrieve, ["generate", "finalize"])
        g.add_edge("generate", "verify")
        g.add_conditional_edges("verify", self._after_verify, ["revise", "finalize"])
        g.add_edge("revise", "generate")
        g.add_edge("finalize", END)
        return g.compile()

    # ---------- entry point ----------
    async def run(self, question: str, service: str | None = None, provider: str | None = None,
                  access: list[str] | None = None) -> AgentResult:
        start = time.perf_counter()
        s = await self.graph.ainvoke({"question": question, "service": service, "provider": provider,
                                      "access": access,
                                      "revisions": 0, "trace": [], "models_used": []})
        hits = s.get("hits", [])
        sources = [to_citation(i, h) for i, h in enumerate(hits, 1)]
        valid, invalid = check_citations(s.get("draft", ""), len(hits))
        return AgentResult(
            question=question, answer=s["final_answer"], confidence=s["confidence"],
            support_rate=s.get("support_rate"), citation_coverage=citation_coverage(s.get("draft", "")),
            claims=s.get("claims", []), analysis=s.get("analysis", {}), search_query=s.get("search_query", ""),
            citations=[sources[n - 1] for n in valid], sources=sources, invalid_citations=invalid,
            revisions=s.get("revisions", 0), models_used=s.get("models_used", []), trace=s.get("trace", []),
            total_ms=_ms(start),
        )


@lru_cache
def get_agent() -> IncidentAgent:
    s = get_settings()
    return IncidentAgent(get_answerer(), get_router(), s.agent_fast_model or None, s.agent_revise_below,
                         s.agent_max_revisions, s.answer_max_tokens)
