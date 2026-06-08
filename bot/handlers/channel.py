import asyncio
import logging

from aiogram import Router, types, Bot
from aiogram.filters import F

from config import Settings
from services.storage import Storage
from services.translator import Translator
from services.linkedin import LinkedInClient

router = Router()
logger = logging.getLogger(__name__)

router.channel_post.filter(F.chat.type == "channel")


@router.channel_post(F.text | F.photo)
async def handle_channel_post(
    message: types.Message,
    bot: Bot,
    storage: Storage,
    translator: Translator,
    linkedin_client: LinkedInClient,
) -> None:
    text = message.text or message.caption or ""

    photo_file_ids: list[str] = []
    if message.photo:
        photo_file_ids = [message.photo[-1].file_id]

    if not text and not photo_file_ids:
        return

    import aiosqlite

    async with aiosqlite.connect(storage.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE linkedin_access_token IS NOT NULL"
        )
        rows = await cursor.fetchall()

    if not rows:
        logger.warning("No users with LinkedIn connected, skipping channel post")
        return

    for row in rows:
        user_id = row["user_id"]
        source_lang = row["source_lang"]
        target_lang = row["target_lang"]
        access_token = row["linkedin_access_token"]
        person_urn = row["linkedin_person_urn"]

        translated_text = text
        if text.strip():
            try:
                translated_text = await translator.translate(text, source_lang, target_lang)
            except Exception as e:
                logger.error(f"Translation failed for user {user_id}: {e}")

        image_asset_urns: list[str] = []
        for file_id in photo_file_ids:
            try:
                file = await bot.get_file(file_id)
                image_bytes = await bot.download_file(file.file_path)
                image_data = image_bytes.read()
                asset_urn = await linkedin_client.upload_image_full(
                    access_token, person_urn, image_data
                )
                image_asset_urns.append(asset_urn)
            except Exception as e:
                logger.error(f"Image upload failed: {e}")

        try:
            await linkedin_client.create_post(
                access_token, person_urn, translated_text, image_asset_urns or None
            )
            logger.info(f"Channel post published to LinkedIn for user {user_id}")
        except Exception as e:
            logger.error(f"LinkedIn post failed for user {user_id}: {e}")
            try:
                await bot.send_message(
                    user_id,
                    f"❌ Ошибка публикации в LinkedIn: {e}\nВозможно, нужно переподключить: /auth",
                )
            except Exception:
                pass
