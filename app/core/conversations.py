"""Saved conversations and answer feedback, in the same SQLite file as the query log.

Every read and write is scoped to the owner's username, so one user can never open, change or
delete another user's conversation, even with a valid id.
"""
import json
import sqlite3
import time
import uuid
from contextlib import closing
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings
from app.llm.base import Message

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY, username TEXT NOT NULL, title TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL, content TEXT NOT NULL, mode TEXT, result TEXT, created REAL NOT NULL,
    rating TEXT, fixed INTEGER, feedback_at REAL
);
CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(username, updated);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created);
"""


class ConversationStore:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conn()) as c:
            c.executescript(SCHEMA)
            c.commit()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def save_exchange(self, username: str, conversation_id: str | None, question: str, answer: str, mode: str,
                      result: dict) -> tuple[str, str]:
        """Store one question and its answer, creating the conversation if needed.
        Returns (conversation id, answer message id). Raises KeyError for someone else's conversation."""
        now = time.time()
        answer_id = uuid.uuid4().hex
        with closing(self._conn()) as c:
            if conversation_id:
                if not c.execute("SELECT 1 FROM conversations WHERE id = ? AND username = ?",
                                 (conversation_id, username)).fetchone():
                    raise KeyError(conversation_id)
                c.execute("UPDATE conversations SET updated = ? WHERE id = ?", (now, conversation_id))
            else:
                conversation_id = uuid.uuid4().hex
                c.execute("INSERT INTO conversations VALUES (?, ?, ?, ?, ?)",
                          (conversation_id, username, question.strip()[:80], now, now))
            c.execute("INSERT INTO messages (id, conversation_id, role, content, created) VALUES (?, ?, 'user', ?, ?)",
                      (uuid.uuid4().hex, conversation_id, question, now))
            c.execute("INSERT INTO messages (id, conversation_id, role, content, mode, result, created) "
                      "VALUES (?, ?, 'assistant', ?, ?, ?, ?)",
                      (answer_id, conversation_id, answer, mode, json.dumps(result), now + 0.001))
            c.commit()
        return conversation_id, answer_id

    def list_for_user(self, username: str, limit: int = 100) -> list[dict]:
        with closing(self._conn()) as c:
            rows = c.execute("SELECT id, title, created, updated FROM conversations WHERE username = ? "
                             "ORDER BY updated DESC LIMIT ?", (username, limit)).fetchall()
        return [dict(r) for r in rows]

    def get(self, username: str, conversation_id: str) -> dict | None:
        with closing(self._conn()) as c:
            conv = c.execute("SELECT id, title, created, updated FROM conversations WHERE id = ? AND username = ?",
                             (conversation_id, username)).fetchone()
            if conv is None:
                return None
            rows = c.execute("SELECT id, role, content, mode, result, created, rating, fixed FROM messages "
                             "WHERE conversation_id = ? ORDER BY created", (conversation_id,)).fetchall()
        messages = []
        for r in rows:
            m = dict(r)
            m["result"] = json.loads(m["result"]) if m["result"] else None
            m["fixed"] = None if m["fixed"] is None else bool(m["fixed"])
            messages.append(m)
        return {**dict(conv), "messages": messages}

    def history(self, username: str, conversation_id: str) -> list[Message] | None:
        conv = self.get(username, conversation_id)
        if conv is None:
            return None
        return [Message(role=m["role"], content=m["content"]) for m in conv["messages"]]

    def delete(self, username: str, conversation_id: str) -> bool:
        with closing(self._conn()) as c:
            deleted = c.execute("DELETE FROM conversations WHERE id = ? AND username = ?",
                                (conversation_id, username)).rowcount
            c.commit()
        return bool(deleted)

    def set_feedback(self, username: str, message_id: str, rating: str | None, fixed: bool | None) -> bool:
        with closing(self._conn()) as c:
            changed = c.execute(
                "UPDATE messages SET rating = ?, fixed = ?, feedback_at = ? WHERE id = ? AND role = 'assistant' "
                "AND conversation_id IN (SELECT id FROM conversations WHERE username = ?)",
                (rating, None if fixed is None else int(fixed), time.time(), message_id, username)).rowcount
            c.commit()
        return bool(changed)

    def feedback_summary(self, last_hours: float) -> dict:
        since = time.time() - last_hours * 3600
        with closing(self._conn()) as c:
            row = c.execute(
                "SELECT COUNT(*) AS answers, "
                "COALESCE(SUM(rating = 'up'), 0) AS up, COALESCE(SUM(rating = 'down'), 0) AS down, "
                "COALESCE(SUM(fixed = 1), 0) AS fixed, "
                "COALESCE(SUM(fixed = 0), 0) AS not_fixed "
                "FROM messages WHERE role = 'assistant' AND created >= ?", (since,)).fetchone()
        return dict(row)


@lru_cache
def get_conversation_store() -> ConversationStore:
    return ConversationStore(get_settings().query_log_db)
