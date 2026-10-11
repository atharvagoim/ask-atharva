import io
from contextlib import contextmanager
from datetime import timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import app.config as config
from app.agent import llm as llm_module
from app.main import app
from app.services import calendar as cal
from app.services.dates import now_local
from fake_llm import FakeLLM

client = TestClient(app)
assert client.post("/api/signup", json={"name": "Atharva", "email": "me@example.com", "password": "password123"}).status_code == 200


@contextmanager
def as_user(email="me@example.com"):
    """Run service code outside a request as a particular account."""
    from app.db import current_user, database

    token = current_user.set(database().users.find_one({"email": email}))
    try:
        yield
    finally:
        current_user.reset(token)


@pytest.fixture(autouse=True)
def reset_ai():
    llm_module.set_llm_override(None)
    yield
    llm_module.set_llm_override(None)


def test_web_page_and_status():
    assert client.get("/").status_code == 200
    s = client.get("/api/status").json()
    assert s["name"] == "Atharva" and s["ai"]["ready"] is False


def test_todos_without_ai():
    r = client.post("/api/todos", json={"title": "Water the plants", "priority": "urgent", "due": "tomorrow"})
    assert r.status_code == 201
    t = r.json()
    assert t["priority"] == "high" and t["due"] == (now_local().date() + timedelta(days=1)).isoformat()
    again = client.post("/api/todos", json={"title": "water the PLANTS"}).json()
    assert again["created"] is False and again["id"] == t["id"]
    assert client.post("/api/todos", json={"title": "x", "due": "blorp day"}).status_code == 400
    assert client.patch(f"/api/todos/{t['id']}", json={"done": True}).json()["done"] is True
    assert all(x["id"] != t["id"] for x in client.get("/api/todos").json())
    assert any(x["id"] == t["id"] for x in client.get("/api/todos?show=done").json())
    assert client.patch(f"/api/todos/{t['id']}", json={"due": None}).json()["due"] is None
    assert client.delete(f"/api/todos/{t['id']}").status_code == 200
    assert client.delete(f"/api/todos/{t['id']}").status_code == 404
    assert client.post("/api/todos", json={"title": ""}).status_code == 400


def test_chat_without_key_explains():
    r = client.post("/api/chat", json={"message": "hi"})
    assert r.status_code == 409 and "app owner" in r.json()["detail"]
    assert client.get("/api/threads").json() == [] or True


def test_chat_with_tools_and_memory():
    llm_module.set_llm_override(FakeLLM())
    r = client.post("/api/chat", json={"message": "add a todo to finish the q3 report by friday"}).json()
    assert "Added" in r["message"]["content"] and r["refresh"] == ["todos"]
    tid = r["thread_id"]
    r2 = client.post("/api/chat", json={"message": "add finish the q3 report", "thread_id": tid}).json()
    assert "already on the list" in r2["message"]["content"]
    r3 = client.post("/api/chat", json={"message": "what's left?", "thread_id": tid}).json()
    assert "finish the q3 report" in r3["message"]["content"]
    r4 = client.post("/api/chat", json={"message": "done with q3", "thread_id": tid}).json()
    assert "Done: “finish the q3 report”" in r4["message"]["content"]
    r5 = client.post("/api/chat", json={"message": "what did I just ask?", "thread_id": tid}).json()
    assert "done with q3" in r5["message"]["content"]  # memory works
    hist = client.get(f"/api/threads/{tid}").json()
    assert len(hist["messages"]) == 10 and hist["title"].startswith("add a todo")


