"""Answer a question from retrieved sources, with numbered citations.

    retrieve -> number the sources [1]..[n] -> LLM answers citing them -> check the citations

The citation check is the first, simplest guard against hallucination: every [n] in the answer
must point to a source the model was actually given. Step 7 adds a deeper check (does the
cited source really support the sentence?).
"""
import re
import time
from functools import lru_cache

from pydantic import BaseModel

from app.core.config import get_settings
from app.llm.base import Message
from app.llm.router import LLMRouter, get_router
from app.rag.retriever import Retriever, get_retriever
from app.rag.vector_store import SearchHit

SYSTEM_PROMPT = """You are OpsMind, an incident-response assistant for on-call engineers.

Answer the engineer's question using ONLY the numbered sources provided.
Rules:
- After every factual sentence, cite the source(s) it comes from, like [1] or [2][3].
- Never cite a number that is not in the sources list.
- Sources may describe the same problem on a different service, pod or system. When the symptoms
  match, apply them to the engineer's situation.
- Only if NONE of the sources is relevant, say that the knowledge base does not cover it.
  Never add facts that are not in the sources.
- Be concise and practical. Prefer concrete commands from the sources.

Format your answer in Markdown with these sections (skip a section if the sources have nothing for it):
**Likely cause** - one or two sentences
**What to check** - short numbered steps
**How to fix** - short numbered steps
**Similar past incidents** - one line each, only if a ticket or postmortem source matches"""

NO_SOURCES_ANSWER = ("I could not find anything relevant in the knowledge base for this question. "
                     "Try adding the exact error message or the alert name.")

# Matches [1], [2,3], [2, 3] and [1-2] style citations.
CITATION = re.compile(r"\[(\d+(?:\s*[,-]\s*\d+)*)\]")


class Citation(BaseModel):
    number: int
    title: str
    section: str | None
    source_type: str
    source: str
    snippet: str


class Timings(BaseModel):
    retrieval_ms: int
    generation_ms: int
    total_ms: int


class AskResult(BaseModel):
    question: str
    answer: str
    citations: list[Citation]          # sources the answer actually cites, in order
    sources: list[Citation]            # every source the LLM was given
    invalid_citations: list[int]       # numbers cited that were not provided -> hallucinated
    grounded: bool                     # True if it cites at least one real source and no fake ones
    citation_coverage: float           # share of answer sentences that cite a source (0-1)
    provider: str | None
    model: str | None
    timings: Timings


def format_sources(hits: list[SearchHit]) -> str:
    blocks = []
    for i, h in enumerate(hits, 1):
        blocks.append(f"[{i}] ({h.source_type}) {h.title}" + (f" - {h.section}" if h.section else "")
                      + f"\n{h.text}")
    return "\n\n".join(blocks)


def normalize_citations(answer: str) -> str:
    """Rewrite other citation styles to [n]. gpt-oss, for example, often writes 【1†L1-L4】
    (its native "source 1, lines 1-4" format) despite being asked for [1]."""
    answer = re.sub(r"【\s*(\d+)\s*(?:†[^】]*)?】", r"[\1]", answer)
    return re.sub(r"\[\^(\d+)\]", r"[\1]", answer)  # Markdown footnote style [^1]


def _prose(answer: str) -> str:
    """The answer without code, so `items[0]` in a kubectl command is not mistaken for a citation."""
    prose = re.sub(r"```.*?```", " ", answer, flags=re.DOTALL)
    return re.sub(r"`[^`\n]*`", "CODE", prose)


def extract_citations(answer: str) -> list[int]:
    """All citation numbers in order of first appearance, e.g. 'a [2] b [1, 3]' -> [2, 1, 3]."""
    numbers: list[int] = []
    for group in CITATION.findall(_prose(answer)):
        for part in re.split(r"\s*,\s*", group):
            if "-" in part:
                lo, hi = (int(x) for x in part.split("-"))
                numbers.extend(range(lo, hi + 1) if hi - lo < 20 else [lo, hi])
            else:
                numbers.append(int(part))
    return list(dict.fromkeys(numbers))


