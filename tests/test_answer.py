"""Answer tests use the in-memory store from test_rag and a fake LLM, so they need no API key."""
import asyncio

from fastapi.testclient import TestClient

from app.llm.base import LLMProvider, LLMResponse
from app.llm.router import LLMRouter
from app.main import app
from app.rag.answer import (
    NO_SOURCES_ANSWER,
    Answerer,
    citation_coverage,
    extract_citations,
    format_sources,
    get_answerer,
    normalize_citations,
)
from app.rag.retriever import Retriever
from tests.test_rag import RUNBOOK, make_store


class FakeLLM(LLMProvider):
    name = "fake"
    model = "fake-1"

    def __init__(self, reply: str):
        self.reply = reply
        self.last_messages = None

    async def generate(self, messages, temperature=0.2, max_tokens=1024, model=None):
        self.last_messages = messages
        return LLMResponse(text=self.reply, provider=self.name, model=self.model, latency_ms=5)


def make_answerer(reply: str) -> tuple[Answerer, FakeLLM]:
    llm = FakeLLM(reply)
    retriever = Retriever(make_store([RUNBOOK]), None, mode="hybrid", rerank=False)
    return Answerer(retriever, LLMRouter({"fake": llm}, default="fake"), top_k=2), llm


def test_extract_citations_formats():
    assert extract_citations("a [2] b [1, 3] c [2][4] d [5-6]") == [2, 1, 3, 4, 5, 6]


def test_other_citation_styles_are_normalized():
    text = "Leader lost【1†L1-L4】【3†L1-L8】. Check disks【2】. See notes[^4]."
    assert normalize_citations(text) == "Leader lost[1][3]. Check disks[2]. See notes[4]."


def test_gpt_oss_style_answer_counts_as_grounded():
    answerer, _ = make_answerer("Increase the memory limit【1†L2-L5】.")
    result = asyncio.run(answerer.ask("how to fix crash looping pods"))
    assert result.grounded and result.answer == "Increase the memory limit[1]."


def test_extract_citations_ignores_code():
    text = "Run `kubectl get pod -o jsonpath='{.items[0]}'` [1]\n```\nx = arr[7]\n```"
    assert extract_citations(text) == [1]


def test_citation_coverage_counts_cited_sentences():
    answer = ("**Likely cause**\nThe container exceeded its memory limit [1].\n\n"
              "**How to fix**\n1. Raise the memory limit in the deployment spec [2].\n"
              "2. Restart the deployment so the new limits apply.\n"
              "Run `kubectl rollout restart deployment/x` to apply it.")
    assert citation_coverage(answer) == 0.5   # 2 of 4 claim sentences cited; headings ignored
    assert citation_coverage("") == 0.0


def test_format_sources_numbers_each_hit():
    hits = make_store([RUNBOOK]).search("memory", top_k=2)
    text = format_sources(hits)
    assert text.startswith("[1] (runbook)") and "\n\n[2] (runbook)" in text


def test_grounded_answer():
    answerer, llm = make_answerer("Increase the memory limit [1].")
    result = asyncio.run(answerer.ask("how to fix crash looping pods"))
    assert result.grounded and result.invalid_citations == []
    assert [c.number for c in result.citations] == [1]
    assert len(result.sources) == 2
    assert "Sources:" in llm.last_messages[1].content  # the sources reached the LLM


def test_hallucinated_citation_is_flagged():
    answerer, _ = make_answerer("Increase memory [1]. Also reboot the datacenter [7].")
    result = asyncio.run(answerer.ask("how to fix crash looping pods"))
    assert result.invalid_citations == [7]
    assert result.grounded is False


def test_answer_without_citations_is_not_grounded():
    answerer, _ = make_answerer("Just restart it.")
    assert asyncio.run(answerer.ask("how to fix crash looping pods")).grounded is False


def test_no_sources_skips_the_llm():
    answerer, llm = make_answerer("should not be called")
    result = asyncio.run(answerer.ask("anything", service="no-such-service"))
    assert result.answer == NO_SOURCES_ANSWER and llm.last_messages is None


def test_quotas_give_a_balanced_mix_runbooks_first():
    from app.ingestion.schema import Document

    tickets = [Document(id=f"ticket-{i}", source_type="ticket", title=f"Pod crash {i}",
                        text="pod crash looping memory limit restart", source=f"tickets/{i}") for i in range(5)]
    retriever = Retriever(make_store([RUNBOOK, *tickets]), None, mode="hybrid", rerank=False)
    answerer = Answerer(retriever, LLMRouter({"fake": FakeLLM("x [1]")}, default="fake"),
                        quotas={"runbook": 1, "ticket": 2})
    hits = answerer.gather_sources("pod crash looping memory", None, None, None)
    assert [h.source_type for h in hits] == ["runbook", "ticket", "ticket"]
    # an explicit top_k or filter bypasses the quotas
    assert len(answerer.gather_sources("pod crash", 4, ["ticket"], None)) == 4


def test_ask_endpoint():
    app.dependency_overrides[get_answerer] = lambda: make_answerer("Increase the memory limit [1].")[0]
    try:
        r = TestClient(app).post("/ask", json={"question": "pods keep crashing"})
        assert r.status_code == 200
        body = r.json()
        assert body["grounded"] is True and body["citations"][0]["source_type"] == "runbook"
    finally:
        app.dependency_overrides.clear()