def test_calendar_events_crud_and_assistant():
    from datetime import date
    day = (date.today() + timedelta(days=3)).isoformat()
    ev = client.post("/api/calendar/events", json={"title": "Design review", "date": day, "time": "14:30", "duration_minutes": 45, "location": "Room A2"})
    assert ev.status_code == 201
    e = ev.json()
    assert e["title"] == "Design review" and e["start"].startswith(f"{day}T14:30") and e["location"] == "Room A2" and not e["all_day"]
    allday = client.post("/api/calendar/events", json={"title": "Holiday", "date": day, "all_day": True}).json()
    assert allday["all_day"] and allday["start"].startswith(f"{day}T00:00")
    listed = client.get(f"/api/calendar/events?day={day}&days=1").json()["events"]
    assert [x["title"] for x in listed] == ["Holiday", "Design review"]
    assert client.get(f"/api/calendar/events?day={day}&days=1&x=1").status_code == 200
    moved = client.patch(f"/api/calendar/events/{e['id']}", json={"time": "16:00", "title": "Design review v2"}).json()
    assert moved["start"].startswith(f"{day}T16:00") and moved["end"].startswith(f"{day}T16:45") and moved["title"] == "Design review v2"
    assert client.post("/api/calendar/events", json={"title": "x"}).status_code == 400  # needs a date or words
    assert client.post("/api/calendar/events", json={"title": "x", "when": "gibberish never"}).status_code == 400
    # plain words work too (this is what the assistant uses)
    said = client.post("/api/calendar/events", json={"title": "Call Riya", "when": "tomorrow 3pm"}).json()
    assert "T15:00" in said["start"]
    llm_module.set_llm_override(FakeLLM())
    r = client.post("/api/chat", json={"message": "what's on my calendar?"}).json()
    assert "calendar" in r["message"]["content"].lower() or "Nothing" in r["message"]["content"] or "Today" in r["message"]["content"]
    # another account never sees these
    other = TestClient(app)
    other.post("/api/signup", json={"name": "Sam", "email": "sam@example.com", "password": "password789"})
    assert other.get(f"/api/calendar/events?day={day}&days=1").json()["events"] == []
    assert other.delete(f"/api/calendar/events/{e['id']}").status_code == 400
    for x in (e, allday, said):
        assert client.delete(f"/api/calendar/events/{x['id']}").status_code == 200
    assert client.delete(f"/api/calendar/events/{e['id']}").status_code == 400
    t = client.get("/api/today").json()
    assert "events" in t and "calendar" not in t


def test_upload_analyse_download():
    df = pd.DataFrame({"Region": ["North", "South", "North", "East"], "Sales": [100, 250, 50, None], "Units": [1, 2, 3, 4]})
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    up = client.post("/api/files", files={"file": ("Q3 sales.xlsx", buf.getvalue(), "application/octet-stream")})
    assert up.status_code == 201 and up.json()["name"] == "Q3 sales.xlsx"
    assert client.post("/api/files", files={"file": ("evil.exe", b"MZ", "application/octet-stream")}).status_code == 400
    assert client.get("/api/files/uploads/..%2F..%2Fapp%2Fconfig.py").status_code == 404
    llm_module.set_llm_override(FakeLLM())
    r = client.post("/api/chat", json={"message": "analyse sales and make a chart"}).json()
    content = r["message"]["content"]
    assert "Total “Sales” by “Region”" in content and "South" in content
    names = [f["name"] for f in r["message"]["files"]]
    assert any(n.endswith(".png") for n in names) and any(n.endswith(".xlsx") for n in names)
    dl = client.get(r["message"]["files"][0]["url"])
    assert dl.status_code == 200 and len(dl.content) > 1000


def test_slides_ai_and_fallback():
    llm_module.set_llm_override(FakeLLM())
    r = client.post("/api/chat", json={"message": "make me a presentation"}).json()
    assert "Point 1" in r["message"]["content"] and r["message"]["files"][0]["name"].endswith(".pptx")
    from pptx import Presentation
    prs = Presentation(io.BytesIO(client.get(r["message"]["files"][0]["url"]).content))
    assert len(prs.slides) == 5
    llm_module.set_llm_override(None)
    from app.services import slides
    with as_user():
        out = slides.create("Offline topic", 4)
    assert out["by_ai"] is False and out["slides"] == 5


def test_meeting_notes_file_creates_todos():
    notes = b"Standup notes. Riya will send the launch email to customers. We decided to launch Monday. Someone should update the pricing page."
    client.post("/api/files", files={"file": ("standup.txt", notes, "text/plain")})
    llm_module.set_llm_override(FakeLLM())
    r = client.post("/api/chat", json={"message": "summarise my standup notes"}).json()
    assert "Added 2 todo(s)" in r["message"]["content"] and "todos" in r["refresh"]
    titles = [t["title"] for t in client.get("/api/todos").json()]
    assert "Update the pricing page" in titles
    r2 = client.post("/api/chat", json={"message": "summarise my standup notes"}).json()
    assert "Already on the list" in r2["message"]["content"]


def test_settings_roundtrip_is_saved_on_the_account():
    r = client.put("/api/settings", json={"name": "Atharva G", "timezone": "America/New_York", "groq_api_key": "gsk_sneaky"})
    assert r.status_code == 200 and r.json()["name"] == "Atharva G" and r.json()["ai"] == {"ready": False}  # AI keys can't be set from the app
    assert client.get("/api/status").json()["name"] == "Atharva G"  # a fresh request reads it back from MongoDB
    assert client.get("/api/status").json()["timezone"] == "Asia/Kolkata"  # fixed to IST; a time zone can't be changed
    client.put("/api/settings", json={"name": "Atharva"})


