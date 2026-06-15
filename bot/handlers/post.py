import logging

from aiogram import Router, types, Bot
from aiogram.filters import Command

from services.storage import Storage
from services.publisher import Publisher, render_results

router = Router()
logger = logging.getLogger(__name__)


@router.message(Command("preview"))
async def cmd_preview(message: types.Message, storage: Storage) -> None:
    pending = await storage.get_pending_post(message.from_user.id)
    if pending is None:
        await message.answer("❌ Нет отложенного поста. Перешлите сообщение боту.")
        return
    user = await storage.get_user(message.from_user.id)

    from bot.handlers.preview_ui import preview_text, preview_keyboard
    await message.answer(
        preview_text(pending, "m"),
        reply_markup=preview_keyboard("m", message.from_user.id, pending, user),
    )


@router.message(Command("post"))
async def cmd_post(
    message: types.Message,
    bot: Bot,
    storage: Storage,
    publisher: Publisher,
) -> None:
    """Publish the pending post's active text to all destinations."""
    pending = await storage.get_pending_post(message.from_user.id)
    if pending is None:
        await message.answer("❌ Нет отложенного поста. Перешлите сообщение боту.")
        return

    user = await storage.get_user(message.from_user.id)
    connected = (
        user is not None
        and (user.linkedin_access_token or user.instagram_username or user.instagram_sessionid_encrypted)
    )
    if not connected:
        await message.answer("❌ Нет подключённых destination. Откройте /start")
        return

    await message.answer("⏳ Публикую...")

    results = await publisher.publish_to_all(
        user,
        pending.active_text or pending.translated_text,
        pending.photo_file_ids,
        li_enabled=pending.li_enabled,
        ig_enabled=pending.ig_enabled,
    )

    if any(r.ok for r in results):
        await storage.delete_pending_post(message.from_user.id)
        await message.answer("✅ Готово!\n" + render_results(results))
    else:
        await message.answer(
            "❌ Ни один destination не сработал:\n" + render_results(results)
        )


@router.message(Command("skip"))
async def cmd_skip(message: types.Message, storage: Storage) -> None:
    deleted = await storage.get_pending_post(message.from_user.id)
    if deleted is None:
        await message.answer("❌ Нет отложенного поста для отмены.")
        return
    await storage.delete_pending_post(message.from_user.id)
    await message.answer("🗑️ Пост отменён.")
