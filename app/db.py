"""SQLite access: one connection per thread, WAL mode, a process-wide write lock."""
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from . import config

_local = threading.local()
_write_lock = threading.RLock()


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse(ts: str | None) -> datetime | None:
    return datetime.fromisoformat(ts) if ts else None


def conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        os.makedirs(os.path.dirname(config.DATABASE_PATH), exist_ok=True)
        c = sqlite3.connect(config.DATABASE_PATH, timeout=30, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        _local.conn = c
    return c


@contextmanager
def tx():
    """A write transaction. Serialises writers inside this process; SQLite's lock covers other processes."""
    with _write_lock:
        c = conn()
        try:
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise


def q(sql: str, params=()) -> list[sqlite3.Row]:
    return conn().execute(sql, params).fetchall()


def q1(sql: str, params=()):
    return conn().execute(sql, params).fetchone()


def init_schema():
    with open(os.path.join(os.path.dirname(__file__), "schema.sql")) as f:
        conn().executescript(f.read())


def event(c: sqlite3.Connection, case_id: str, event_type: str, actor: str = "system", **payload):
    c.execute("INSERT INTO case_event (case_id, event_type, payload, actor, created_at) VALUES (?,?,?,?,?)",
              (case_id, event_type, json.dumps(payload, ensure_ascii=False), actor, iso(now())))


def sla_delta(hours: float) -> timedelta:
    """Convert an SLA in business hours into demo wall-clock time."""
    return timedelta(seconds=hours * config.SLA_SECONDS_PER_HOUR)
