import logging

from aiogram import Router, types, Bot
from aiogram.filters import Command

from services.storage import Storage
from services.linkedin import LinkedInClient

router = Router()
logger = logging.getLogger(__name__)


@router.message(Command("preview"))
async def cmd_preview(message: types.Message, storage: Storage) -> None:
    pending = await storage.get_pending_post(message.from_user.id)
    if pending is None:
        await message.answer("❌ Нет отложенного поста. Перешлите сообщение боту.")
        return

    text = (
        f"<b>📋 Оригинал:</b>\n{pending.original_text}\n\n"
        f"<b>🌐 Перевод:</b>\n{pending.translated_text}\n\n"
    )
    if pending.photo_file_ids:
        text += f"🖼️ Изображений: {len(pending.photo_file_ids)} шт.\n\n"
    text += "<code>/post</code> — опубликовать\n<code>/skip</code> — отменить"
    await message.answer(text)


@router.message(Command("post"))
async def cmd_post(
    message: types.Message,
    bot: Bot,
    storage: Storage,
    linkedin_client: LinkedInClient,
) -> None:
    pending = await storage.get_pending_post(message.from_user.id)
    if pending is None:
        await message.answer("❌ Нет отложенного поста. Перешлите сообщение боту.")
        return

    user = await storage.get_user(message.from_user.id)
    if user is None or not user.linkedin_access_token:
        await message.answer("❌ LinkedIn не подключён. Используйте /auth")
        return

    await message.answer("⏳ Публикую в LinkedIn...")

    image_asset_urns: list[str] = []
    for file_id in pending.photo_file_ids:
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
            await message.answer(f"⚠️ Не удалось загрузить изображение: {e}")

    try:
        await linkedin_client.create_post(
            user.linkedin_access_token,
            user.linkedin_person_urn,
            pending.translated_text,
            image_asset_urns or None,
        )
        await storage.delete_pending_post(message.from_user.id)
        await message.answer("✅ Пост опубликован в LinkedIn!")
    except Exception as e:
        logger.error(f"LinkedIn post creation failed: {e}")
        await message.answer(
            f"❌ Ошибка публикации: {e}\n\n"
            "Возможно, токен истёк. Попробуйте: /auth"
        )


@router.message(Command("skip"))
async def cmd_skip(message: types.Message, storage: Storage) -> None:
    deleted = await storage.get_pending_post(message.from_user.id)
    if deleted is None:
        await message.answer("❌ Нет отложенного поста для отмены.")
        return
    await storage.delete_pending_post(message.from_user.id)
    await message.answer("🗑️ Пост отменён.")
