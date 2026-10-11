"""Chat threads and their messages, stored per signed-in user."""
from __future__ import annotations

import uuid

from app.db import aware, database, now, user_id


class ThreadNotFound(LookupError):
    pass


def _message_dict(m: dict) -> dict:
    return {
        "id": str(m["_id"]),
        "role": m["role"],
        "content": m["content"],
        "files": m.get("files", []),
        "created_at": aware(m["created_at"]).isoformat() if m.get("created_at") else None,
    }


def list_threads(limit: int = 50) -> list[dict]:
    rows = database().threads.find({"user_id": user_id()}).sort("updated_at", -1).limit(limit)
    return [{"id": t["_id"], "title": t["title"], "updated_at": aware(t["updated_at"]).isoformat()} for t in rows]


def _owned(thread_id: str) -> dict | None:
    return database().threads.find_one({"_id": thread_id, "user_id": user_id()}) if thread_id else None


def get_thread(thread_id: str) -> dict:
    thread = _owned(thread_id)
    if thread is None:
        raise ThreadNotFound("That conversation doesn't exist any more.")
    msgs = database().messages.find({"thread_id": thread_id}).sort("_id", 1)
    return {"id": thread["_id"], "title": thread["title"], "messages": [_message_dict(m) for m in msgs]}


def delete_thread(thread_id: str) -> None:
    if _owned(thread_id) is not None:
        database().messages.delete_many({"thread_id": thread_id})
        database().threads.delete_one({"_id": thread_id, "user_id": user_id()})


def get_or_create_thread(thread_id: str | None, first_message: str) -> str:
    thread = _owned(thread_id) if thread_id else None
    if thread is not None:
        return thread["_id"]
    title = " ".join(first_message.split())[:60] or "New chat"
    new_id = str(uuid.uuid4())
    database().threads.insert_one({"_id": new_id, "user_id": user_id(), "title": title, "created_at": now(), "updated_at": now()})
    return new_id


def history(thread_id: str, limit: int) -> list[dict]:
    """The most recent `limit` messages, oldest first."""
    if _owned(thread_id) is None:
        return []
    rows = list(database().messages.find({"thread_id": thread_id}).sort("_id", -1).limit(limit))
    return [_message_dict(m) for m in reversed(rows)]


def save_message(thread_id: str, role: str, content: str, files: list[dict] | None = None) -> dict:
    doc = {"thread_id": thread_id, "user_id": user_id(), "role": role, "content": content, "files": files or [], "created_at": now()}
    doc["_id"] = database().messages.insert_one(doc).inserted_id
    database().threads.update_one({"_id": thread_id, "user_id": user_id()}, {"$set": {"updated_at": now()}})
    return _message_dict(doc)
