"""MongoDB storage: users, todos, chat threads, messages and files.

Set MONGODB_URI (a free MongoDB Atlas cluster works). Every document except `users`
carries a `user_id`, and every query in the services filters by the signed-in user.
Tests use `mongomock://…` instead of a real server.
"""
from __future__ import annotations

import contextvars
import os
from datetime import datetime, timezone

DB_NAME = os.getenv("MONGODB_DB", "ask_atharva")


class DatabaseNotConfigured(RuntimeError):
    pass


class NotSignedIn(RuntimeError):
    pass


def now() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime | None) -> datetime | None:
    """Mongo hands datetimes back naive (UTC); make them timezone-aware again."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


_client = None
_indexed = False


def _uri() -> str:
    return os.getenv("MONGODB_URI") or os.getenv("MONGODB_URL") or ""


def configured() -> bool:
    return bool(_uri())


def database():
    """The shared database handle (one client reused across requests)."""
    global _client, _indexed
    if _client is None:
        uri = _uri()
        if not uri:
            raise DatabaseNotConfigured("MONGODB_URI isn't set. Add your MongoDB connection string to .env (or to Vercel's environment variables).")
        if uri.startswith("mongomock://"):
            import mongomock

            _client = mongomock.MongoClient()
        else:
            from pymongo import MongoClient

            _client = MongoClient(uri, serverSelectionTimeoutMS=8000, maxPoolSize=5, tz_aware=True)
    db = _client[DB_NAME]
    if not _indexed:
        db.users.create_index("email", unique=True)
        db.todos.create_index([("user_id", 1), ("done", 1)])
        db.threads.create_index([("user_id", 1), ("updated_at", -1)])
        db.events.create_index([("user_id", 1), ("start", 1)])
        db.messages.create_index([("thread_id", 1), ("_id", 1)])
        db.files.create_index([("user_id", 1), ("kind", 1), ("name", 1)], unique=True)
        _indexed = True
    return db


def reset_for_tests() -> None:
    global _client, _indexed
    _client, _indexed = None, False


# ---- who is asking? Set per request by app.auth.guard --------------------
current_user: contextvars.ContextVar[dict | None] = contextvars.ContextVar("current_user", default=None)


def user_id() -> str:
    user = current_user.get()
    if not user:
        raise NotSignedIn("Please sign in.")
    return str(user["_id"])
