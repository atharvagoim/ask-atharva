"""Configuration.

Server-wide values (database address, secrets, default AI key) come from the environment / .env.
Each person's own settings (name) is saved on their account in MongoDB. The AI key and model are
server-wide and come from the environment, so people never see or handle them.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
ON_VERCEL = bool(os.getenv("VERCEL"))
# Scratch space for building slides and charts. On Vercel only /tmp is writable, and it is
# wiped between requests, so everything that matters is stored in MongoDB.
DATA_DIR = Path(os.getenv("ATHARVA_DATA_DIR") or ("/tmp/atharva" if ON_VERCEL else ROOT / "data"))
UPLOADS_DIR = DATA_DIR / "uploads"
OUTPUTS_DIR = DATA_DIR / "outputs"

for d in (DATA_DIR, UPLOADS_DIR, OUTPUTS_DIR):
    d.mkdir(parents=True, exist_ok=True)

load_dotenv(ENV_FILE)
os.environ.setdefault("MPLCONFIGDIR", str(DATA_DIR / "mpl"))  # matplotlib needs a writable cache folder

# Keys a person can change from the Settings page. The AI key and model are server-only.
EDITABLE_KEYS = {"USER_NAME"}
TIMEZONE = "Asia/Kolkata"  # fixed: everyone sees India Standard Time (IST)


@dataclass(frozen=True)
class Settings:
    user_name: str
    timezone: str
    groq_api_key: str
    openai_api_key: str
    model: str
    host: str
    port: int

    @property
    def tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            return ZoneInfo("Asia/Kolkata")

    @property
    def ai_provider(self) -> str | None:
        if self.groq_api_key:
            return "groq"
        if self.openai_api_key:
            return "openai"
        return None


def _mine() -> dict:
    """The signed-in person's saved settings (empty if nobody is signed in)."""
    from app.db import current_user

    user = current_user.get()
    return (user or {}).get("settings", {}) or {}


def settings() -> Settings:
    """Read fresh every time, so Settings-page changes apply immediately."""
    try:
        port = int(os.getenv("PORT", "8000"))
    except ValueError:
        port = 8000
    mine = _mine()

    def get(key: str, default: str = "") -> str:
        return str(mine[key] if key in mine and key in EDITABLE_KEYS else os.getenv(key, default)).strip()

    return Settings(
        user_name=get("USER_NAME", "Atharva") or "Atharva",
        timezone=TIMEZONE,
        groq_api_key=get("GROQ_API_KEY"),
        openai_api_key=get("OPENAI_API_KEY"),
        model=get("MODEL"),
        host=os.getenv("HOST", "127.0.0.1").strip() or "127.0.0.1",
        port=port,
    )


def save_settings(updates: dict[str, str]) -> None:
    """Save the signed-in person's settings on their account."""
    from app.db import current_user, database

    updates = {k: v.strip() for k, v in updates.items() if k in EDITABLE_KEYS}
    user = current_user.get()
    if not updates or not user:
        return
    database().users.update_one({"_id": user["_id"]}, {"$set": {f"settings.{k}": v for k, v in updates.items()}})
    user.setdefault("settings", {}).update(updates)  # visible to the rest of this request
