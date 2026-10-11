"""Accounts: sign up with an email and password, then sign in. Each account has its own data.

Passwords are stored as salted scrypt hashes. A signed cookie keeps you signed in for 30 days.
Set SECRET_KEY to sign cookies with your own secret (otherwise one is generated and kept in
the database). Set ALLOW_SIGNUP=false once your accounts exist to stop new people joining.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import re
import secrets
import time

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from app import db as store
from app.db import current_user, database, now

COOKIE = "atharva_session"
MAX_AGE = 30 * 24 * 3600
OPEN_PATHS = {"/login", "/api/login", "/api/signup"}
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

router = APIRouter()


# ---- passwords ------------------------------------------------------------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        probe = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(probe.hex(), digest)
    except (ValueError, TypeError):
        return False


# ---- signed session cookie -------------------------------------------------
def _secret() -> bytes:
    env = os.getenv("SECRET_KEY")
    if env:
        return env.encode()
    meta = database().meta
    doc = meta.find_one({"_id": "secret"})
    if doc is None:
        try:
            meta.insert_one({"_id": "secret", "value": secrets.token_hex(32)})
        except DuplicateKeyError:
            pass
        doc = meta.find_one({"_id": "secret"})
    return doc["value"].encode()


def _sign(payload: str) -> str:
    return hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()


def make_token(user_id: str) -> str:
    payload = f"{user_id}.{int(time.time()) + MAX_AGE}"
    return f"{payload}.{_sign(payload)}"


def user_from_token(token: str | None) -> dict | None:
    if not token or token.count(".") != 2:
        return None
    uid, expiry, sig = token.split(".")
    try:
        if int(expiry) <= time.time() or not hmac.compare_digest(sig, _sign(f"{uid}.{expiry}")):
            return None
        return database().users.find_one({"_id": ObjectId(uid)})
    except (ValueError, InvalidId):
        return None


def signups_open() -> bool:
    if os.getenv("ALLOW_SIGNUP", "true").strip().lower() not in ("0", "false", "no", "off"):
        return True
    return database().users.estimated_document_count() == 0  # the very first account is always allowed


# ---- middleware ------------------------------------------------------------
async def guard(request: Request, call_next):
    """Let signed-in people through (and remember who), send everyone else to /login."""
    path = request.url.path
    if not store.configured():
        return _setup_needed(request)
    try:
        user = user_from_token(request.cookies.get(COOKIE))
    except store.DatabaseNotConfigured:
        return _setup_needed(request)
    except Exception as e:  # noqa: BLE001 — usually the database being unreachable
        print(f"Database error: {e}")
        return _setup_needed(request, unreachable=True)
    if user is None and path not in OPEN_PATHS:
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Please sign in."}, status_code=401)
        return RedirectResponse("/login")
    token = current_user.set(user)
    try:
        return await call_next(request)
    finally:
        current_user.reset(token)


def _setup_needed(request: Request, unreachable: bool = False):
    msg = (
        "I can't reach the database. Check that MONGODB_URI is right and that your MongoDB Atlas network access allows this server (0.0.0.0/0 for Vercel)."
        if unreachable
        else "Add MONGODB_URI (your MongoDB connection string) to .env locally, or to Vercel's environment variables, then restart or redeploy."
    )
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": msg}, status_code=503)
    return HTMLResponse(SETUP_PAGE.replace("{msg}", msg), status_code=503)


# ---- endpoints -------------------------------------------------------------
class SignupIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)


class LoginIn(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)


def _start_session(request: Request, user_id: str) -> JSONResponse:
    secure = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0] == "https"
    res = JSONResponse({"ok": True})
    res.set_cookie(COOKIE, make_token(user_id), max_age=MAX_AGE, httponly=True, samesite="lax", secure=secure, path="/")
    return res


@router.post("/api/signup")
async def signup(body: SignupIn, request: Request):
    email = body.email.strip().lower()
    if not signups_open():
        return JSONResponse({"detail": "Sign-ups are closed on this app."}, status_code=403)
    if not body.name.strip():
        return JSONResponse({"detail": "Enter your name."}, status_code=400)
    if not EMAIL.match(email):
        return JSONResponse({"detail": "That email doesn't look right."}, status_code=400)
    if len(body.password) < 8:
        return JSONResponse({"detail": "Use at least 8 characters for your password."}, status_code=400)
    doc = {
        "email": email,
        "password_hash": await asyncio.to_thread(hash_password, body.password),
        "created_at": now(),
        "settings": {"USER_NAME": body.name.strip()},
    }
    try:
        doc["_id"] = database().users.insert_one(doc).inserted_id
    except DuplicateKeyError:
        return JSONResponse({"detail": "That email already has an account. Sign in instead."}, status_code=409)
    return _start_session(request, str(doc["_id"]))


@router.post("/api/login")
async def login(body: LoginIn, request: Request):
    user = database().users.find_one({"email": body.email.strip().lower()})
    ok = user is not None and await asyncio.to_thread(check_password, body.password, user["password_hash"])
    if not ok:
        await asyncio.sleep(1.0)  # slows down guessing
        return JSONResponse({"detail": "Wrong email or password."}, status_code=401)
    return _start_session(request, str(user["_id"]))


@router.post("/api/logout")
def logout():
    res = JSONResponse({"ok": True})
    res.delete_cookie(COOKIE, path="/")
    return res


@router.get("/login", include_in_schema=False)
def login_page(request: Request):
    if current_user.get():
        return RedirectResponse("/")
    return HTMLResponse(LOGIN_PAGE.replace("__SIGNUP__", "true" if signups_open() else "false"))


SETUP_PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Almost there</title><body style="font:16px/1.5 system-ui;max-width:32rem;margin:15vh auto;padding:0 1.25rem;color:#15132b">
<h1>One more step</h1><p>{msg}</p></body>"""

