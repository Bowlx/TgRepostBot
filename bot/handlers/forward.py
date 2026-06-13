from aiogram import Router, types, F

from bot.media_group import MediaGroupAggregator, extract_group_content
from services.storage import Storage
from services.translator import Translator

router = Router()

# One aggregator per process: batches album forwards into a single pending post.
aggregator = MediaGroupAggregator(delay=1.0)

# Only handle private messages
router.message.filter(F.chat.type == "private")


@router.message(F.forward_date | (F.photo & ~F.forward_date))
async def handle_forwarded(
    message: types.Message,
    storage: Storage,
    translator: Translator,
) -> None:
    """Each message of an album is a separate forward.
    Buffer them by media_group_id, then show a single preview / pending post.
    """

    async def process_group(messages: list[types.Message]) -> None:
        # Skip commands that slipped through (e.g. "/post")
        if any(m.text and m.text.startswith("/") for m in messages):
            return

        text, photo_file_ids = extract_group_content(messages)
        if not text and not photo_file_ids:
            await message.answer("❌ Не удалось извлечь контент из сообщения.")
            return

        user = await storage.get_user(message.from_user.id)
        if user is None:
            await message.answer("Сначала нажмите /start")
            return

        # Translate text (only if enabled for this user)
        translated_text = text
        if text.strip() and user.translate_enabled:
            try:
                translated_text = await translator.translate(
                    text, user.source_lang, user.target_lang
                )
            except Exception as e:
                await message.answer(
                    f"⚠️ Ошибка перевода: {e}\n\nПост будет опубликован без перевода."
                )

        # Store as a single pending post (whole album combined)
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

    await aggregator.add(message, process_group)
