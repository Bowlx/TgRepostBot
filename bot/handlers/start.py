from aiogram import Router, types
from aiogram.filters import CommandStart

from config import Settings
from services.storage import Storage

router = Router()


@router.message(CommandStart())
async def cmd_start(
    message: types.Message,
    storage: Storage,
    app_config: Settings,
) -> None:
    user = await storage.get_user(message.from_user.id)
    if user is None:
        user = await storage.create_user(
            message.from_user.id,
            source_lang=app_config.default_source_lang,
            target_lang=app_config.default_target_lang,
        )

    welcome = (
        f"👋 Привет, <b>{message.from_user.full_name}</b>!\n\n"
        f"Я бот для кросспостинга из Telegram в LinkedIn с переводом.\n\n"
        f"<b>Как пользоваться:</b>\n"
        f"1. <code>/auth</code> — подключить LinkedIn\n"
        f"2. <code>/setlang ru en</code> — настроить языки перевода\n"
        f"3. Перешли мне пост или добавь меня в канал\n\n"
        f"<b>Текущие настройки:</b>\n"
        f"🔤 Перевод: {user.source_lang} → {user.target_lang}\n"
        f"💼 LinkedIn: {'✅ Подключён' if user.linkedin_access_token else '❌ Не подключён'}"
    )
    await message.answer(welcome)
