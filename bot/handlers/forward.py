from aiogram import Router, types, F

from services.storage import Storage
from services.translator import Translator

router = Router()

# Only handle private messages
router.message.filter(F.chat.type == "private")


@router.message(F.forward_date | (F.photo & ~F.forward_date))
async def handle_forwarded(
    message: types.Message,
    storage: Storage,
    translator: Translator,
) -> None:
    user = await storage.get_user(message.from_user.id)
    if user is None:
        await message.answer("Сначала нажмите /start")
        return

    # Extract text
    text = message.text or message.caption or ""

    # Extract photo file IDs
    photo_file_ids: list[str] = []
    if message.photo:
        # Get the largest photo size
        photo_file_ids = [message.photo[-1].file_id]

    if not text and not photo_file_ids:
        await message.answer("❌ Не удалось извлечь контент из сообщения.")
        return

    # Translate text
    translated_text = text
    if text.strip():
        try:
            translated_text = await translator.translate(text, user.source_lang, user.target_lang)
        except Exception as e:
            await message.answer(f"⚠️ Ошибка перевода: {e}\n\nПост будет опубликован без перевода.")

    # Store as pending post
    await storage.save_pending_post(
        user_id=message.from_user.id,
        original_text=text,
        translated_text=translated_text,
        photo_file_ids=photo_file_ids,
    )

    preview = (
        f"<b>📋 Превью поста:</b>\n\n"
        f"{translated_text}\n\n"
        f"{'🖼️ Изображения: ' + str(len(photo_file_ids)) + ' шт.' if photo_file_ids else ''}\n\n"
        f"<code>/post</code> — опубликовать\n"
        f"<code>/skip</code> — отменить"
    )
    await message.answer(preview)