LOGIN_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#e8e2fb"><title>Sign in</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Ccircle cx='32' cy='32' r='30' fill='%23a98bf5'/%3E%3C/svg%3E">
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@500;700;800&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box}body{margin:0;min-height:100dvh;display:grid;place-items:center;padding:20px;background:#e8e2fb;color:#15132b;font:500 16px/1.5 "Plus Jakarta Sans",system-ui,sans-serif}
main{width:min(400px,100%);background:#f6f5f8;border-radius:32px;padding:30px 24px 24px;box-shadow:0 30px 70px -30px rgba(21,19,43,.4);animation:rise .6s cubic-bezier(.2,.8,.2,1) both}
@keyframes rise{from{opacity:0;transform:translateY(18px) scale(.97)}to{opacity:1;transform:none}}
.tile{width:92px;height:92px;margin:0 auto 16px;border-radius:30px;display:grid;place-items:center;background:linear-gradient(150deg,#fff,#efe6ff);box-shadow:0 22px 30px -14px rgba(52,22,128,.5);transform:rotate(-6deg);animation:float 5s ease-in-out infinite}
@keyframes float{50%{transform:translateY(-8px) rotate(-2deg)}}
h1{margin:0 0 4px;text-align:center;font-size:28px;font-weight:800;letter-spacing:-.02em}p.sub{margin:0 0 18px;text-align:center;color:#5f5c78}
.seg{display:grid;grid-template-columns:1fr 1fr;background:#fff;border-radius:999px;padding:4px;margin-bottom:16px}
.seg button{margin:0;min-height:42px;border:0;border-radius:999px;background:transparent;color:#5f5c78;font:inherit;font-weight:700;cursor:pointer}
.seg button[aria-pressed="true"]{background:#15132b;color:#fff}
label{display:block;margin:0 0 10px}label span{display:block;font-size:13px;font-weight:700;color:#5f5c78;margin:0 0 4px 4px}
input{width:100%;min-height:52px;padding:12px 18px;border:1.5px solid #e6e3f0;border-radius:18px;background:#fff;font:inherit;font-size:16px;outline:none}input:focus{border-color:#15132b}
.go{width:100%;min-height:54px;margin-top:8px;border:0;border-radius:999px;background:#15132b;color:#fff;font:inherit;font-weight:700;cursor:pointer;transition:transform .15s}.go:active{transform:scale(.97)}.go:disabled{opacity:.5}
.err{min-height:1.4em;margin:10px 0 0;text-align:center;color:#c2413a;font-size:14px}
[hidden]{display:none!important}
</style></head><body>
<main>
<div class="tile"><svg width="66" height="66" viewBox="0 0 100 100" aria-hidden="true">
<path d="M16 50 L17 17 Q18 10 24 14 L39 27 Q50 24 61 27 L76 14 Q82 10 83 17 L84 50 Q85 80 50 85 Q15 80 16 50Z" fill="#1b2a3b"/>
<path d="M24 50 H44 Q43 60 34 60 Q25 60 24 50Z" fill="#f59a23"/><path d="M34 51 V58" stroke="#16202c" stroke-width="2.4" stroke-linecap="round"/>
<path d="M56 50 H76 Q75 60 66 60 Q57 60 56 50Z" fill="#f59a23"/><path d="M66 51 V58" stroke="#16202c" stroke-width="2.4" stroke-linecap="round"/>
<g stroke="#8fa6ba" stroke-width="1.6" stroke-linecap="round" fill="none"><path d="M18 62 L3 59"/><path d="M18 67 L4 70"/><path d="M82 62 L97 59"/><path d="M82 67 L96 70"/></g></svg></div>
<h1 id="title">Welcome back</h1><p class="sub" id="sub">Sign in to see your day.</p>
<div class="seg" id="seg"><button type="button" data-mode="in" aria-pressed="true">Sign in</button><button type="button" data-mode="up" aria-pressed="false">Create account</button></div>
<form id="f">
<label id="name-row" hidden><span>Your name</span><input id="name" autocomplete="name" maxlength="40" placeholder="Atharva"></label>
<label><span>Email</span><input id="email" type="email" autocomplete="email" placeholder="you@example.com" required></label>
<label><span>Password</span><input id="pw" type="password" autocomplete="current-password" placeholder="At least 8 characters" required></label>
<button class="go" id="go">Sign in</button><div class="err" id="err" role="alert"></div></form>
</main>
<script>
const SIGNUP=__SIGNUP__;let mode="in";
const $=id=>document.getElementById(id);
if(!SIGNUP)$("seg").hidden=true;
function setMode(m){mode=m;const up=m==="up";$("name-row").hidden=!up;$("name").required=up;$("pw").autocomplete=up?"new-password":"current-password";
$("title").textContent=up?"Create your account":"Welcome back";$("sub").textContent=up?"Your todos, chats and files stay yours.":"Sign in to see your day.";
$("go").textContent=up?"Create account":"Sign in";$("err").textContent="";
document.querySelectorAll("#seg button").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.mode===m)))}
document.querySelectorAll("#seg button").forEach(b=>b.addEventListener("click",()=>setMode(b.dataset.mode)));
$("f").addEventListener("submit",async e=>{e.preventDefault();$("go").disabled=true;$("err").textContent="";
const body={email:$("email").value,password:$("pw").value};if(mode==="up")body.name=$("name").value;
try{const r=await fetch(mode==="up"?"/api/signup":"/api/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
if(r.ok){location.replace("/");return}const d=await r.json().catch(()=>({}));
$("err").textContent=typeof d.detail==="string"?d.detail:"Please check what you entered."}
catch{$("err").textContent="Can't reach the app. Check your connection."}$("go").disabled=false});
</script></body></html>
"""
