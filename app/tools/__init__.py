"""Everything the assistant can do. Each tool returns plain text for the AI to relay.

Errors never crash the chat: they come back as a short explanation.
"""
from __future__ import annotations

import functools
from datetime import datetime
from typing import Callable, Literal

from langchain_core.tools import tool

from app.services import calendar as cal
from app.services import files, meetings, slides, spreadsheets, todos
from app.services.dates import nice_day, parse_day


def friendly(fn: Callable[..., str]) -> Callable[..., str]:
    @functools.wraps(fn)
    def wrapper(*args, **kwargs) -> str:
        try:
            return fn(*args, **kwargs)
        except (todos.TodoError, cal.CalendarError, files.FileError, spreadsheets.SheetError, ValueError) as e:
            return f"Couldn't do that: {e}"
        except Exception as e:  # noqa: BLE001
            return f"Something went wrong ({type(e).__name__}). Please try again."

    return wrapper


# ---- Todos -------------------------------------------------------------
@tool
@friendly
def add_todo(title: str, priority: Literal["low", "medium", "high"] = "medium", due: str = "") -> str:
    """Add a todo. `due` is optional plain words like "friday" or "tomorrow"."""
    todo, created = todos.add_todo(title, priority, due or None)
    if not created:
        return f"“{todo.title}” is already on the list."
    return f"Added: {todos.describe(todo)}"


@tool
@friendly
def list_todos(show: Literal["open", "done", "all"] = "open") -> str:
    """List todos. Use show="open" (default) for what's left to do."""
    items = todos.list_todos(show)
    if not items:
        return {"open": "No open todos — all clear.", "done": "Nothing completed yet.", "all": "The todo list is empty."}[show]
    return "\n".join(f"- {todos.describe(t)}" for t in items[:50])


@tool
@friendly
def complete_todo(title: str) -> str:
    """Mark a todo as done. `title` can be part of the todo's name."""
    todo = todos.find_todo(title)
    todos.update_todo(todo.id, done=True)
    remaining = len(todos.list_todos("open"))
    return f"Done: “{todo.title}”. {remaining} open todo{'s' if remaining != 1 else ''} left."


@tool
@friendly
def update_todo(title: str, new_title: str = "", priority: str = "", due: str = "") -> str:
    """Change a todo's title, priority (low/medium/high) or due date ("none" clears it)."""
    todo = todos.find_todo(title)
    kwargs: dict = {}
    if new_title:
        kwargs["title"] = new_title
    if priority:
        kwargs["priority"] = priority
    if due:
        kwargs["due"] = None if due.strip().lower() in ("none", "no date", "clear") else due
    if not kwargs:
        return "Tell me what to change: the title, priority or due date."
    updated = todos.update_todo(todo.id, **kwargs)
    return f"Updated: {todos.describe(updated)}"


@tool
@friendly
def delete_todo(title: str) -> str:
    """Delete a todo permanently (only after the user confirms)."""
    todo = todos.find_todo(title, include_done=True)
    todos.delete_todo(todo.id)
    return f"Deleted “{todo.title}”."


# ---- Calendar ----------------------------------------------------------
@tool
@friendly
def list_calendar_events(day: str = "today", days: int = 1) -> str:
    """Show calendar events for a day ("today", "tomorrow", "next monday", "2026-10-20"). Use days>1 for a range, e.g. days=7 for the week."""
    d = parse_day(day)
    if d is None:
        return f"I couldn't understand the day “{day}”."
    days = max(1, min(int(days or 1), 31))
    events = cal.events_for_day(d, days)
    label = nice_day(d) if days == 1 else f"{nice_day(d)} + {days - 1} days"
    if not events:
        return f"Nothing on the calendar for {label}."
    if days == 1:
        return f"{label.capitalize()}:\n" + "\n".join(f"- {cal.describe(e)}" for e in events)
    lines, current = [], None
    for e in events:
        day_label = nice_day(datetime.fromisoformat(e["start"]).date())
        if day_label != current:
            lines.append(f"{day_label.capitalize()}:")
            current = day_label
        lines.append(f"- {cal.describe(e)}")
    return "\n".join(lines)


@tool
@friendly
def create_calendar_event(title: str, when: str, duration_minutes: int = 60) -> str:
    """Create a calendar event. `when` is plain words like "tomorrow 3pm" or "friday 10:30am"."""
    e = cal.create_event(title, when, duration_minutes)
    start = datetime.fromisoformat(e["start"])
    return f"Booked “{e['title']}” for {nice_day(start.date())} at {cal.fmt_time(start)} ({duration_minutes} min)."


