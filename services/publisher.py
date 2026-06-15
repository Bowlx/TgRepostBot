"""Single entry point that fans a post out to every connected+enabled destination."""
import logging
import os
import tempfile
from dataclasses import dataclass

from aiogram import Bot

from models import User
from services.linkedin import LinkedInClient
from services.instagram import InstagramClient

logger = logging.getLogger(__name__)


@dataclass
class DestResult:
    name: str   # "LinkedIn" / "Instagram"
    ok: bool           # True only when actually published
    detail: str
    skipped: bool = False  # paused / not connected / no media

    @property
    def icon(self) -> str:
        if self.skipped:
            return "⏸"
        return "✅" if self.ok else "❌"


class Publisher:
    def __init__(self, linkedin: LinkedInClient, instagram: InstagramClient, bot: Bot):
        self.linkedin = linkedin
        self.instagram = instagram
        self.bot = bot

    async def publish_to_all(
        self,
        user: User,
        text: str,
        photo_file_ids: list[str],
        li_enabled: bool | None = None,
        ig_enabled: bool | None = None,
    ) -> list[DestResult]:
        results: list[DestResult] = []

        # Per-post overrides default to the user's global toggles.
        if li_enabled is None:
            li_enabled = user.linkedin_enabled
        if ig_enabled is None:
            ig_enabled = user.instagram_enabled

        # Download each photo to a temp file ONCE; both destinations reuse the paths.
        temp_paths = await self._download_photos(photo_file_ids)
        try:
            results.append(await self._publish_linkedin(user, text, temp_paths, li_enabled))
            results.append(await self._publish_instagram(user, text, temp_paths, ig_enabled))
        finally:
            for path in temp_paths:
                try:
                    os.remove(path)
                except OSError:
                    pass
        return results

    async def _download_photos(self, photo_file_ids: list[str]) -> list[str]:
        paths: list[str] = []
        for file_id in photo_file_ids:
            try:
                file = await self.bot.get_file(file_id)
                downloaded = await self.bot.download_file(file.file_path)
                data = downloaded.read()
                fd, path = tempfile.mkstemp(suffix=".jpg")
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                paths.append(path)
            except Exception as e:
                logger.error(f"Failed to download photo {file_id}: {e}")
        return paths

    async def _publish_linkedin(
        self, user: User, text: str, photo_paths: list[str], enabled: bool
    ) -> DestResult:
        if not user.linkedin_access_token or not user.linkedin_person_urn:
            return DestResult("LinkedIn", False, "не подключён", skipped=True)
        if not enabled:
            return DestResult("LinkedIn", False, "пауза", skipped=True)

        image_urns: list[str] = []
        for path in photo_paths:
            try:
                with open(path, "rb") as f:
                    data = f.read()
                urn = await self.linkedin.upload_image_full(
                    user.linkedin_access_token, user.linkedin_person_urn, data
                )
                image_urns.append(urn)
            except Exception as e:
                logger.error(f"LinkedIn image upload failed: {e}")
        try:
            await self.linkedin.create_post(
                user.linkedin_access_token,
                user.linkedin_person_urn,
                text,
                image_urns or None,
            )
            return DestResult("LinkedIn", True, "опубликован")
        except Exception as e:
            return DestResult("LinkedIn", False, str(e))

    async def _publish_instagram(
        self, user: User, text: str, photo_paths: list[str], enabled: bool
    ) -> DestResult:
        ig_password_mode = bool(
            user.instagram_username and user.instagram_password_encrypted
        )
        ig_session_mode = bool(user.instagram_sessionid_encrypted)
        if not (ig_password_mode or ig_session_mode):
            return DestResult("Instagram", False, "не подключён", skipped=True)
        if not enabled:
            return DestResult("Instagram", False, "пауза", skipped=True)
        if not photo_paths:
            # Instagram has no text-only posts — skip gracefully.
            return DestResult("Instagram", False, "нет фото (требуется медиа)", skipped=True)

        try:
            media_id = await self.instagram.publish(
                user.user_id,
                user.instagram_username,
                user.instagram_password_encrypted,
                user.instagram_totp_secret_encrypted,
                user.instagram_sessionid_encrypted,
                text,
                photo_paths,
            )
            return DestResult("Instagram", True, f"опубликован ({media_id})")
        except Exception as e:
            return DestResult("Instagram", False, str(e))


def render_results(results: list[DestResult]) -> str:
    lines = []
    for r in results:
        lines.append(f"{r.icon} {r.name}: {r.detail}")
    return "\n".join(lines)
