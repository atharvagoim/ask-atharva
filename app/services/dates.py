"""Natural-language dates in the user's time zone ("tomorrow 3pm", "next friday")."""
from __future__ import annotations

from datetime import date, datetime

import dateparser

from app.config import settings


def now_local() -> datetime:
    return datetime.now(settings().tz)


def parse_when(text: str, prefer_future: bool = True) -> datetime | None:
    text = (text or "").strip()
    if not text:
        return None
    s = settings()
    dt = dateparser.parse(
        text,
        settings={
            "TIMEZONE": s.timezone,
            "TO_TIMEZONE": s.timezone,
            "RETURN_AS_TIMEZONE_AWARE": True,
            "PREFER_DATES_FROM": "future" if prefer_future else "current_period",
            "RELATIVE_BASE": now_local().replace(tzinfo=None),
        },
    )
    return dt.astimezone(s.tz) if dt else None


def parse_day(text: str) -> date | None:
    """A calendar day from text like 'today', 'friday', '2026-10-20'."""
    lowered = (text or "").strip().lower()
    if lowered in ("", "today", "now"):
        return now_local().date()
    try:
        return date.fromisoformat(lowered)
    except ValueError:
        pass
    dt = parse_when(text)
    return dt.date() if dt else None


def nice_day(d: date) -> str:
    today = now_local().date()
    delta = (d - today).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    if delta == -1:
        return "yesterday"
    return d.strftime("%a %d %b").replace(" 0", " ")