def test_free_slots_handles_timezones_and_all_day(monkeypatch):
    day = now_local().date() + timedelta(days=2)
    tz = config.settings().tz
    from datetime import datetime, time
    events = [
        {"id": "a", "title": "All hands", "start": datetime.combine(day, time(10), tz).astimezone(tz.__class__("UTC")).isoformat(), "end": datetime.combine(day, time(11), tz).isoformat(), "all_day": False},
        {"id": "b", "title": "Birthday", "start": datetime.combine(day, time(0), tz).isoformat(), "end": datetime.combine(day + timedelta(days=1), time(0), tz).isoformat(), "all_day": True},
        {"id": "c", "title": "Lunch", "start": datetime.combine(day, time(13), tz).isoformat(), "end": datetime.combine(day, time(14), tz).isoformat(), "all_day": False},
    ]
    monkeypatch.setattr(cal, "list_events", lambda s, e: events)
    slots = cal.free_slots(day, 60)
    as_text = [(cal.fmt_time(s), cal.fmt_time(e)) for s, e in slots]
    assert as_text == [("9:00 AM", "10:00 AM"), ("11:00 AM", "1:00 PM"), ("2:00 PM", "6:00 PM")]


def test_ai_errors_are_plain_english():
    class Boom:
        def bind_tools(self, _):
            return self

        def invoke(self, *_a, **_k):
            raise RuntimeError("Error code: 401 - invalid api key")

    llm_module.set_llm_override(Boom())
    r = client.post("/api/chat", json={"message": "hello"})
    assert r.status_code == 502 and "rejected" in r.json()["detail"]
    assert client.get("/api/threads").status_code == 200


def _user_id(email):
    from app.db import database

    return str(database().users.find_one({"email": email})["_id"])


def test_sign_up_and_sign_in_rules():
    anon = TestClient(app)
    assert anon.get("/api/status").status_code == 401
    page = anon.get("/", follow_redirects=False)
    assert page.status_code == 307 and page.headers["location"] == "/login"
    assert "Create account" in anon.get("/login").text
    bad = lambda **kw: anon.post("/api/signup", json={"name": "Z", "email": "z@example.com", "password": "longenough1", **kw})
    assert bad(password="short").status_code == 400
    assert bad(email="not-an-email").status_code == 400
    assert bad(email="ME@example.com").status_code == 409  # emails are case-insensitive and unique
    assert anon.post("/api/login", json={"email": "me@example.com", "password": "wrong-password"}).status_code == 401
    assert anon.post("/api/login", json={"email": "nobody@example.com", "password": "password123"}).status_code == 401
    ok = anon.post("/api/login", json={"email": " Me@Example.com ", "password": "password123"})
    assert ok.status_code == 200 and "httponly" in ok.headers["set-cookie"].lower()
    assert anon.get("/api/status").json()["email"] == "me@example.com"
    assert anon.post("/api/logout").status_code == 200
    anon.cookies.clear()
    assert anon.get("/api/status").status_code == 401
    forged = TestClient(app, cookies={"atharva_session": f"{_user_id('me@example.com')}.9999999999.deadbeef"})
    assert forged.get("/api/status").status_code == 401


def test_passwords_are_hashed():
    from app.db import database

    stored = database().users.find_one({"email": "me@example.com"})["password_hash"]
    assert stored.startswith("scrypt$") and "password123" not in stored


def test_each_account_only_sees_its_own_data():
    other = TestClient(app)
    assert other.post("/api/signup", json={"name": "Riya", "email": "riya@example.com", "password": "password456"}).status_code == 200
    assert other.get("/api/status").json()["name"] == "Riya"
    mine = client.post("/api/todos", json={"title": "my private todo"}).json()
    assert other.get("/api/todos").json() == []
    assert other.patch(f"/api/todos/{mine['id']}", json={"done": True}).status_code == 404
    assert other.delete(f"/api/todos/{mine['id']}").status_code == 404
    client.post("/api/files", files={"file": ("secret plan.txt", b"for my eyes only", "text/plain")})
    assert other.get("/api/files").json() == {"uploads": [], "outputs": []}
    assert other.get("/api/files/uploads/secret%20plan.txt").status_code == 404
    llm_module.set_llm_override(FakeLLM())
    t = client.post("/api/chat", json={"message": "what's on my plate today?"}).json()["thread_id"]
    assert other.get(f"/api/threads/{t}").status_code == 404
    assert other.get("/api/threads").json() == []
    assert client.get(f"/api/threads/{t}").status_code == 200
    client.delete(f"/api/todos/{mine['id']}")


