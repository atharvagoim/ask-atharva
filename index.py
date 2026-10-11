"""Vercel entry point: Vercel looks for an `app` object in a root-level index.py.

The real application lives in app/main.py; this file makes sure the project folder is
importable (so `import app...` works the same on Vercel as on your computer) and re-exports it.
If the app can't start, it prints the full error to the logs and serves a small error page
instead of a blank "FUNCTION_INVOCATION_FAILED". Set DEBUG_BOOT=1 to show the error on the page.
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from app.main import app  # noqa: F401
except Exception:  # noqa: BLE001
    BOOT_ERROR = traceback.format_exc()
    print("APP FAILED TO START:\n" + BOOT_ERROR, flush=True)

    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse

    app = FastAPI()

    @app.get("/{path:path}", include_in_schema=False)
    def failed(path: str = ""):
        body = BOOT_ERROR if os.getenv("DEBUG_BOOT") else "The app failed to start. Open the deployment logs in Vercel for the error."
        return PlainTextResponse(body, status_code=500)
