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
        cl = await self._get_client(
            user_id, username, password, totp_secret, sessionid=None
        )
        cl.dump_settings(self.session_path(user_id))

    async def login_by_sessionid(self, user_id: int, sessionid: str) -> str:
        """Login via the browser sessionid cookie. Returns the account username."""
        cl = await self._get_client(
            user_id, username=None, password=None, totp_secret=None, sessionid=sessionid
        )
        cl.dump_settings(self.session_path(user_id))

        def _fetch_username():
            return cl.user_info(cl.user_id).username

        return await asyncio.to_thread(_fetch_username)

    async def _get_client(
        self,
        user_id: int,
        username: Optional[str],
        password: Optional[str],
        totp_secret: Optional[str],
        sessionid: Optional[str] = None,
    ) -> Client:
        """Load a logged-in client, reusing the session file.

        Two login modes: sessionid cookie (no password) or username+password
        (with optional TOTP). Picks based on which credential is provided.
        """
        loop = asyncio.get_running_loop()

        def challenge_handler(uname, choice):
            # Runs inside the worker thread. Delegate to the async ask_code,
            # which owns the pending-code future + FSM state and returns the
            # code string. Do NOT create a future here — single owner.
            if self.ask_code is None:
                return ""
            try:
                return asyncio.run_coroutine_threadsafe(
                    self.ask_code(user_id, choice), loop
                ).result(timeout=300)
            except Exception as e:
                logger.error(f"Instagram challenge code not provided: {e}")
                return ""

        def _build():
            cl = Client()
            cl.challenge_code_handler = challenge_handler
            path = self.session_path(user_id)
            if os.path.exists(path):
                cl.set_settings(cl.load_settings(path))
            if sessionid:
                cl.login_by_sessionid(sessionid)
            else:
                # instagrapi calls verification_code.strip() on its 2FA branch —
                # pass "" (its default), never None, or a 2FA account crashes.
                verification = pyotp.TOTP(totp_secret).now() if totp_secret else ""
                cl.login(username, password, verification_code=verification)
            return cl

        return await asyncio.to_thread(_build)

    async def publish(
        self,
        user_id: int,
        username: Optional[str],
        password_enc: Optional[str],
        totp_secret_enc: Optional[str],
        sessionid_enc: Optional[str],
        caption: str,
        image_paths: list[str],
    ) -> str:
        """Publish a photo or carousel. Returns the media id (str)."""
        password = self.crypto.decrypt(password_enc) if password_enc else None
        totp_secret = (
            self.crypto.decrypt(totp_secret_enc) if totp_secret_enc else None
        )
        sessionid = self.crypto.decrypt(sessionid_enc) if sessionid_enc else None

        cl = await self._get_client(
            user_id, username, password, totp_secret, sessionid
        )

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
            cl = await self._get_client(
                user_id, username, password, totp_secret, sessionid
            )
            return await asyncio.to_thread(_upload)

    async def logout(self, user_id: int) -> None:
        path = self.session_path(user_id)
        if os.path.exists(path):
            os.remove(path)
