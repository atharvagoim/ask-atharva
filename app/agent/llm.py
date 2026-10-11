"""Picks the AI model from the server's configuration: Groq first, then OpenAI."""
from __future__ import annotations

from typing import Any

from app.config import settings


class NoAIKeyError(RuntimeError):
    """Raised when no AI key is configured yet."""


_override: Any = None


def set_llm_override(llm: Any) -> None:
    """Tests use this to plug in a fake model."""
    global _override
    _override = llm


def has_ai() -> bool:
    return _override is not None or settings().ai_provider is not None


def get_llm(temperature: float = 0.2):
    if _override is not None:
        return _override
    s = settings()
    if s.groq_api_key:
        from langchain_groq import ChatGroq

        return ChatGroq(model=s.model or "openai/gpt-oss-120b", api_key=s.groq_api_key, temperature=temperature, max_retries=1, timeout=60)
    if s.openai_api_key:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=s.model or "gpt-4o-mini", api_key=s.openai_api_key, temperature=temperature, max_retries=1, timeout=60)
    raise NoAIKeyError("Chat isn't switched on yet. The app owner needs to add an AI key.")


def friendly_ai_error(err: Exception) -> str:
    """Turns provider errors into one plain sentence."""
    text = f"{type(err).__name__}: {err}".lower()
    if isinstance(err, NoAIKeyError):
        return str(err)
    if "401" in text or "invalid api key" in text or "authentication" in text or "invalid_api_key" in text:
        return "The assistant's AI key was rejected. The app owner needs to check it — it may have a typo or have been revoked."
    if "429" in text or "rate limit" in text or "rate_limit" in text:
        return "The AI service is busy (rate limit reached). Wait a minute and try again."
    if "model" in text and ("not found" in text or "does not exist" in text or "decommissioned" in text):
        return "The configured AI model isn't available any more. The app owner needs to update the MODEL setting."
    if "connect" in text or "timeout" in text or "timed out" in text or "network" in text:
        return "Couldn't reach the AI service. Check your internet connection and try again."
    if "recursion" in text:
        return "That took too many steps. Try asking in a simpler way, or one thing at a time."
    return "Something went wrong while thinking about that. Please try again."
