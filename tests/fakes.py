"""Message factory and service fakes shared by the TgRepostBot test suite.

Plain module (not conftest) so tests import it explicitly: `from conftest
import ...` is discouraged by pytest. Fixtures live in conftest.py.
"""
import io
import os
from datetime import datetime, timezone
from types import SimpleNamespace

from aiogram.types import Chat, Message, PhotoSize

from models import User


def make_message(
    message_id: int,
    *,
    text: str | None = None,
    caption: str | None = None,
    photo: str | None = None,
    media_group_id: str | None = None,
    chat_id: int = 42,
) -> Message:
    """Minimal aiogram Message; only the fields the codebase actually touches."""
    photos = None
    if photo is not None:
        photos = [
            PhotoSize(file_id=f"{photo}-small", file_unique_id=f"{photo}-us", width=10, height=10),
            PhotoSize(file_id=f"{photo}-large", file_unique_id=f"{photo}-ul", width=1000, height=1000),
        ]
    return Message(
        message_id=message_id,
        date=datetime.now(timezone.utc),
        chat=Chat(id=chat_id, type="private"),
        text=text,
        caption=caption,
        photo=photos,
        media_group_id=media_group_id,
    )


def make_user(**overrides) -> User:
    defaults = dict(
        user_id=1,
        linkedin_access_token="li-token",
        linkedin_person_urn="urn:li:person:abc",
        instagram_username="iguser",
        instagram_password_encrypted="enc-password",
    )
    defaults.update(overrides)
    return User(**defaults)


class FakeBot:
    """Telegram Bot stand-in: serves photo bytes from memory."""

    def __init__(self, data: bytes = b"jpeg-bytes", fail_download_for=()):
        self.data = data
        self.fail_download_for = set(fail_download_for)
        self.requested_file_ids = []

    async def get_file(self, file_id: str):
        self.requested_file_ids.append(file_id)
        return SimpleNamespace(file_path=f"/telegram/files/{file_id}")

    async def download_file(self, file_path: str):
        file_id = file_path.rsplit("/", 1)[-1]
        if file_id in self.fail_download_for:
            raise RuntimeError(f"download failed for {file_id}")
        return io.BytesIO(self.data)


class FakeLinkedIn:
    def __init__(self, upload_fail_indexes=(), create_post_exc=None):
        self.upload_fail_indexes = set(upload_fail_indexes)
        self.create_post_exc = create_post_exc
        self.uploaded_images = []
        self.posts = []
        self._upload_calls = 0

    async def upload_image_full(self, access_token, person_urn, data):
        index = self._upload_calls
        self._upload_calls += 1
        if index in self.upload_fail_indexes:
            raise RuntimeError(f"upload {index} failed")
        self.uploaded_images.append(data)
        return f"urn:li:digitalAssetAsset:{len(self.uploaded_images)}"

    async def create_post(self, access_token, person_urn, text, image_urns):
        if self.create_post_exc is not None:
            raise self.create_post_exc
        self.posts.append((access_token, person_urn, text, image_urns))


class FakeInstagram:
    def __init__(self, exc=None):
        self.exc = exc
        self.calls = []

    async def publish(self, user_id, username, password, totp, sessionid, text, photo_paths):
        self.calls.append(
            {
                "user_id": user_id,
                "username": username,
                "password": password,
                "totp": totp,
                "sessionid": sessionid,
                "text": text,
                "photo_paths": list(photo_paths),
                # Captured at call time: the temp files must still exist while
                # Instagram uploads them (cleanup happens only after publish).
                "paths_existed": [os.path.exists(p) for p in photo_paths],
            }
        )
        if self.exc is not None:
            raise self.exc
        return "media_123"