@tool
@friendly
def move_calendar_event(title: str, when: str, duration_minutes: int = 0) -> str:
    """Move an existing event (found by title) to a new time. duration_minutes=0 keeps its length."""
    e = cal.update_event(title, when, duration_minutes or None)
    if e is None:
        return f"I couldn't find an upcoming event called “{title}”."
    start = datetime.fromisoformat(e["start"])
    return f"Moved “{e['title']}” to {nice_day(start.date())} at {cal.fmt_time(start)}."


@tool
@friendly
def delete_calendar_event(title: str) -> str:
    """Delete an upcoming calendar event by title (only after the user confirms)."""
    e = cal.delete_event(title)
    if e is None:
        return f"I couldn't find an upcoming event called “{title}”."
    return f"Deleted “{e['title']}” ({cal.describe(e)})."


@tool
@friendly
def find_free_time(day: str = "today", duration_minutes: int = 60) -> str:
    """Find free slots between 9 AM and 6 PM on a day, at least `duration_minutes` long."""
    d = parse_day(day)
    if d is None:
        return f"I couldn't understand the day “{day}”."
    slots = cal.free_slots(d, int(duration_minutes or 60))
    if not slots:
        return f"No free {duration_minutes}-minute slots between 9 AM and 6 PM {nice_day(d)}."
    return f"Free {nice_day(d)}:\n" + "\n".join(f"- {cal.fmt_time(s)}–{cal.fmt_time(e)}" for s, e in slots)


# ---- Files, spreadsheets, meetings, slides -------------------------------
@tool
@friendly
def list_files() -> str:
    """List the files the user has uploaded (spreadsheets and notes)."""
    items = files.list_files("uploads")
    if not items:
        return "No files uploaded yet. The user can attach one with the paperclip button or on the Files page."
    return "\n".join(f"- {f['name']}" for f in items[:40])


@tool
@friendly
def analyze_spreadsheet(
    file_name: str,
    analysis: Literal["summary", "missing_values", "top_values", "pivot", "chart", "correlation"] = "summary",
    group_by: str = "",
    value_column: str = "",
) -> str:
    """Analyse an uploaded .xlsx/.csv. analysis: summary, missing_values, top_values, pivot (totals by group), chart (bar chart of totals), correlation. Optional group_by / value_column name the columns to use."""
    result = spreadsheets.analyse(file_name, analysis, group_by or None, value_column or None)
    return result["text"] + "\n\nCreated: " + ", ".join(result["files"])


@tool
@friendly
def summarize_meeting(notes: str, add_action_items_as_todos: bool = True) -> str:
    """Summarise pasted meeting notes or a transcript; action items are added as todos."""
    r = meetings.summarise_and_capture(notes, add_action_items_as_todos)
    tail = ""
    if r["added"]:
        tail += f"\n\nAdded {len(r['added'])} todo(s): " + "; ".join(r["added"])
    if r["already_listed"]:
        tail += "\nAlready on the list: " + "; ".join(r["already_listed"])
    return r["summary"] + tail


@tool
@friendly
def summarize_meeting_file(file_name: str, add_action_items_as_todos: bool = True) -> str:
    """Summarise an uploaded notes/transcript file (.txt, .md, .vtt, .srt)."""
    path = files.find_upload(file_name)
    if path.suffix.lower() not in files.NOTES:
        return f"{path.name} isn't a notes file. Upload a .txt or .md file."
    text = path.read_text(encoding="utf-8", errors="replace")
    return summarize_meeting.func(text, add_action_items_as_todos)  # type: ignore[attr-defined]


@tool
@friendly
def create_presentation(topic: str, slide_count: int = 6, guidance: str = "") -> str:
    """Create a PowerPoint deck about `topic`. Optional `guidance` (audience, tone, points to include)."""
    r = slides.create(topic, slide_count, guidance)
    how = "" if r["by_ai"] else " (a starter outline — the assistant is switched off, so this is generic)"
    return f"Created {r['file']} with {r['slides']} slides{how}: " + ", ".join(r["titles"])


TOOLS = [
    add_todo,
    list_todos,
    complete_todo,
    update_todo,
    delete_todo,
    list_calendar_events,
    create_calendar_event,
    move_calendar_event,
    delete_calendar_event,
    find_free_time,
    list_files,
    analyze_spreadsheet,
    summarize_meeting,
    summarize_meeting_file,
    create_presentation,
]

# Tools that change data the pages show — the UI refreshes when one runs.
CHANGES = {
    "todos": {"add_todo", "complete_todo", "update_todo", "delete_todo", "summarize_meeting", "summarize_meeting_file"},
    "calendar": {"create_calendar_event", "move_calendar_event", "delete_calendar_event"},
    "files": {"analyze_spreadsheet", "create_presentation"},
}

