import logging

from aiogram import Router, types, Bot, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.media_group import MediaGroupAggregator, extract_group_content
from bot.text_format import format_text
from services.storage import Storage
from services.translator import Translator
from services.publisher import Publisher, render_results

router = Router()
logger = logging.getLogger(__name__)

aggregator = MediaGroupAggregator(delay=1.0)

router.channel_post.filter(F.chat.type == "channel")


@router.channel_post(F.text | F.photo)
async def handle_channel_post(
    message: types.Message,
    bot: Bot,
    storage: Storage,
    translator: Translator,
    publisher: Publisher,
) -> None:
    """Buffer album messages, then publish the whole group as ONE post
    (immediately, or via an approval message if /approve on)."""

    async def publish_group(messages: list[types.Message]) -> None:
        original_text, photo_file_ids = extract_group_content(messages)
        if not original_text and not photo_file_ids:
            return

        users = await storage.get_all_active_users()
        if not users:
            logger.warning("No users with a connected destination, skipping channel post")
            return

        for user in users:
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
                approval_id = await storage.create_approval(
                    user.user_id, original_text, text, photo_file_ids
                )
                approval = await storage.get_approval(approval_id)
                from bot.handlers.preview_ui import preview_text, preview_keyboard
                try:
                    await bot.send_message(
                        user.user_id,
                        preview_text(approval, "a"),
                        reply_markup=preview_keyboard("a", approval_id, approval.active_mode),
                    )
                except Exception as e:
                    logger.error(f"Failed to send approval DM to {user.user_id}: {e}")
                    await storage.delete_approval(approval_id)
            else:
                results = await publisher.publish_to_all(user, text, photo_file_ids)
                try:
                    await bot.send_message(
                        user.user_id,
                        "📋 <b>Опубликовано:</b>\n" + render_results(results),
                    )
                except Exception:
                    pass

    await aggregator.add(message, publish_group)
