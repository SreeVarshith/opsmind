"""Agent tests: a scripted fake LLM plays triage, writer and fact-checker, so every path through
the graph (happy path, revision loop, giving up, failures) is tested without an API key."""
import asyncio
import json
import re

from fastapi.testclient import TestClient

from app.agents.incident_agent import IncidentAgent, get_agent
from app.llm.base import LLMProvider, LLMResponse
from app.llm.router import LLMRouter
from app.main import app
from app.rag.answer import Answerer
from app.rag.retriever import Retriever
from tests.test_rag import RUNBOOK, make_store

GOOD = "The pod exceeded its memory limit [1]. Increase the memory limit and redeploy [2]."
BAD = "The pod exceeded its memory limit [1]. Reboot the whole datacenter immediately."


class ScriptedLLM(LLMProvider):
    """Answers like each agent role would, based on which system prompt it receives."""
    name = "openai_compat"
    model = "main-model"

    def __init__(self, drafts: list[str], analyze_reply: str | None = None, verify_ok: bool = True):
        self.drafts = list(drafts)
        self.analyze_reply = analyze_reply or json.dumps(
            {"category": "kubernetes-workload", "summary": "pods crash", "search_query": "KubePodCrashLooping"})
        self.verify_ok = verify_ok
        self.calls: list[tuple[str, str]] = []   # (role, model)

    async def generate(self, messages, temperature=0.2, max_tokens=1024, model=None):
        system, user = messages[0].content, messages[-1].content
        if system.startswith("You triage"):
            role, text = "analyze", self.analyze_reply
        elif system.startswith("You are a strict fact-checker"):
            role = "verify"
            claims = re.findall(r"^(\d+)\. (.+)$", user.split("Claims:")[-1], flags=re.MULTILINE)
            text = json.dumps({"results": [
                {"id": int(i), "verdict": "unsupported" if "datacenter" in c else "supported", "sources": [1]}
                for i, c in claims]}) if self.verify_ok else "sorry, no JSON"
        else:
            role, text = "generate", self.drafts.pop(0)
        self.calls.append((role, model or self.model))
        return LLMResponse(text=text, provider=self.name, model=model or self.model, latency_ms=1)


def make_agent(llm: ScriptedLLM, **kwargs) -> IncidentAgent:
    retriever = Retriever(make_store([RUNBOOK]), None, mode="hybrid", rerank=False)
    router = LLMRouter({"openai_compat": llm}, default="openai_compat")
    answerer = Answerer(retriever, router, quotas={"runbook": 2})
    return IncidentAgent(answerer, router, fast_model="fast-model", **kwargs)


def run(agent, question="pods keep crashing", **kw):
    return asyncio.run(agent.run(question, **kw))


def test_happy_path_no_revision():
    llm = ScriptedLLM([GOOD])
    result = run(make_agent(llm))
    assert result.confidence == "high" and result.support_rate == 1.0 and result.revisions == 0
    assert [s.step for s in result.trace] == ["analyze", "retrieve", "generate", "verify", "finalize"]
    assert result.search_query == "KubePodCrashLooping"
    assert "Not found in the sources" not in result.answer


def test_quick_steps_use_the_fast_model():
    llm = ScriptedLLM([GOOD])
    run(make_agent(llm))
    assert llm.calls == [("analyze", "fast-model"), ("generate", "main-model"), ("verify", "fast-model")]


def test_unsupported_claim_triggers_one_revision_that_fixes_it():
    llm = ScriptedLLM([BAD, GOOD])
    result = run(make_agent(llm))
    assert result.revisions == 1
    assert [s.step for s in result.trace] == ["analyze", "retrieve", "generate", "verify", "review",
                                              "revise", "verify", "finalize"]
    assert result.confidence == "high" and "datacenter" not in result.answer


def test_gives_up_after_max_revisions_and_flags_the_claim():
    llm = ScriptedLLM([BAD, BAD])
    result = run(make_agent(llm, revise_below=0.9, max_revisions=1))
    assert result.revisions == 1 and result.support_rate == 0.5
    assert result.confidence == "medium"
    assert "Not found in the sources" in result.answer and "datacenter" in result.answer.split("---")[-1]


def test_low_confidence_warning():
    llm = ScriptedLLM(["Reboot the whole datacenter immediately."])
    result = run(make_agent(llm, max_revisions=0))
    assert result.confidence == "low" and result.answer.startswith("> **Low confidence:**")


def test_bad_triage_json_falls_back_to_the_question():
    llm = ScriptedLLM([GOOD], analyze_reply="not json at all")
    result = run(make_agent(llm))
    assert result.search_query == "" and result.confidence == "high"
    assert result.trace[0].detail.startswith("skipped")


def test_verifier_failure_means_unverified_not_crash():
    llm = ScriptedLLM([GOOD], verify_ok=False)
    result = run(make_agent(llm))
    assert result.confidence == "unverified" and result.support_rate is None and result.revisions == 0


def test_no_sources():
    llm = ScriptedLLM([])
    result = run(make_agent(llm), service="no-such-service")
    assert result.confidence == "none" and [s.step for s in result.trace][-1] == "finalize"
    assert ("generate", "main-model") not in llm.calls


def test_agent_endpoint():
    app.dependency_overrides[get_agent] = lambda: make_agent(ScriptedLLM([GOOD]))
    try:
        r = TestClient(app).post("/agent/ask", json={"question": "pods keep crashing"})
        assert r.status_code == 200
        body = r.json()
        assert body["confidence"] == "high" and len(body["claims"]) == 2
    finally:
        app.dependency_overrides.clear()
