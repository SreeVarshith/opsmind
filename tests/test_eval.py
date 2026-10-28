"""Tests for the evaluation tooling itself: if the measuring stick is wrong, every result is wrong."""
from app.ingestion.schema import Document
from app.llm.json_utils import parse_json_object
from app.rag.retriever import Retriever
from eval.answer_eval import ExcludingRetriever
from eval.answer_report import bootstrap_ci, paired
from eval.verifier_audit import cohen_kappa
from tests.test_rag import RUNBOOK, make_store


def test_excluding_retriever_hides_the_ticket_under_test():
    tickets = [Document(id=f"ticket-{i}", source_type="ticket", title=f"Pod crash {i}",
                        text="pod crash looping memory limit", source=f"tickets/{i}") for i in range(3)]
    r = ExcludingRetriever(Retriever(make_store([RUNBOOK, *tickets]), None, mode="hybrid", rerank=False))
    r.exclude = {"ticket-1"}
    hits = r.retrieve("pod crash looping memory", 3, ["ticket"])
    assert len(hits) == 2 and "ticket-1" not in {h.doc_id for h in hits}


def test_bootstrap_ci_brackets_the_mean():
    lo, hi = bootstrap_ci([1.0] * 30 + [0.0] * 10)
    assert lo < 0.75 < hi and 0.5 < lo and hi <= 1.0


def test_cohen_kappa():
    perfect = [("supported", "supported"), ("unsupported", "unsupported"), ("partial", "partial")]
    assert cohen_kappa(perfect) == 1.0
    always_supported = [("supported", "supported"), ("unsupported", "supported")] * 5
    assert cohen_kappa(always_supported) == 0.0   # agreeing only by always saying "supported" is chance level


def test_paired_comparison():
    a = [{"ticket_id": "1", "judge_score": 3}, {"ticket_id": "2", "judge_score": 5}, {"ticket_id": "3", "judge_score": 4}]
    b = [{"ticket_id": "1", "judge_score": 5}, {"ticket_id": "2", "judge_score": 5}, {"ticket_id": "3", "judge_score": 2}]
    assert paired(a, b) == {"n": 3, "b_better": 1, "same": 1, "a_better": 1}


def test_parse_json_skips_reasoning_blocks():
    text = '<think>maybe {"score": 1}?</think>\n```json\n{"score": 4, "reason": "ok"}\n```'
    assert parse_json_object(text) == {"score": 4, "reason": "ok"}
