"""Todo logic shared by the AI tools and the Todos page."""
from __future__ import annotations

import difflib
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from bson import ObjectId
from bson.errors import InvalidId

from app.db import aware, database, now, user_id
from app.services.dates import nice_day, now_local, parse_day

PRIORITIES = ("low", "medium", "high")
_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


class TodoError(ValueError):
    pass


@dataclass
class Todo:
    id: str
    title: str
    priority: str
    due: date | None
    done: bool
    created_at: datetime
    completed_at: datetime | None

    @classmethod
    def from_doc(cls, d: dict) -> "Todo":
        due = d.get("due")
        return cls(
            id=str(d["_id"]),
            title=d["title"],
            priority=d.get("priority", "medium"),
            due=date.fromisoformat(due) if due else None,
            done=bool(d.get("done")),
            created_at=aware(d.get("created_at")) or now(),
            completed_at=aware(d.get("completed_at")),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "priority": self.priority,
            "due": self.due.isoformat() if self.due else None,
            "done": self.done,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


def _todos():
    return database().todos


def _oid(todo_id: str) -> ObjectId:
    try:
        return ObjectId(str(todo_id))
    except (InvalidId, TypeError) as e:
        raise TodoError("That todo doesn't exist any more.") from e


def normalise_priority(value: str | None) -> str:
    v = (value or "medium").strip().lower()
    aliases = {"urgent": "high", "important": "high", "normal": "medium", "med": "medium", "minor": "low"}
    v = aliases.get(v, v)
    return v if v in PRIORITIES else "medium"


def parse_due(value: str | date | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    d = parse_day(str(value))
    if d is None:
        raise TodoError(f"I couldn't understand the date “{value}”.")
    return d


def list_todos(show: str = "open") -> list[Todo]:
    query: dict = {"user_id": user_id()}
    if show == "open":
        query["done"] = False
    elif show == "done":
        query["done"] = True
    rows = [Todo.from_doc(d) for d in _todos().find(query)]
    if show == "done":
        return sorted(rows, key=lambda t: t.completed_at or t.created_at, reverse=True)
    far = date.max
    return sorted(rows, key=lambda t: (t.done, t.due or far, _PRIORITY_ORDER.get(t.priority, 1), t.created_at))


def add_todo(title: str, priority: str | None = None, due: str | date | None = None) -> tuple[Todo, bool]:
    """Returns (todo, created). Re-adding an open todo with the same title is a no-op."""
    title = " ".join((title or "").split())
    if not title:
        raise TodoError("A todo needs a title.")
    if len(title) > 300:
        title = title[:300]
    for t in list_todos("open"):
        if t.title.lower() == title.lower():
            return t, False
    when = parse_due(due)
    doc = {
        "user_id": user_id(),
        "title": title,
        "priority": normalise_priority(priority),
        "due": when.isoformat() if when else None,
        "done": False,
        "created_at": now(),
        "completed_at": None,
    }
    doc["_id"] = _todos().insert_one(doc).inserted_id
    return Todo.from_doc(doc), True


def find_todo(query: str, include_done: bool = False) -> Todo:
    """Find one todo by (part of) its title. Raises TodoError with options if unclear."""
    q = " ".join((query or "").split()).lower()
    if not q:
        raise TodoError("Tell me which todo you mean.")
    todos = list_todos("all" if include_done else "open")
    for t in todos:  # the id itself also works
        if t.id == q:
            return t
    exact = [t for t in todos if t.title.lower() == q]
    if exact:
        return exact[0]
    partial = [t for t in todos if q in t.title.lower()]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        names = "; ".join(f"“{t.title}”" for t in partial[:5])
        raise TodoError(f"More than one todo matches “{query}”: {names}. Which one?")
    close = difflib.get_close_matches(q, [t.title.lower() for t in todos], n=1, cutoff=0.6)
    if close:
        return next(t for t in todos if t.title.lower() == close[0])
    raise TodoError(f"I couldn't find an open todo matching “{query}”.")


def update_todo(todo_id: str, *, title: str | None = None, priority: str | None = None, due: str | date | None | bool = False, done: bool | None = None) -> Todo:
    """due=False means 'leave unchanged'; due=None/'' clears it."""
    doc = _todos().find_one({"_id": _oid(todo_id), "user_id": user_id()})
    if doc is None:
        raise TodoError("That todo doesn't exist any more.")
    changes: dict = {}
    if title is not None:
        clean = " ".join(title.split())
        if not clean:
            raise TodoError("A todo needs a title.")
        changes["title"] = clean[:300]
    if priority is not None:
        changes["priority"] = normalise_priority(priority)
    if due is not False:
        when = parse_due(due)  # type: ignore[arg-type]
        changes["due"] = when.isoformat() if when else None
    if done is not None and done != bool(doc.get("done")):
        changes["done"] = done
        changes["completed_at"] = now() if done else None
    if changes:
        _todos().update_one({"_id": doc["_id"]}, {"$set": changes})
        doc.update(changes)
    return Todo.from_doc(doc)


def delete_todo(todo_id: str) -> None:
    if _todos().delete_one({"_id": _oid(todo_id), "user_id": user_id()}).deleted_count == 0:
        raise TodoError("That todo doesn't exist any more.")


def describe(t: Todo) -> str:
    bits = [t.title]
    extras = []
    if t.priority != "medium":
        extras.append(f"{t.priority} priority")
    if t.due:
        overdue = not t.done and t.due < now_local().date()
        extras.append(("overdue, was due " if overdue else "due ") + nice_day(t.due))
    if extras:
        bits.append(f"({', '.join(extras)})")
    if t.done:
        bits.append("✓ done")
    return " ".join(bits)


def stats() -> dict:
    """Totals and a seven-day history of completed tasks, for the progress cards."""
    from app.config import settings

    items = list_todos("all")
    today = now_local().date()
    tz = settings().tz
    done = [t for t in items if t.done]
    open_items = [t for t in items if not t.done]
    last7 = []
    for back in range(6, -1, -1):
        day = today - timedelta(days=back)
        n = sum(1 for t in done if t.completed_at and t.completed_at.astimezone(tz).date() == day)
        last7.append({"date": day.isoformat(), "done": n})
    total = len(items)
    return {
        "total": total,
        "done": len(done),
        "open": len(open_items),
        "overdue": sum(1 for t in open_items if t.due and t.due < today),
        "due_today": sum(1 for t in open_items if t.due == today),
        "high_open": sum(1 for t in open_items if t.priority == "high"),
        "percent": round(100 * len(done) / total) if total else 0,
        "last7": last7,
    }