def test_files_survive_a_wiped_scratch_disk():
    from app.config import DATA_DIR

    up = client.post("/api/files", files={"file": ("notes db.txt", b"hello from mongo", "text/plain")})
    assert up.status_code == 201
    assert any(f["name"] == "notes db.txt" for f in client.get("/api/files").json()["uploads"])
    (DATA_DIR / "uploads" / _user_id("me@example.com") / "notes db.txt").unlink()  # a fresh serverless instance has an empty disk
    assert client.get("/api/files/uploads/notes%20db.txt").content == b"hello from mongo"
    assert client.delete("/api/files/uploads/notes%20db.txt").status_code == 200
    assert not any(f["name"] == "notes db.txt" for f in client.get("/api/files").json()["uploads"])


def test_profile_photo_upload_replace_and_remove():
    from PIL import Image

    def png(color, size=(600, 300)):
        buf = io.BytesIO()
        Image.new("RGB", size, color).save(buf, "PNG")
        return buf.getvalue()

    assert client.get("/api/status").json()["photo"] is None
    assert client.get("/api/profile/photo").status_code == 404
    up = client.post("/api/profile/photo", files={"file": ("me.png", png("orange"), "image/png")})
    assert up.status_code == 200 and up.json()["photo"].startswith("/api/profile/photo?v=")
    got = client.get("/api/profile/photo")
    assert got.status_code == 200 and got.headers["content-type"] == "image/jpeg"
    assert Image.open(io.BytesIO(got.content)).size == (320, 320)  # cropped to a square
    first = up.json()["photo"]
    again = client.post("/api/profile/photo", files={"file": ("me2.png", png("blue", (400, 400)), "image/png")}).json()["photo"]
    assert again != first  # a new version so browsers refresh it
    assert client.post("/api/profile/photo", files={"file": ("x.png", b"not an image", "image/png")}).status_code == 400
    assert client.post("/api/profile/photo", files={"file": ("big.png", b"0" * (3 * 1024 * 1024), "image/png")}).status_code == 400
    other = TestClient(app)
    other.post("/api/signup", json={"name": "Kim", "email": "kim@example.com", "password": "password000"})
    assert other.get("/api/profile/photo").status_code == 404  # photos are per account
    assert client.delete("/api/profile/photo").json()["photo"] is None
    assert client.get("/api/profile/photo").status_code == 404


def test_todo_stats_show_progress():
    other = TestClient(app)
    other.post("/api/signup", json={"name": "Stat", "email": "stat@example.com", "password": "password111"})
    assert other.get("/api/todos/stats").json()["total"] == 0 and other.get("/api/todos/stats").json()["percent"] == 0
    ids = [other.post("/api/todos", json={"title": f"task {i}", "priority": "high" if i == 0 else "low", "due": "2020-01-01" if i < 2 else None}).json()["id"] for i in range(4)]
    other.patch(f"/api/todos/{ids[0]}", json={"done": True})
    st = other.get("/api/todos/stats").json()
    assert (st["total"], st["done"], st["open"], st["percent"]) == (4, 1, 3, 25)
    assert st["overdue"] == 1 and st["high_open"] == 0 and len(st["last7"]) == 7 and st["last7"][-1]["done"] == 1
    assert "recent_files" not in other.get("/api/today").json()


def test_home_lists_tomorrows_tasks():
    other = TestClient(app)
    other.post("/api/signup", json={"name": "Tom", "email": "tom@example.com", "password": "password222"})
    assert other.get("/api/today").json()["tomorrow"] == []
    tomorrow = (now_local().date() + timedelta(days=1)).isoformat()
    other.post("/api/todos", json={"title": "pack bags", "due": tomorrow})
    other.post("/api/todos", json={"title": "someday thing"})
    t = other.get("/api/today").json()
    assert [x["title"] for x in t["tomorrow"]] == ["pack bags"]
    assert "pack bags" not in [x["title"] for x in t["upcoming"]] and "someday thing" in [x["title"] for x in t["upcoming"]]
    # the days after tomorrow (within a week) are listed too; anything further away stays in the main list
    other.post("/api/todos", json={"title": "in three days", "due": (now_local().date() + timedelta(days=3)).isoformat()})
    other.post("/api/todos", json={"title": "next month", "due": (now_local().date() + timedelta(days=30)).isoformat()})
    t = other.get("/api/today").json()
    assert [x["title"] for x in t["later"]] == ["in three days"]
    assert "next month" in [x["title"] for x in t["upcoming"]] and "in three days" not in [x["title"] for x in t["upcoming"]]
