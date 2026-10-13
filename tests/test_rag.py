"""RAG tests run on an in-memory Qdrant with a tiny fake embedder: no Docker, no model download."""
import hashlib
import math
import re

from fastapi.testclient import TestClient
from qdrant_client import QdrantClient

from app.ingestion.schema import Document
from app.main import app
from app.rag.chunking import MAX_CHARS, chunk_document
from app.rag.vector_store import VectorStore, get_vector_store

RUNBOOK = Document(
    id="runbook-1", source_type="runbook", title="Kube Pod Crash Looping [KubePodCrashLooping]",
    source="https://runbooks.example/kubepodcrashlooping",
    metadata={"component": "kubernetes", "alert": "KubePodCrashLooping"},
    text="# KubePodCrashLooping\n\n## Meaning\n\nPod restarts again and again.\n\n"
         "## Mitigation\n\nIncrease the memory limit and redeploy.",
)


class FakeEmbedder:
    """Bag-of-words hashed into 64 dimensions: similar words -> similar vectors. Good enough for tests."""
    dim = 64

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for word in re.findall(r"[a-z]+", text.lower()):
            v[int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dim] += 1
        norm = math.sqrt(sum(x * x for x in v)) or 1
        return [x / norm for x in v]

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


def make_store(docs: list[Document]) -> VectorStore:
    from app.rag.chunking import chunk_documents

    store = VectorStore(QdrantClient(":memory:"), "test", FakeEmbedder())
    store.recreate()
    store.upsert(chunk_documents(docs))
    return store


def test_runbook_is_chunked_by_section_with_context_header():
    chunks = chunk_document(RUNBOOK)
    assert [c.section for c in chunks] == ["Meaning", "Mitigation"]
    assert chunks[1].text.startswith("[runbook] Kube Pod Crash Looping [KubePodCrashLooping] - Mitigation")
    assert chunks[1].chunk_id == "runbook-1#1"


def test_short_documents_stay_whole():
    doc = Document(id="ticket-1", source_type="ticket", title="t", text="short ticket", source="tickets/1")
    assert len(chunk_document(doc)) == 1


def test_long_text_is_split_below_the_limit():
    doc = Document(id="pm-1", source_type="postmortem", title="t", source="x",
                   text="\n\n".join(f"Paragraph {i} " + "word " * 60 for i in range(20)))
    chunks = chunk_document(doc)
    assert len(chunks) > 1
    assert all(len(c.text) <= MAX_CHARS + 100 for c in chunks)  # +header


def test_search_finds_the_relevant_section():
    store = make_store([RUNBOOK])
    hits = store.search("how do I fix it, increase memory limit", top_k=1)
    assert hits[0].section == "Mitigation"
    assert hits[0].source == RUNBOOK.source


def test_search_filters_by_source_type():
    ticket = Document(id="ticket-1", source_type="ticket", title="Pod restarts",
                      text="Pod restarts again and again", source="tickets/1", metadata={"service": "checkout-api"})
    store = make_store([RUNBOOK, ticket])
    assert {h.source_type for h in store.search("pod restarts", top_k=5, source_types=["ticket"])} == {"ticket"}
    assert store.search("pod restarts", top_k=5, service="checkout-api")[0].doc_id == "ticket-1"
    assert store.search("pod restarts", top_k=5, service="other-service") == []


def test_search_endpoint():
    app.dependency_overrides[get_vector_store] = lambda: make_store([RUNBOOK])
    try:
        r = TestClient(app).post("/search", json={"query": "increase memory limit", "top_k": 1})
        assert r.status_code == 200
        assert r.json()["hits"][0]["section"] == "Mitigation"
    finally:
        app.dependency_overrides.clear()
