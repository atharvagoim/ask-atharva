"""Start Ask Atharva: `python run.py` — then it opens in your browser."""
from __future__ import annotations

import os
import shutil
import socket
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent

if sys.version_info < (3, 11):
    sys.exit("Ask Atharva needs Python 3.11 or newer. You have " + sys.version.split()[0] + ".")

# First run: create .env from the example so Settings has somewhere to save.
env_file, example = ROOT / ".env", ROOT / ".env.example"
if not env_file.exists() and example.exists():
    shutil.copy(example, env_file)

try:
    import uvicorn  # noqa: F401
    import fastapi  # noqa: F401
    import langgraph  # noqa: F401
except ImportError as e:
    sys.exit(
        f"A required package is missing ({e.name}).\n"
        "Install everything with:\n\n    pip install -r requirements.txt\n\n"
        "(or, if you use uv:  uv sync  then  uv run python run.py)"
    )

from dotenv import load_dotenv  # noqa: E402

load_dotenv(env_file)
host = os.getenv("HOST", "127.0.0.1") or "127.0.0.1"
port = int(os.getenv("PORT", "8000") or 8000)


def port_free(p: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", p)) != 0


if not port_free(port):
    for candidate in range(port + 1, port + 20):
        if port_free(candidate):
            print(f"Port {port} is busy, using {candidate} instead.")
            port = candidate
            break

url = f"http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}"
print(f"\n  Ask Atharva is starting at {url}\n  Press Ctrl+C to stop.\n")

if os.getenv("NO_BROWSER", "").lower() not in ("1", "true", "yes"):
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()

import uvicorn  # noqa: E402

uvicorn.run("app.main:app", host=host, port=port, log_level="warning")
