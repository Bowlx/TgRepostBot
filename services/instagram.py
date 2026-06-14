"""Instagram destination via the instagrapi private-API library.

instagrapi is synchronous, so every call runs in asyncio.to_thread. Login
supports TOTP (automatic, via pyotp) and SMS/email challenges (interactive —
bridged to a Telegram FSM through an in-memory future registry).
"""
import asyncio
import logging
import os
from typing import Optional

import pyotp
from instagrapi import Client

from services.crypto import Crypto

logger = logging.getLogger(__name__)


class InstagramClient:
    def __init__(
        self,
        session_dir: str,
        crypto: Crypto,
        ask_code=None,
    ):
        # ask_code: async callable(user_id, choice) -> Optional[str]
        # provided by the handler layer to request an SMS/email 2FA code.
        self.session_dir = session_dir
        self.crypto = crypto
        self.ask_code = ask_code
        # user_id -> asyncio.Future, resolved when the FSM receives the code.
        self._pending_codes: dict[int, asyncio.Future] = {}
        os.makedirs(session_dir, exist_ok=True)

    def session_path(self, user_id: int) -> str:
        return os.path.join(self.session_dir, f"ig_session_{user_id}.json")

    def submit_code(self, user_id: int, code: str) -> bool:
        """Called by the FSM handler when the user types their 2FA code."""
        fut = self._pending_codes.get(user_id)
        if fut is None or fut.done():
            return False
        fut.set_result(code)
        return True

    async def login(
        self,
        user_id: int,
        username: str,
        password: str,
        totp_secret: Optional[str] = None,
    ) -> None:
        cl = await self._get_client(user_id, username, password, totp_secret)
        cl.dump_settings(self.session_path(user_id))

    async def _get_client(self, user_id: int, username: str, password: str,
                          totp_secret: Optional[str]) -> Client:
        """Load a logged-in client, reusing the session file."""
        loop = asyncio.get_running_loop()

        def challenge_handler(uname, choice):
            # Runs inside the worker thread. Bridge to the async ask_code.
            if self.ask_code is None:
                return False
            fut: asyncio.Future = loop.create_future()
            self._pending_codes[user_id] = fut
            try:
                return asyncio.run_coroutine_threadsafe(
                    self.ask_code(user_id, choice), loop
                ).result(timeout=300)
            except Exception as e:
                logger.error(f"Instagram challenge code not provided: {e}")
                return False
            finally:
                self._pending_codes.pop(user_id, None)

        def _build():
            cl = Client()
            cl.challenge_code_handler = challenge_handler
            path = self.session_path(user_id)
            if os.path.exists(path):
                cl.set_settings(cl.load_settings(path))
            verification = pyotp.TOTP(totp_secret).now() if totp_secret else None
            cl.login(username, password, verification_code=verification)
            return cl

        return await asyncio.to_thread(_build)

    async def publish(
        self,
        user_id: int,
        username: str,
        password_enc: str,
        totp_secret_enc: Optional[str],
        caption: str,
        image_paths: list[str],
    ) -> str:
        """Publish a photo or carousel. Returns the media id (str)."""
        password = self.crypto.decrypt(password_enc)
        totp_secret = (
            self.crypto.decrypt(totp_secret_enc) if totp_secret_enc else None
        )

        cl = await self._get_client(user_id, username, password, totp_secret)

        def _upload():
            if len(image_paths) == 1:
                media = cl.photo_upload(image_paths[0], caption)
            else:
                media = cl.album_upload(image_paths, caption)
            return str(media.id)

        try:
            return await asyncio.to_thread(_upload)
        except Exception:
            # One retry: rebuild client (forces fresh login) then upload again.
            logger.warning("Instagram publish failed once, retrying after re-login")
            cl = await self._get_client(user_id, username, password, totp_secret)
            return await asyncio.to_thread(_upload)

    async def logout(self, user_id: int) -> None:
        path = self.session_path(user_id)
        if os.path.exists(path):
            os.remove(path)
