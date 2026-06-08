from aiogram import Router, types
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from services.storage import Storage

router = Router()


@router.message(CommandStart())
async def cmd_start(message: types.Message, storage: Storage) -> None:
    user = await storage.get_user(message.from_user.id)
    if user is None:
        user = await storage.create_user(message.from_user.id)

    # Check if API keys are configured
    settings = await storage.get_all_settings()
    has_google = bool(settings.get("google_translate_api_key"))
    has_linkedin_app = bool(
        settings.get("linkedin_client_id")
        and settings.get("linkedin_client_secret")
        and settings.get("linkedin_redirect_uri")
    )
    has_linkedin_auth = bool(user.linkedin_access_token)

    if not has_google or not has_linkedin_app:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🚀 Настроить бот", callback_data="setup:start")]
            ]
        )
        await message.answer(
            f"👋 Привет, <b>{message.from_user.full_name}</b>!\n\n"
            f"Я бот для кросспостинга из Telegram в LinkedIn с переводом.\n\n"
            f"⚠️ <b>Бот ещё не настроен.</b> Нужно добавить API ключи.\n"
            f"Нажмите кнопку ниже — я проведу вас пошагово 👇",
            reply_markup=keyboard,
        )
        return

    # All configured — show status
    welcome = (
        f"👋 Привет, <b>{message.from_user.full_name}</b>!\n\n"
        f"Я бот для кросспостинга из Telegram в LinkedIn с переводом.\n\n"
        f"<b>📋 Статус:</b>\n"
        f"🔑 Google Translate: ✅\n"
        f"🆔 LinkedIn App: ✅\n"
        f"💼 LinkedIn аккаунт: {'✅ Подключён' if has_linkedin_auth else '❌ Не подключён'}\n"
        f"🔤 Перевод: {user.source_lang} → {user.target_lang}\n\n"
    )

    if not has_linkedin_auth:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔗 Подключить LinkedIn", callback_data="setup:go_auth")]
            ]
        )
        welcome += "Нажмите кнопку ниже для подключения LinkedIn 👇"
        await message.answer(welcome, reply_markup=keyboard)
    else:
        welcome += (
            "<b>Команды:</b>\n"
            "• Перешлите пост — перевод + превью\n"
            "• <code>/post</code> — опубликовать\n"
            "• <code>/setlang ru en</code> — сменить языки\n"
            "• <code>/setup</code> — перенастроить API ключи"
        )
        await message.answer(welcome)