def citation_coverage(answer: str) -> float:
    """Share of claim sentences that carry at least one citation (0.0 - 1.0).

    A "claim" is a sentence or list item of real content; headings like **How to fix** and very
    short fragments are skipped. Low coverage means much of the answer cannot be traced to a source.
    """
    claims = []
    for line in _prose(answer).splitlines():
        line = re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", line).strip()       # list markers
        if not line or re.fullmatch(r"(#+.*|\*\*[^*]+\*\*:?)", line):   # empty or heading
            continue
        line = re.sub(r"^\*\*[^*]+\*\*:?\s*", "", line)                 # inline bold label
        claims += [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", line) if len(s) >= 15]
    if not claims:
        return 0.0
    return round(sum(1 for c in claims if CITATION.search(c)) / len(claims), 3)


def to_citation(n: int, h: SearchHit) -> Citation:
    body = h.text.split("\n", 1)[-1]  # drop the context header line
    return Citation(number=n, title=h.title, section=h.section, source_type=h.source_type,
                    source=h.source, snippet=body[:300])


class Answerer:
    def __init__(self, retriever: Retriever, llm: LLMRouter, top_k: int = 6, max_tokens: int = 1200,
                 quotas: dict[str, int] | None = None):
        self.retriever = retriever
        self.llm = llm
        self.top_k = top_k
        self.max_tokens = max_tokens
        self.quotas = quotas or {}

    def gather_sources(self, question: str, top_k: int | None, source_types: list[str] | None,
                       service: str | None) -> list[SearchHit]:
        """Explicit filter or top_k -> plain search. Otherwise a balanced mix using the quotas,
        in quota order (runbooks first: they are the authoritative fix)."""
        if source_types or top_k or not self.quotas:
            return self.retriever.retrieve(question, top_k or self.top_k, source_types, service)
        hits: list[SearchHit] = []
        for source_type, n in self.quotas.items():
            hits += self.retriever.retrieve(question, n, [source_type], service)
        return hits

    async def ask(self, question: str, top_k: int | None = None, source_types: list[str] | None = None,
                  service: str | None = None, provider: str | None = None) -> AskResult:
        start = time.perf_counter()
        hits = self.gather_sources(question, top_k, source_types, service)
        retrieval_ms = int((time.perf_counter() - start) * 1000)
        sources = [to_citation(i, h) for i, h in enumerate(hits, 1)]

        if not hits:
            return AskResult(question=question, answer=NO_SOURCES_ANSWER, citations=[], sources=[],
                             invalid_citations=[], grounded=False, citation_coverage=0.0,
                             provider=None, model=None,
                             timings=Timings(retrieval_ms=retrieval_ms, generation_ms=0, total_ms=retrieval_ms))

        messages = [
            Message(role="system", content=SYSTEM_PROMPT),
            Message(role="user", content=f"Sources:\n\n{format_sources(hits)}\n\n---\nQuestion: {question}"),
        ]
        res = await self.llm.generate(messages, provider=provider, temperature=0.1, max_tokens=self.max_tokens)
        text = normalize_citations(res.text).strip()

        cited = extract_citations(text)
        valid = [n for n in cited if 1 <= n <= len(hits)]
        invalid = [n for n in cited if n not in valid]
        return AskResult(
            question=question,
            answer=text,
            citations=[sources[n - 1] for n in valid],
            sources=sources,
            invalid_citations=invalid,
            grounded=bool(valid) and not invalid,
            citation_coverage=citation_coverage(text),
            provider=res.provider,
            model=res.model,
            timings=Timings(retrieval_ms=retrieval_ms, generation_ms=res.latency_ms,
                            total_ms=int((time.perf_counter() - start) * 1000)),
        )


@lru_cache
def get_answerer() -> Answerer:
    s = get_settings()
    return Answerer(get_retriever(), get_router(), s.answer_top_k, s.answer_max_tokens, s.answer_quotas)
