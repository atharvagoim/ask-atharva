from functools import lru_cache
from pathlib import Path

PROMPTS = Path(__file__).parent / "prompts"


@lru_cache
def load_prompt(name: str) -> str:
    return (PROMPTS / name).read_text(encoding="utf-8")
