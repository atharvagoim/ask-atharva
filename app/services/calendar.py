"""The built-in calendar. Events are stored in MongoDB, per account — no Google needed.

Times are saved in UTC and shown in the person's time zone. All-day events run from local
midnight to the next local midnight.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from bson import ObjectId
from bson.errors import InvalidId

from app.config import settings
from app.db import aware, database, now, user_id
from app.services.dates import now_local, parse_when


class CalendarError(RuntimeError):
    pass


def _events():
    return database().events


# ---- conversion -----------------------------------------------------------
def _local(value: datetime) -> datetime:
    return aware(value).astimezone(settings().tz)


def simplify(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "title": doc.get("title") or "(no title)",
        "start": _local(doc["start"]).isoformat(),
        "end": _local(doc["end"]).isoformat(),
        "all_day": bool(doc.get("all_day")),
        "location": doc.get("location", ""),
        "notes": doc.get("notes", ""),
    }


def _day_bounds(d: date, days: int = 1) -> tuple[datetime, datetime]:
    tz = settings().tz
    start = datetime.combine(d, time.min, tz)
    return start, start + timedelta(days=days)


def _oid(event_id: str) -> ObjectId:
    try:
        return ObjectId(str(event_id))
    except (InvalidId, TypeError) as e:
        raise CalendarError("That event doesn't exist any more.") from e


def _when(text: str) -> datetime:
    dt = parse_when(text)
    if dt is None:
        raise CalendarError(f"I couldn't understand the time “{text}”. Try something like “tomorrow 3pm”.")
    return dt


def _utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc)


# ---- operations -----------------------------------------------------------
def list_events(start: datetime, end: datetime) -> list[dict]:
    """Events that overlap [start, end), soonest first."""
    rows = _events().find({"user_id": user_id(), "start": {"$lt": _utc(end)}, "end": {"$gt": _utc(start)}}).sort("start", 1).limit(500)
    return [simplify(d) for d in rows]


def events_for_day(d: date, days: int = 1) -> list[dict]:
    return list_events(*_day_bounds(d, days))


def create_event(
    title: str,
    when: str = "",
    duration_minutes: int = 60,
    *,
    start: datetime | None = None,
    all_day: bool = False,
    location: str = "",
    notes: str = "",
) -> dict:
    """Make an event from plain words (`when`) or from an exact `start` datetime."""
    title = " ".join((title or "").split())[:200] or "New event"
    first = start or _when(when)
    if all_day:
        first = datetime.combine(first.astimezone(settings().tz).date(), time.min, settings().tz)
        last = first + timedelta(days=1)
    else:
        last = first + timedelta(minutes=max(5, min(int(duration_minutes or 60), 24 * 60)))
    doc = {
        "user_id": user_id(),
        "title": title,
        "start": _utc(first),
        "end": _utc(last),
        "all_day": all_day,
        "location": (location or "").strip()[:200],
        "notes": (notes or "").strip()[:2000],
        "created_at": now(),
    }
    doc["_id"] = _events().insert_one(doc).inserted_id
    return simplify(doc)


def get_event(event_id: str) -> dict | None:
    doc = _events().find_one({"_id": _oid(event_id), "user_id": user_id()})
    return simplify(doc) if doc else None


def edit_event(
    event_id: str,
    *,
    title: str | None = None,
    start: datetime | None = None,
    duration_minutes: int | None = None,
    all_day: bool | None = None,
    location: str | None = None,
    notes: str | None = None,
) -> dict:
    doc = _events().find_one({"_id": _oid(event_id), "user_id": user_id()})
    if doc is None:
        raise CalendarError("That event doesn't exist any more.")
    tz = settings().tz
    current_start = aware(doc["start"]).astimezone(tz)
    length = aware(doc["end"]) - aware(doc["start"])
    is_all_day = bool(doc.get("all_day")) if all_day is None else all_day
    first = start.astimezone(tz) if start else current_start
    if is_all_day:
        first = datetime.combine(first.date(), time.min, tz)
        last = first + timedelta(days=1)
    else:
        if duration_minutes:
            length = timedelta(minutes=max(5, min(int(duration_minutes), 24 * 60)))
        elif doc.get("all_day"):  # an all-day event turned into a timed one
            length = timedelta(hours=1)
        last = first + length
    changes: dict = {"start": _utc(first), "end": _utc(last), "all_day": is_all_day}
    if title is not None:
        changes["title"] = " ".join(title.split())[:200] or doc["title"]
    if location is not None:
        changes["location"] = location.strip()[:200]
    if notes is not None:
        changes["notes"] = notes.strip()[:2000]
    _events().update_one({"_id": doc["_id"]}, {"$set": changes})
    doc.update(changes)
    return simplify(doc)


def delete_event_by_id(event_id: str) -> None:
    if _events().delete_one({"_id": _oid(event_id), "user_id": user_id()}).deleted_count == 0:
        raise CalendarError("That event doesn't exist any more.")


def find_event(title: str) -> dict | None:
    """Upcoming (or from yesterday) event whose title matches best."""
    q = (title or "").strip().lower()
    if not q:
        return None
    start = now_local() - timedelta(days=1)
    events = list_events(start, start + timedelta(days=366))
    for e in events:
        if e["title"].lower() == q:
            return e
    for e in events:
        if q in e["title"].lower():
            return e
    return None


def update_event(title: str, when: str, duration_minutes: int | None = None) -> dict | None:
    """Move the event called `title` to a new time (used by the assistant)."""
    event = find_event(title)
    if event is None:
        return None
    return edit_event(event["id"], start=_when(when), duration_minutes=duration_minutes)


def delete_event(title: str) -> dict | None:
    event = find_event(title)
    if event is None:
        return None
    delete_event_by_id(event["id"])
    return event


def free_slots(d: date, duration_minutes: int = 60, day_start: int = 9, day_end: int = 18) -> list[tuple[datetime, datetime]]:
    """Gaps of at least `duration_minutes` between `day_start` and `day_end` (local)."""
    tz = settings().tz
    window_start = datetime.combine(d, time(hour=day_start), tz)
    window_end = datetime.combine(d, time(hour=day_end), tz)
    current = now_local()
    if d == current.date():
        # Don't offer times that have already passed (round up to the next 15 min).
        rounded = (current + timedelta(minutes=15 - current.minute % 15)).replace(second=0, microsecond=0)
        window_start = max(window_start, rounded)
    if window_start >= window_end:
        return []
    busy = []
    for e in list_events(window_start, window_end):
        if e.get("all_day"):
            continue  # birthdays, holidays, "working from home" don't block the day
        s = datetime.fromisoformat(e["start"]).astimezone(tz)
        en = datetime.fromisoformat(e["end"]).astimezone(tz)
        s, en = max(s, window_start), min(en, window_end)
        if en > s:
            busy.append((s, en))
    busy.sort()
    slots, cursor, need = [], window_start, timedelta(minutes=duration_minutes)
    for s, en in busy:
        if s - cursor >= need:
            slots.append((cursor, s))
        cursor = max(cursor, en)
    if window_end - cursor >= need:
        slots.append((cursor, window_end))
    return slots


def fmt_time(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


def describe(e: dict) -> str:
    if e["all_day"]:
        return f"All day: {e['title']}"
    s = datetime.fromisoformat(e["start"])
    en = datetime.fromisoformat(e["end"])
    return f"{fmt_time(s)}–{fmt_time(en)}: {e['title']}"
