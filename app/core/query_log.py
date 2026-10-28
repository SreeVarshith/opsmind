"""A small SQLite log of every question: who asked, which model answered, how confident, how fast.

SQLite needs no server and is enough for one team; the same table could move to Postgres later.
Logging is best effort: a logging failure must never break an answer.
"""
import logging
import sqlite3
import statistics
import time
from contextlib import closing
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    username TEXT, role TEXT, endpoint TEXT, question TEXT,
    provider TEXT, model TEXT,
    confidence TEXT, support_rate REAL, citation_coverage REAL, grounded INTEGER,
    n_sources INTEGER, revisions INTEGER, total_ms INTEGER,
    error TEXT
)"""

COLUMNS = ["username", "role", "endpoint", "question", "provider", "model", "confidence", "support_rate",
           "citation_coverage", "grounded", "n_sources", "revisions", "total_ms", "error"]


class QueryLog:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False) if path == ":memory:" else None
        with closing(self._conn()) as c:
            c.execute(SCHEMA)
            c.commit()

    def _conn(self):
        if self._memory_conn:
            return _NoClose(self._memory_conn)
        return sqlite3.connect(self.path)

    def record(self, **fields) -> None:
        try:
            values = [fields.get(col) for col in COLUMNS]
            with closing(self._conn()) as c:
                c.execute(f"INSERT INTO queries (ts, {', '.join(COLUMNS)}) VALUES (?, {', '.join('?' * len(COLUMNS))})",
                          [time.time(), *values])
                c.commit()
        except sqlite3.Error as e:
            logger.warning("query log write failed: %s", e)

    def summary(self, last_hours: float = 24 * 7, recent: int = 20) -> dict:
        since = time.time() - last_hours * 3600
        with closing(self._conn()) as c:
            cur = c.execute("SELECT * FROM queries WHERE ts >= ? ORDER BY ts DESC", (since,))
            names = [d[0] for d in cur.description]
            rows = [dict(zip(names, r)) for r in cur.fetchall()]
        ok = [r for r in rows if not r["error"]]
        latencies = sorted(r["total_ms"] for r in ok if r["total_ms"] is not None)

        def pct(p: float) -> int | None:
            return latencies[min(len(latencies) - 1, int(p * len(latencies)))] if latencies else None

        def count_by(key: str) -> dict:
            out: dict = {}
            for r in rows:
                out[r[key] or "n/a"] = out.get(r[key] or "n/a", 0) + 1
            return out

        support = [r["support_rate"] for r in ok if r["support_rate"] is not None]
        return {
            "window_hours": last_hours,
            "total_queries": len(rows),
            "errors": len(rows) - len(ok),
            "latency_ms": {"p50": pct(0.5), "p95": pct(0.95)},
            "mean_support_rate": round(statistics.mean(support), 3) if support else None,
            "by_endpoint": count_by("endpoint"),
            "by_confidence": count_by("confidence"),
            "by_model": count_by("model"),
            "by_user": count_by("username"),
            "recent": rows[:recent],
        }


class _NoClose:
    """Wraps the shared in-memory connection so `closing()` does not destroy it (used in tests)."""

    def __init__(self, conn):
        self._c = conn

    def __getattr__(self, name):
        return getattr(self._c, name)

    def close(self):
        pass


@lru_cache
def get_query_log() -> QueryLog:
    return QueryLog(get_settings().query_log_db)
