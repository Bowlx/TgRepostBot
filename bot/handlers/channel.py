import logging

from aiogram import Router, types, Bot, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.media_group import MediaGroupAggregator, extract_group_content
from bot.text_format import format_text
from services.storage import Storage
from services.translator import Translator
from services.linkedin import LinkedInClient

router = Router()
logger = logging.getLogger(__name__)

# One aggregator per process: batches album messages into a single publication.
aggregator = MediaGroupAggregator(delay=1.0)

router.channel_post.filter(F.chat.type == "channel")


def approval_keyboard(approval_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"apv:{approval_id}:pub"),
                InlineKeyboardButton(text="✏️ Изменить", callback_data=f"apv:{approval_id}:edit"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"apv:{approval_id}:skip"),
            ]
        ]
    )


async def publish_to_linkedin(
    bot: Bot,
    linkedin_client: LinkedInClient,
    user_id: int,
    access_token: str,
    person_urn: str,
    text: str,
    photo_file_ids: list[str],
) -> None:
    """Upload images (if any) and create a LinkedIn post for one user."""
    image_asset_urns: list[str] = []
    for file_id in photo_file_ids:
        try:
            file = await bot.get_file(file_id)
            image_bytes = await bot.download_file(file.file_path)
            image_data = image_bytes.read()
            asset_urn = await linkedin_client.upload_image_full(access_token, person_urn, image_data)
            image_asset_urns.append(asset_urn)
        except Exception as e:
            logger.error(f"Image upload failed: {e}")

    try:
        await linkedin_client.create_post(access_token, person_urn, text, image_asset_urns or None)
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


@router.channel_post(F.text | F.photo)
async def handle_channel_post(
    message: types.Message,
    bot: Bot,
    storage: Storage,
    translator: Translator,
    linkedin_client: LinkedInClient,
) -> None:
    """Each message of an album is a separate update.
    Buffer them by media_group_id, then publish the whole group as ONE post
    (immediately, or via an approval message if /approve on).
    """

    async def publish_group(messages: list[types.Message]) -> None:
        original_text, photo_file_ids = extract_group_content(messages)
        if not original_text and not photo_file_ids:
            return

        users = await storage.get_all_linkedin_users()
        if not users:
            logger.warning("No users with LinkedIn connected, skipping channel post")
            return

        for user in users:
            # Translate (if enabled for this user)
            text = original_text
            if original_text.strip() and user.translate_enabled:
                try:
                    text = await translator.translate(
                        original_text, user.source_lang, user.target_lang
                    )
                except Exception as e:
                    logger.error(f"Translation failed for user {user.user_id}: {e}")
            text = format_text(text)

            if user.approve_enabled:
                # Approval gate: store and send a preview DM with buttons.
                approval_id = await storage.create_approval(
                    user.user_id, original_text, text, photo_file_ids
                )
                preview = (
                    f"🆕 <b>Новый пост из канала</b>\n\n"
                    f"{text}\n\n"
                )
                if photo_file_ids:
                    preview += f"🖼️ Изображений: {len(photo_file_ids)} шт.\n\n"
                preview += "Подтвердите публикацию в LinkedIn:"
                try:
                    await bot.send_message(
                        user.user_id,
                        preview,
                        reply_markup=approval_keyboard(approval_id),
                    )
                except Exception as e:
                    logger.error(f"Failed to send approval DM to {user.user_id}: {e}")
                    await storage.delete_approval(approval_id)
            else:
                # Auto-publish immediately.
                await publish_to_linkedin(
                    bot, linkedin_client, user.user_id,
                    user.linkedin_access_token, user.linkedin_person_urn,
                    text, photo_file_ids,
                )

    await aggregator.add(message, publish_group)
