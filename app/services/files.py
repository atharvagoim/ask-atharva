"""Your files: uploads (things you give Atharva) and outputs (things it makes).

The bytes live in MongoDB, per user. The local disk is only a scratch area: a file is copied
there when something needs a real path (pandas, python-pptx, downloads) and written back
to the database when the app creates one.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from bson import Binary

from app.config import DATA_DIR, ON_VERCEL
from app.db import aware, database, now, user_id

# Vercel rejects request bodies over 4.5 MB; a MongoDB document holds at most 16 MB.
MAX_UPLOAD_BYTES = 4 * 1024 * 1024 if ON_VERCEL else 15 * 1024 * 1024
MAX_UPLOAD_MB = MAX_UPLOAD_BYTES // (1024 * 1024)
ALLOWED_UPLOADS = {".csv", ".xlsx", ".xlsm", ".txt", ".md", ".vtt", ".srt"}
SPREADSHEETS = {".csv", ".xlsx", ".xlsm"}
NOTES = {".txt", ".md", ".vtt", ".srt"}
KINDS = ("uploads", "outputs")


class FileError(ValueError):
    pass


def folder(kind: str) -> Path:
    """This user's scratch folder for `kind` (never shared with other accounts)."""
    if kind not in KINDS:
        raise FileError("Unknown folder.")
    path = DATA_DIR / kind / user_id()
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_name(name: str) -> str:
    """Strip any folders and odd characters: 'C:/x/../Q3 Sales (v2).xlsx' → 'Q3 Sales (v2).xlsx'."""
    base = Path(str(name).replace("\\", "/")).name
    base = re.sub(r"[^\w\-. ()&+,]", "_", base).strip(" .")
    return base[:120] or "file"


def _files():
    return database().files


def _stored(kind: str) -> list[dict]:
    rows = _files().find({"user_id": user_id(), "kind": kind}, {"data": 0}).sort("modified", -1)
    return [
        {"name": r["name"], "kind": kind, "size": r["size"], "modified": aware(r["modified"]).isoformat(), "url": f"/api/files/{kind}/{quote(r['name'])}"}
        for r in rows
    ]


def _taken(kind: str) -> set[str]:
    return {r["name"] for r in _files().find({"user_id": user_id(), "kind": kind}, {"name": 1})}


def unique_path(kind: str, name: str) -> Path:
    base = folder(kind)
    taken = _taken(kind)
    path = base / safe_name(name)
    stem, suffix, n = path.stem, path.suffix, 2
    while path.exists() or path.name in taken:
        path = base / f"{stem} ({n}){suffix}"
        n += 1
    return path


def _persist(kind: str, path: Path) -> None:
    data = path.read_bytes()
    _files().update_one(
        {"user_id": user_id(), "kind": kind, "name": path.name},
        {"$set": {"data": Binary(data), "size": len(data), "modified": now()}},
        upsert=True,
    )


def _pull(kind: str, name: str) -> bool:
    """Make sure a stored file exists on the scratch disk. False if it isn't stored."""
    target = folder(kind) / name
    if target.is_file():
        return True
    row = _files().find_one({"user_id": user_id(), "kind": kind, "name": name})
    if row is None:
        return False
    target.write_bytes(bytes(row["data"]))
    return True


def save_upload(name: str, data: bytes) -> Path:
    suffix = Path(safe_name(name)).suffix.lower()
    if suffix not in ALLOWED_UPLOADS:
        raise FileError(f"{suffix or 'That file type'} isn't supported. Upload a spreadsheet (.xlsx, .csv) or notes (.txt, .md).")
    if len(data) > MAX_UPLOAD_BYTES:
        raise FileError(f"That file is larger than {MAX_UPLOAD_MB} MB.")
    if not data:
        raise FileError("That file is empty.")
    path = unique_path("uploads", name)
    path.write_bytes(data)
    _persist("uploads", path)
    return path


def resolve(kind: str, name: str) -> Path:
    base = folder(kind)
    clean = safe_name(name)
    _pull(kind, clean)
    path = (base / clean).resolve()
    if path.parent != base.resolve() or not path.is_file():
        raise FileError(f"I can't find a file called “{name}”.")
    return path


def delete_file(kind: str, name: str) -> None:
    path = resolve(kind, name)
    path.unlink(missing_ok=True)
    _files().delete_one({"user_id": user_id(), "kind": kind, "name": path.name})


def find_upload(name: str) -> Path:
    """Exact name, or the closest uploaded file whose name contains it."""
    try:
        return resolve("uploads", name)
    except FileError:
        pass
    q = Path(str(name)).name.lower()
    stem = Path(q).stem
    names = [f["name"] for f in _stored("uploads")]  # newest first
    for n in names:
        if q in n.lower() or (stem and stem in Path(n).stem.lower()):
            return resolve("uploads", n)
    raise FileError(f"I can't find “{name}” in your uploaded files (uploaded: {', '.join(names) or 'none yet'}).")


def describe(path: Path, kind: str) -> dict:
    st = path.stat()
    return {
        "name": path.name,
        "kind": kind,
        "size": st.st_size,
        "modified": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
        "url": f"/api/files/{kind}/{quote(path.name)}",
    }


def list_files(kind: str) -> list[dict]:
    return _stored(kind)


def snapshot_outputs() -> dict[str, float]:
    return {p.name: p.stat().st_mtime for p in folder("outputs").iterdir() if p.is_file()}


def new_outputs_since(before: dict[str, float]) -> list[dict]:
    out = folder("outputs")
    after = [p for p in out.iterdir() if p.is_file() and before.get(p.name) != p.stat().st_mtime]
    after.sort(key=lambda p: p.stat().st_mtime)
    for p in after:
        _persist("outputs", p)
    return [describe(p, "outputs") for p in after]


def output_path(name: str) -> Path:
    """A fresh, unique path in outputs/ (never overwrites earlier results)."""
    return unique_path("outputs", name)


def timestamp() -> str:
    from app.services.dates import now_local

    return now_local().strftime("%Y-%m-%d %H%M")
