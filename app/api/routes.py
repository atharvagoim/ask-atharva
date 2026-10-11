"""JSON API used by the web interface. Errors are always {"detail": "<plain sentence>"}."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app.agent import chat as chat_service
from app.agent.llm import NoAIKeyError, friendly_ai_error, get_llm, has_ai
from app.config import save_settings, settings
from app.db import current_user
from app.services import calendar as cal
from app.services import chats, files, profile, todos
from app.services.dates import now_local, parse_day

router = APIRouter(prefix="/api")


def fail(status: int, message: str):
    raise HTTPException(status_code=status, detail=message)


# ---- Status & settings -------------------------------------------------
@router.get("/status")
def status():
    s = settings()
    return {
        "name": s.user_name,
        "timezone": s.timezone,
        "ai": {"ready": has_ai()},
        "now": now_local().isoformat(),
        "photo": profile.photo_url(current_user.get()),
        "email": (current_user.get() or {}).get("email", ""),
        "auth": True,
        "max_upload_mb": files.MAX_UPLOAD_MB,
    }


class SettingsIn(BaseModel):
    name: str | None = Field(default=None, max_length=40)


@router.put("/settings")
def update_settings(body: SettingsIn):
    updates: dict[str, str] = {}
    if body.name is not None:
        if not body.name.strip():
            fail(400, "Enter a name.")
        updates["USER_NAME"] = body.name.strip()
    save_settings(updates)
    return status()


# ---- Profile photo -----------------------------------------------------
@router.post("/profile/photo")
async def upload_photo(file: UploadFile = File(...)):
    raw = await file.read(profile.MAX_PHOTO_BYTES + 1)
    try:
        profile.save_photo(raw)
    except profile.PhotoError as e:
        fail(400, str(e))
    return status()


@router.get("/profile/photo")
def get_photo():
    data = profile.get_photo()
    if data is None:
        fail(404, "No profile photo yet.")
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@router.delete("/profile/photo")
def remove_photo():
    profile.delete_photo()
    return status()


# ---- Chat --------------------------------------------------------------
class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    thread_id: str | None = None


@router.post("/chat")
def chat(body: ChatIn):
    if not body.message.strip():
        fail(400, "Type a message first.")
    try:
        return chat_service.run_chat(body.message, body.thread_id)
    except NoAIKeyError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        fail(502, friendly_ai_error(e))


@router.get("/threads")
def threads():
    return chats.list_threads()


@router.get("/threads/{thread_id}")
def thread_messages(thread_id: str):
    try:
        return chats.get_thread(thread_id)
    except chats.ThreadNotFound as e:
        fail(404, str(e))


@router.delete("/threads/{thread_id}")
def delete_thread(thread_id: str):
    chats.delete_thread(thread_id)
    return {"ok": True}


# ---- Todos -------------------------------------------------------------
class TodoIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    priority: str = "medium"
    due: str | None = None


class TodoPatch(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    priority: str | None = None
    due: str | None = "__keep__"
    done: bool | None = None


@router.get("/todos/stats")
def todo_stats():
    return todos.stats()


@router.get("/todos")
def get_todos(show: str = "open"):
    if show not in ("open", "done", "all"):
        show = "open"
    return [t.to_dict() for t in todos.list_todos(show)]


@router.post("/todos", status_code=201)
def create_todo(body: TodoIn):
    try:
        todo, created = todos.add_todo(body.title, body.priority, body.due or None)
    except todos.TodoError as e:
        fail(400, str(e))
    return {**todo.to_dict(), "created": created}


@router.patch("/todos/{todo_id}")
def patch_todo(todo_id: str, body: TodoPatch):
    try:
        due = False if body.due == "__keep__" else (body.due or None)
        return todos.update_todo(todo_id, title=body.title, priority=body.priority, due=due, done=body.done).to_dict()
    except todos.TodoError as e:
        fail(404 if "exist" in str(e) else 400, str(e))


@router.delete("/todos/{todo_id}")
def remove_todo(todo_id: str):
    try:
        todos.delete_todo(todo_id)
    except todos.TodoError as e:
        fail(404, str(e))
    return {"ok": True}


# ---- Calendar ----------------------------------------------------------
def _calendar_call(fn):
    try:
        return fn()
    except cal.CalendarError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/calendar/events")
def calendar_events(day: str = "today", days: int = 7):
    d = parse_day(day) or now_local().date()
    days = max(1, min(days, 62))
    return {"from": d.isoformat(), "days": days, "events": _calendar_call(lambda: cal.events_for_day(d, days))}


class EventIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    when: str | None = Field(default=None, max_length=100)  # plain words: "tomorrow 3pm"
    date: str | None = None  # or an exact date (YYYY-MM-DD) ...
    time: str | None = None  # ... and time (HH:MM)
    duration_minutes: int = Field(default=60, ge=5, le=1440)
    all_day: bool = False
    location: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=2000)


class EventPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    date: str | None = None
    time: str | None = None
    duration_minutes: int | None = Field(default=None, ge=5, le=1440)
    all_day: bool | None = None
    location: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)


def _exact_start(date_text: str | None, time_text: str | None):
    """A timezone-aware datetime from a date and optional HH:MM, or None if no date was given."""
    if not date_text:
        return None
    try:
        day = datetime.fromisoformat(date_text).date()
        hh, mm = (time_text or "09:00").split(":")[:2]
        return datetime(day.year, day.month, day.day, int(hh), int(mm), tzinfo=settings().tz)
    except ValueError:
        fail(400, "That date or time doesn't look right.")


@router.post("/calendar/events", status_code=201)
def calendar_create(body: EventIn):
    start = _exact_start(body.date, body.time)
    if start is None and not (body.when or "").strip():
        fail(400, "Pick a date, or say when, like “tomorrow 3pm”.")
    return _calendar_call(
        lambda: cal.create_event(body.title, body.when or "", body.duration_minutes, start=start, all_day=body.all_day, location=body.location, notes=body.notes)
    )


@router.patch("/calendar/events/{event_id}")
def calendar_edit(event_id: str, body: EventPatch):
    start = _exact_start(body.date, body.time)
    if start is None and body.time:  # time changed, keep the day
        current = cal.get_event(event_id)
        if current is None:
            fail(404, "That event doesn't exist any more.")
        start = _exact_start(current["start"][:10], body.time)
    return _calendar_call(
        lambda: cal.edit_event(event_id, title=body.title, start=start, duration_minutes=body.duration_minutes, all_day=body.all_day, location=body.location, notes=body.notes)
    )


@router.delete("/calendar/events/{event_id}")
def calendar_delete(event_id: str):
    _calendar_call(lambda: cal.delete_event_by_id(event_id))
    return {"ok": True}


# ---- Files -------------------------------------------------------------
@router.get("/files")
def list_all_files():
    return {"uploads": files.list_files("uploads"), "outputs": files.list_files("outputs")}


@router.post("/files", status_code=201)
async def upload(file: UploadFile = File(...)):
    data = await file.read(files.MAX_UPLOAD_BYTES + 1)
    try:
        path = files.save_upload(file.filename or "upload", data)
    except files.FileError as e:
        fail(400, str(e))
    return files.describe(path, "uploads")


@router.get("/files/{kind}/{name}")
def download(kind: str, name: str):
    try:
        path = files.resolve(kind, name)
    except files.FileError as e:
        fail(404, str(e))
    return FileResponse(path, filename=path.name)


@router.delete("/files/{kind}/{name}")
def remove_file(kind: str, name: str):
    try:
        files.delete_file(kind, name)
    except files.FileError as e:
        fail(404, str(e))
    return {"ok": True}


# ---- Today -------------------------------------------------------------
@router.get("/today")
def today():
    today_d = now_local().date()
    open_todos = todos.list_todos("open")
    due = [t.to_dict() for t in open_todos if t.due and t.due <= today_d]
    upcoming = [t.to_dict() for t in open_todos if not (t.due and t.due <= today_d)][:6]
    events = cal.events_for_day(today_d, 1)
    done_today = sum(
        1 for t in todos.list_todos("done") if t.completed_at and t.completed_at.astimezone(settings().tz).date() == today_d
    )
    return {
        "date": today_d.isoformat(),
        "due": due,
        "upcoming": upcoming,
        "open_count": len(open_todos),
        "done_today": done_today,
        "events": events,
    }


