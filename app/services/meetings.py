"""Meeting notes → summary, decisions and action items (added to your todos)."""
from __future__ import annotations

import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.llm import get_llm
from app.agent.prompt_loader import load_prompt
from app.services import todos

SKIP = {"", "none", "n/a", "na", "-", "nothing", "no action items", "none mentioned", "not mentioned"}


def summarise(notes: str) -> str:
    notes = (notes or "").strip()
    if len(notes) < 20:
        raise ValueError("Those notes are too short to summarise. Paste the full notes or transcript.")
    reply = get_llm(temperature=0.1).invoke([SystemMessage(content=load_prompt("meeting_summary.txt")), HumanMessage(content=notes[:60000])])
    return str(reply.content).strip()


def action_items(summary: str) -> list[str]:
    m = re.search(r"action items\s*:?\s*\n(?:[-=]+\n)?(.*?)(?:\n\s*\n[A-Z][^\n]*\n|$)", summary, flags=re.I | re.S)
    section = m.group(1) if m else ""
    items = []
    for line in section.splitlines():
        line = re.sub(r"^\s*(?:[-•*]|\d+[.)])\s*", "", line).strip()
        if line.lower().strip(" .:-") in SKIP or len(line) < 3:
            continue
        items.append(line[:300])
    return items


def summarise_and_capture(notes: str, add_todos: bool = True) -> dict:
    summary = summarise(notes)
    added, existing = [], []
    if add_todos:
        for item in action_items(summary):
            todo, created = todos.add_todo(item, "medium")
            (added if created else existing).append(todo.title)
    return {"summary": summary, "added": added, "already_listed": existing}
