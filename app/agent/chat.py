"""The conversation loop: LangGraph assistant ⇄ tools, with memory per chat thread."""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from app.agent.llm import get_llm
from app.agent.prompt_loader import load_prompt
from app.config import settings
from app.services import chats, files
from app.services.dates import now_local
from app.tools import CHANGES, TOOLS

HISTORY_TURNS = 20  # messages of earlier conversation sent back to the AI


def _system_prompt() -> str:
    s = settings()
    stamp = now_local().strftime("%A %d %B %Y, %I:%M %p")
    return load_prompt("system.txt").replace("{name}", s.user_name).replace("{now}", stamp).replace("{timezone}", s.timezone)


def build_graph():
    llm = get_llm().bind_tools(TOOLS)
    system = SystemMessage(content=_system_prompt())

    def assistant(state: MessagesState):
        return {"messages": [llm.invoke([system, *state["messages"]])]}

    g = StateGraph(MessagesState)
    g.add_node("assistant", assistant)
    g.add_node("tools", ToolNode(TOOLS, handle_tool_errors=True))
    g.add_edge(START, "assistant")
    g.add_conditional_edges("assistant", tools_condition)
    g.add_edge("tools", "assistant")
    return g.compile()


def _history(thread_id: str) -> list:
    out = []
    for m in chats.history(thread_id, HISTORY_TURNS):
        if m["role"] == "user":
            out.append(HumanMessage(content=m["content"]))
        else:
            note = f"\n(Files I created: {', '.join(f['name'] for f in m['files'])})" if m["files"] else ""
            out.append(AIMessage(content=m["content"] + note))
    return out


def run_chat(message: str, thread_id: str | None = None) -> dict:
    """Runs one user turn. Raises NoAIKeyError / provider errors for the API layer to explain."""
    message = message.strip()
    graph = build_graph()  # rebuilt each turn so new Settings apply immediately
    thread_id = chats.get_or_create_thread(thread_id, message)
    history = _history(thread_id)
    before = files.snapshot_outputs()

    try:
        result = graph.invoke({"messages": [*history, HumanMessage(content=message)]}, config={"recursion_limit": 16})
    except Exception:
        if not history:  # don't leave an empty chat behind
            chats.delete_thread(thread_id)
        raise

    new_messages = result["messages"][len(history) + 1 :]
    used = [tc["name"] for m in new_messages if isinstance(m, AIMessage) for tc in (m.tool_calls or [])]
    reply = ""
    for m in reversed(new_messages):
        if isinstance(m, AIMessage) and not m.tool_calls and str(m.content).strip():
            reply = str(m.content).strip()
            break
    if not reply:
        tool_texts = [str(m.content) for m in new_messages if isinstance(m, ToolMessage)]
        reply = tool_texts[-1] if tool_texts else "Done."

    created = files.new_outputs_since(before)
    chats.save_message(thread_id, "user", message)
    saved = chats.save_message(thread_id, "assistant", reply, created)
    refresh = sorted({area for area, names in CHANGES.items() if set(used) & names})
    return {"thread_id": thread_id, "message": saved, "tools_used": used, "refresh": refresh}
