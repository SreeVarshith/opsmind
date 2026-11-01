"""Streaming, saved conversations, follow-ups, feedback, uploads and frontend serving."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agents.incident_agent import get_agent
from app.core.conversations import ConversationStore, get_conversation_store
from app.core.security import User, get_current_user
from app.ingestion import uploads
from app.llm.base import LLMError, LLMResponse, Message
from app.llm.ollama import OllamaProvider
from app.llm.openai_compat import OpenAICompatProvider
from app.llm.router import LLMRouter
from app.main import app
from app.rag.answer import build_messages, get_answerer, standalone_question
from app.rag.vector_store import get_vector_store
from tests.test_agent import GOOD, ScriptedLLM, make_agent
from tests.test_answer import FakeLLM, make_answerer
from tests.test_rag import RUNBOOK, make_store


def run(coro):
    import asyncio
    return asyncio.run(coro)


@pytest.fixture
def client(tmp_path):
    store = ConversationStore(str(tmp_path / "c.db"))
    app.dependency_overrides[get_conversation_store] = lambda: store
    app.dependency_overrides[get_answerer] = lambda: make_answerer(GOOD)[0]
    app.dependency_overrides[get_agent] = lambda: make_agent(ScriptedLLM([GOOD, GOOD, GOOD]))
    c = TestClient(app)
    c.store = store
    return c


def stream(client, **body):
    r = client.post("/conversations/stream", json={"question": "pods keep crashing", **body})
    assert r.status_code == 200, r.text
    return [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]


# ---------- streaming from providers ----------
def test_openai_compat_streams_pieces():
    def server(request):
        assert json.loads(request.content)["stream"] is True
        body = ('data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
                'data: {"choices":[{"delta":{"reasoning":"hidden"}}]}\n\n'
                'data: {"choices":[{"delta":{"content":"lo"}}]}\n\ndata: [DONE]\n\n')
        return httpx.Response(200, content=body)

    llm = OpenAICompatProvider("http://x", "key", "m", transport=httpx.MockTransport(server))

    async def collect():
        return [p async for p in llm.stream([Message(role="user", content="hi")])]
    assert run(collect()) == ["Hel", "lo"]


def test_ollama_streams_pieces():
    def server(request):
        return httpx.Response(200, content='{"message":{"content":"Hel"}}\n{"message":{"content":"lo"}}\n{"done":true}\n')

    llm = OllamaProvider("http://x", "m", transport=httpx.MockTransport(server))

    async def collect():
        return [p async for p in llm.stream([Message(role="user", content="hi")])]
    assert run(collect()) == ["Hel", "lo"]


def test_timeout_becomes_llm_error_so_fallback_can_work():
    def slow(request):
        raise httpx.ReadTimeout("slow", request=request)

    llm = OllamaProvider("http://x", "m", transport=httpx.MockTransport(slow))
    with pytest.raises(LLMError, match="did not respond"):
        run(llm.generate([Message(role="user", content="hi")]))


def test_router_stream_falls_back_only_before_the_first_piece():
    class Broken(FakeLLM):
        name = "broken"

        async def stream(self, messages, temperature=0.2, max_tokens=1024, model=None):
            raise LLMError("down")
            yield ""

    class FailsHalfway(FakeLLM):
        name = "halfway"

        async def stream(self, messages, temperature=0.2, max_tokens=1024, model=None):
            yield "partial"
            raise LLMError("cut off")

    async def collect(router):
        return [p async for p in router.stream([Message(role="user", content="hi")])]

    items = run(collect(LLMRouter({"broken": Broken("x"), "ok": FakeLLM("fine")}, default="broken")))
    assert items[0] == "fine" and isinstance(items[-1], LLMResponse) and items[-1].provider == "fake"
    with pytest.raises(LLMError):
        run(collect(LLMRouter({"halfway": FailsHalfway("x"), "ok": FakeLLM("fine")}, default="halfway")))


# ---------- streamed answers ----------
def test_agent_stream_reports_each_step_then_result_then_saved(client):
    events = stream(client, mode="agent")
    kinds = [e["type"] for e in events]
    assert kinds[-2:] == ["result", "saved"] and "sources" in kinds
    assert [e["step"] for e in events if e["type"] == "step"] == ["analyze", "retrieve", "generate", "verify", "finalize"]
    assert events[-2]["result"]["confidence"] == "high"


def test_fast_stream_sends_tokens(client):
    events = stream(client, mode="fast")
    assert "".join(e["text"] for e in events if e["type"] == "token") == GOOD
    assert events[-2]["result"]["grounded"] is True


def test_stream_error_arrives_as_an_event_and_saves_nothing(client):
    class Down(FakeLLM):
        async def stream(self, messages, temperature=0.2, max_tokens=1024, model=None):
            raise LLMError("secret internal detail")
            yield ""

    answerer = make_answerer(GOOD)[0]
    answerer.llm = LLMRouter({"down": Down("x")}, default="down")
    app.dependency_overrides[get_answerer] = lambda: answerer
    events = stream(client, mode="fast")
    assert events[-1]["type"] == "error" and "secret" not in events[-1]["detail"]
    assert client.get("/conversations").json() == []


# ---------- conversations ----------
def test_follow_up_continues_the_same_conversation(client):
    conversation_id = stream(client, mode="fast")[-1]["conversation_id"]
    stream(client, mode="fast", question="what if that fails?", conversation_id=conversation_id)
    conversations = client.get("/conversations").json()
    assert len(conversations) == 1 and conversations[0]["title"] == "pods keep crashing"
    messages = client.get(f"/conversations/{conversation_id}").json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[1]["result"]["sources"]


def test_prompt_contains_history_without_old_citation_numbers():
    history = [Message(role="user", content="pods crash"), Message(role="assistant", content="Raise memory [1].")]
    hits = make_store([RUNBOOK]).search("memory", top_k=1)
    messages = build_messages("what if that fails?", hits, history=history)
    assert [m.role for m in messages] == ["system", "user", "assistant", "user"]
    assert "[1]" not in messages[2].content


def test_standalone_question_rewrites_or_falls_back():
    history = [Message(role="user", content="etcd has no leader"), Message(role="assistant", content="Check nodes.")]
    llm = LLMRouter({"fake": FakeLLM("How to fix etcd no leader if nodes are healthy?")}, default="fake")
    assert run(standalone_question(llm, "and then?", history, None, None)).startswith("How to fix")

    class Down(FakeLLM):
        async def generate(self, messages, temperature=0.2, max_tokens=1024, model=None):
            raise LLMError("down")
    down = LLMRouter({"down": Down("x")}, default="down")
    assert run(standalone_question(down, "and then?", history, None, None)) == "etcd has no leader\nand then?"
    assert run(standalone_question(down, "first question", None, None, None)) == "first question"


def test_users_cannot_touch_each_others_conversations(client):
    conversation_id = stream(client, mode="fast")[-1]["conversation_id"]
    message_id = client.get(f"/conversations/{conversation_id}").json()["messages"][1]["id"]

    app.dependency_overrides[get_current_user] = lambda: User(username="mallory", role="developer")
    assert client.get("/conversations").json() == []
    assert client.get(f"/conversations/{conversation_id}").status_code == 404
    assert client.delete(f"/conversations/{conversation_id}").status_code == 404
    assert client.put(f"/conversations/messages/{message_id}/feedback", json={"rating": "down"}).status_code == 404
    r = client.post("/conversations/stream", json={"question": "steal this", "conversation_id": conversation_id})
    assert r.status_code == 404

    app.dependency_overrides[get_current_user] = lambda: User(username="tester", role="admin")
    assert client.delete(f"/conversations/{conversation_id}").status_code == 204
    assert client.get("/conversations").json() == []


# ---------- feedback ----------
def test_feedback_is_saved_and_summarized(client):
    conversation_id = stream(client, mode="fast")[-1]["conversation_id"]
    message_id = client.get(f"/conversations/{conversation_id}").json()["messages"][1]["id"]
    assert client.put(f"/conversations/messages/{message_id}/feedback", json={"rating": "up", "fixed": True}).status_code == 204
    saved = client.get(f"/conversations/{conversation_id}").json()["messages"][1]
    assert saved["rating"] == "up" and saved["fixed"] is True
    assert client.get("/metrics/summary").json()["feedback"] == {"answers": 1, "up": 1, "down": 0, "fixed": 1, "not_fixed": 0}


# ---------- uploads ----------
def test_extract_text_rules():
    assert "quorum" in uploads.extract_text("a.md", b"# Etcd\n\nRestore quorum by restarting the member.")
    for name, data, message in [("a.exe", b"x" * 100, "PDF, Markdown"), ("a.txt", b"short", "readable"),
                                ("a.pdf", b"not a pdf at all", "could not be read"),
                                ("a.txt", b"x" * (uploads.MAX_BYTES + 1), "5 MB"), ("a.txt", b"\xff\xfe\x00bad", "UTF-8")]:
        with pytest.raises(uploads.UploadError, match=message):
            uploads.extract_text(name, data)


def test_clean_filename_blocks_paths():
    assert uploads.clean_filename("../../etc/pass wd.md") == "pass wd.md"
    assert uploads.clean_filename("..\\..\\evil.txt") == "evil.txt"
    assert not uploads.remove("../../secrets")


def test_upload_is_searchable_replaceable_and_deletable(monkeypatch, tmp_path):
    monkeypatch.setattr(uploads, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(uploads.save, "__defaults__", (tmp_path,))
    monkeypatch.setattr(uploads.load_all, "__defaults__", (tmp_path,))
    monkeypatch.setattr(uploads.remove, "__defaults__", (tmp_path,))
    store = make_store([RUNBOOK])
    app.dependency_overrides[get_vector_store] = lambda: store
    client = TestClient(app)
    text = b"## Failover\n\nPromote the standby database replica using pg_promote."

    r = client.post("/documents/uploads", files={"file": ("failover.md", text, "text/markdown")}, data={"access": "restricted"})
    assert r.status_code == 201 and r.json()["access"] == "restricted"
    doc_id = r.json()["id"]
    assert [h.doc_id for h in store.search("promote standby replica", top_k=5, source_types=["uploaded"])] == [doc_id]
    assert store.search("promote standby replica", top_k=5, source_types=["uploaded"], access=["public"]) == []

    client.post("/documents/uploads", files={"file": ("failover.md", b"## Failover\n\nA completely new procedure text.", "text/markdown")})
    assert len(client.get("/documents/uploads").json()) == 1
    assert "new procedure" in store.search("procedure", top_k=1, source_types=["uploaded"])[0].text

    assert client.post("/documents/uploads", files={"file": ("bad.exe", b"x" * 100, "application/octet-stream")}).status_code == 422
    assert client.delete(f"/documents/uploads/{doc_id}").status_code == 204
    assert store.search("procedure", top_k=1, source_types=["uploaded"]) == []
    assert client.delete(f"/documents/uploads/{doc_id}").status_code == 404


def test_developer_cannot_upload():
    app.dependency_overrides[get_current_user] = lambda: User(username="dev", role="developer")
    r = TestClient(app).post("/documents/uploads", files={"file": ("a.md", b"x" * 100, "text/markdown")})
    assert r.status_code == 403


# ---------- serving the frontend ----------
def test_frontend_serving_and_path_guard(monkeypatch, tmp_path):
    import app.main as main
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa</html>")
    (dist / "assets" / "a.js").write_text("js")
    (tmp_path / "secret.txt").write_text("nope")
    monkeypatch.setattr(main, "FRONTEND", dist.resolve())
    client = TestClient(app, follow_redirects=False)
    assert client.get("/").headers["location"] == "/app/"
    assert client.get("/app/").text == "<html>spa</html>"
    assert client.get("/app/history").text == "<html>spa</html>"
    assert client.get("/app/assets/a.js").text == "js"
    assert "nope" not in client.get("/app/..%2Fsecret.txt").text
