import logging

from aiogram import Router, types, Bot, F

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

    users = await storage.get_all_linkedin_users()
    if not users:
        logger.warning("No users with LinkedIn connected, skipping channel post")
        return

    for user in users:
        translated_text = text
        if text.strip():
            try:
                translated_text = await translator.translate(text, user.source_lang, user.target_lang)
            except Exception as e:
                logger.error(f"Translation failed for user {user.user_id}: {e}")

        image_asset_urns: list[str] = []
        for file_id in photo_file_ids:
            try:
                file = await bot.get_file(file_id)
                image_bytes = await bot.download_file(file.file_path)
                image_data = image_bytes.read()
                asset_urn = await linkedin_client.upload_image_full(
                    user.linkedin_access_token, user.linkedin_person_urn, image_data
                )
                image_asset_urns.append(asset_urn)
            except Exception as e:
                logger.error(f"Image upload failed: {e}")

        try:
            await linkedin_client.create_post(
                user.linkedin_access_token, user.linkedin_person_urn, translated_text, image_asset_urns or None
            )
            logger.info(f"Channel post published to LinkedIn for user {user.user_id}")
        except Exception as e:
            logger.error(f"LinkedIn post failed for user {user.user_id}: {e}")
            try:
                await bot.send_message(
                    user.user_id,
                    f"❌ Ошибка публикации в LinkedIn: {e}\nВозможно, нужно переподключить: /auth",
                )
            except Exception:
                pass
