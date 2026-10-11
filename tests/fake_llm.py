"""A stand-in chat model for tests: picks tools by keywords like a real model would."""
from __future__ import annotations

import json
import re
import uuid

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage


class FakeLLM:
    def __init__(self):
        self.calls = 0

    def bind_tools(self, _tools):
        return self

    def _call(self, name, **args):
        return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{uuid.uuid4().hex[:8]}", "type": "tool_call"}])

    def invoke(self, messages, *_, **__):
        self.calls += 1
        if isinstance(messages, str):
            return AIMessage(content="ready")
        system = next((m.content for m in messages if isinstance(m, SystemMessage)), "")
        last = messages[-1]
        if "presentation slides" in system:
            return AIMessage(content=json.dumps([{"title": f"Point {i}", "bullets": ["Concrete idea one", "Concrete idea two", "Concrete idea three"]} for i in range(1, 5)]))
        if "meeting notes or a transcript into a clear summary" in system:
            return AIMessage(content="Summary\n-------\nThe team agreed on the launch plan.\n\nDecisions\n---------\n- Launch on Monday\n\nAction Items\n------------\n- Send launch email to customers — Riya\n- Update the pricing page\n")
        if isinstance(last, ToolMessage):
            return AIMessage(content=f"Here you go:\n{last.content}")
        text = str(last.content).lower()
        names = [str(m.content).lower() for m in messages if isinstance(m, HumanMessage)]
        if text.startswith("add "):
            m = re.match(r"add (?:a todo to )?(.+?)(?: by (\w+))?$", text)
            return self._call("add_todo", title=m.group(1), priority="high" if "urgent" in text else "medium", due=m.group(2) or "")
        if "what's left" in text or "my todos" in text:
            return self._call("list_todos", show="open")
        if text.startswith("done with "):
            return self._call("complete_todo", title=text[len("done with "):])
        if "calendar" in text:
            return self._call("list_calendar_events", day="today")
        if "analyse" in text or "analyze" in text:
            kind = "chart" if "chart" in text else "summary"
            return self._call("analyze_spreadsheet", file_name="sales", analysis=kind)
        if "slides" in text or "presentation" in text:
            return self._call("create_presentation", topic="Calm productivity", slide_count=4)
        if "summarise" in text and "notes" in text:
            return self._call("summarize_meeting_file", file_name="standup")
        if "what did i just ask" in text:
            return AIMessage(content=f"You asked: {names[-2] if len(names) > 1 else 'nothing yet'}")
        return AIMessage(content="Hello! How can I help?")
