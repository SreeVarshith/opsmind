"""Shared test setup: endpoint tests run as a logged-in admin with a throwaway in-memory query log.
Auth itself is tested in test_auth.py, which removes these overrides."""
import pytest

from app.core.conversations import ConversationStore, get_conversation_store
from app.core.query_log import QueryLog, get_query_log
from app.core.security import User, get_current_user
from app.main import app


@pytest.fixture(autouse=True)
def logged_in_admin(tmp_path):
    app.dependency_overrides[get_current_user] = lambda: User(username="tester", role="admin")
    app.dependency_overrides[get_query_log] = lambda: QueryLog(":memory:")
    app.dependency_overrides[get_conversation_store] = lambda: ConversationStore(str(tmp_path / "conversations.db"))
    yield
    app.dependency_overrides.clear()
