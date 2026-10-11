"""The whole app: JSON API under /api and the web interface at /."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import auth
from app.api.routes import router

WEB = Path(__file__).parent / "web"

app = FastAPI(title="Ask Atharva", version="2.0.0", docs_url="/api/docs", redoc_url=None)
app.include_router(auth.router)
app.include_router(router)


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(p) for p in first.get("loc", [])[1:])
    msg = first.get("msg", "Please check what you entered.")
    return JSONResponse(status_code=400, content={"detail": f"{field}: {msg}" if field else msg})


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    if not request.url.path.startswith("/api/files/"):
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


app.middleware("http")(auth.guard)
app.mount("/assets", StaticFiles(directory=WEB), name="assets")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB / "index.html")
