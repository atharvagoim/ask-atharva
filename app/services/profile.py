"""Profile photo: one small square JPEG per account, stored on the user's document."""
from __future__ import annotations

import io
import time

from bson import Binary, ObjectId

from app.db import current_user, database, user_id

MAX_PHOTO_BYTES = 2 * 1024 * 1024
SIZE = 320  # pixels; plenty for a round avatar, tiny to store


class PhotoError(ValueError):
    pass


def make_avatar(raw: bytes) -> bytes:
    """Validate an uploaded image and turn it into a clean square JPEG (drops metadata too)."""
    if len(raw) > MAX_PHOTO_BYTES:
        raise PhotoError("That photo is larger than 2 MB.")
    try:
        from PIL import Image, ImageOps

        img = Image.open(io.BytesIO(raw))
        img.load()
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception as e:  # noqa: BLE001 — anything Pillow can't read
        raise PhotoError("That doesn't look like a photo I can use. Try a JPG or PNG.") from e
    img = ImageOps.fit(img, (SIZE, SIZE), method=Image.LANCZOS)  # centre-crop to a square
    out = io.BytesIO()
    img.save(out, "JPEG", quality=88, optimize=True)
    return out.getvalue()


def save_photo(raw: bytes) -> int:
    data = make_avatar(raw)
    version = int(time.time() * 1000)
    database().users.update_one({"_id": ObjectId(user_id())}, {"$set": {"avatar": Binary(data), "avatar_v": version}})
    user = current_user.get()
    if user is not None:
        user["avatar_v"] = version
        user["avatar"] = True
    return version


def get_photo() -> bytes | None:
    doc = database().users.find_one({"_id": ObjectId(user_id())}, {"avatar": 1}) or {}
    return bytes(doc["avatar"]) if doc.get("avatar") else None


def delete_photo() -> None:
    database().users.update_one({"_id": ObjectId(user_id())}, {"$unset": {"avatar": "", "avatar_v": ""}})
    user = current_user.get()
    if user is not None:
        user.pop("avatar", None)
        user.pop("avatar_v", None)


def photo_url(user: dict | None) -> str | None:
    return f"/api/profile/photo?v={user['avatar_v']}" if user and user.get("avatar_v") else None
