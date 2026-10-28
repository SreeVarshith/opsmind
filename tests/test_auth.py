"""Login, tokens, roles and document-level access control."""
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.query_log import QueryLog, get_query_log
from app.core.security import (
    User,
    UserStore,
    create_token,
    get_current_user,
    get_user_store,
    hash_password,
    verify_password,
)
from app.ingestion.schema import Document
from app.main import app
from app.rag.access import PUBLIC, RESTRICTED, access_level
from app.rag.chunking import chunk_document
from app.rag.retriever import Retriever, get_retriever
from tests.test_rag import RUNBOOK, make_store

SECRET = "test-secret-" + "x" * 40
ETCD_RUNBOOK = Document(
    id="runbook-etcd", source_type="runbook", title="etcd No Leader [etcdNoLeader]", source="https://x/etcdnoleader",
    metadata={"component": "etcd", "alert": "etcdNoLeader"},
    text="# etcdNoLeader\n\n## Mitigation\n\nRestore quorum: restart the etcd member with etcdctl member list.")


@pytest.fixture
def real_auth(tmp_path, monkeypatch):
    """Undo the conftest admin override and use a temporary user store and secret."""
    app.dependency_overrides.pop(get_current_user, None)
    s = get_settings()
    monkeypatch.setattr(s, "auth_enabled", True)
    monkeypatch.setattr(s, "jwt_secret", SECRET)
    store = UserStore(tmp_path / "users.json")
    store.add("alice", "correct-horse-battery", "sre")
    store.add("bob", "another-long-password", "developer")
    app.dependency_overrides[get_user_store] = lambda: store
    return TestClient(app)


def login(client, username, password):
    return client.post("/auth/login", json={"username": username, "password": password})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


# ---------- passwords ----------
def test_password_hash_roundtrip_and_salt():
    h1, h2 = hash_password("s3cret-pass"), hash_password("s3cret-pass")
    assert h1 != h2                          # random salt: same password, different hash
    assert verify_password("s3cret-pass", h1) and not verify_password("wrong", h1)
    assert "s3cret-pass" not in h1


def test_unknown_role_rejected(tmp_path):
    with pytest.raises(ValueError):
        UserStore(tmp_path / "u.json").add("eve", "long-enough-pass", "superuser")


# ---------- login & tokens ----------
def test_login_and_me(real_auth):
    r = login(real_auth, "alice", "correct-horse-battery")
    assert r.status_code == 200 and r.json()["role"] == "sre"
    me = real_auth.get("/auth/me", headers=bearer(r.json()["access_token"])).json()
    assert me == {"username": "alice", "role": "sre", "access": [PUBLIC, RESTRICTED]}


def test_wrong_password_and_unknown_user_look_the_same(real_auth):
    a, b = login(real_auth, "alice", "nope"), login(real_auth, "mallory", "nope")
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_protected_endpoints_need_a_token(real_auth):
    assert real_auth.post("/search", json={"query": "pods"}).status_code == 401
    assert real_auth.get("/health").status_code == 200  # health stays public


def test_tampered_and_expired_tokens_are_rejected(real_auth):
    forged = create_token(User(username="alice", role="admin"), "some-other-secret", 60)
    assert real_auth.get("/auth/me", headers=bearer(forged)).status_code == 401
    expired = jwt.encode({"sub": "alice", "role": "sre", "exp": int(time.time()) - 10}, SECRET, algorithm="HS256")
    r = real_auth.get("/auth/me", headers=bearer(expired))
    assert r.status_code == 401 and "expired" in r.json()["detail"]


def test_developer_cannot_read_metrics_or_raw_documents(real_auth):
    token = login(real_auth, "bob", "another-long-password").json()["access_token"]
    assert real_auth.get("/metrics/summary", headers=bearer(token)).status_code == 403
    assert real_auth.get("/documents/stats", headers=bearer(token)).status_code == 403


# ---------- document access control ----------
def test_access_policy_labels():
    assert access_level(chunk_document(ETCD_RUNBOOK)[0]) == RESTRICTED
    assert access_level(chunk_document(RUNBOOK)[0]) == PUBLIC


def test_search_filters_restricted_documents_by_role(real_auth):
    app.dependency_overrides[get_retriever] = lambda: Retriever(make_store([RUNBOOK, ETCD_RUNBOOK]), None,
                                                                mode="hybrid", rerank=False)
    query = {"query": "restart etcd member quorum", "top_k": 10}

    dev = login(real_auth, "bob", "another-long-password").json()["access_token"]
    dev_hits = real_auth.post("/search", json=query, headers=bearer(dev)).json()["hits"]
    assert dev_hits and all(h["doc_id"] != "runbook-etcd" for h in dev_hits)

    sre = login(real_auth, "alice", "correct-horse-battery").json()["access_token"]
    sre_hits = real_auth.post("/search", json=query, headers=bearer(sre)).json()["hits"]
    assert sre_hits[0]["doc_id"] == "runbook-etcd"


# ---------- query log ----------
def test_query_log_summary():
    log = QueryLog(":memory:")
    log.record(username="a", endpoint="ask", model="m1", total_ms=100, citation_coverage=0.5, grounded=1)
    log.record(username="b", endpoint="agent", model="m2", confidence="high", support_rate=0.9, total_ms=300)
    log.record(username="b", endpoint="agent", error="rate limited")
    s = log.summary()
    assert s["total_queries"] == 3 and s["errors"] == 1
    assert s["latency_ms"]["p50"] == 300 and s["mean_support_rate"] == 0.9
    assert s["by_user"] == {"a": 1, "b": 2}


def test_metrics_endpoint_for_admin():
    log = QueryLog(":memory:")
    log.record(username="a", endpoint="ask", total_ms=50)
    app.dependency_overrides[get_query_log] = lambda: log
    r = TestClient(app).get("/metrics/summary")
    assert r.status_code == 200 and r.json()["total_queries"] == 1
