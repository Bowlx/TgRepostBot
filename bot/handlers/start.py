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

    # Check if LinkedIn app is configured (translator needs no setup)
    settings = await storage.get_all_settings()
    has_linkedin_app = bool(
        settings.get("linkedin_client_id")
        and settings.get("linkedin_client_secret")
        and settings.get("linkedin_redirect_uri")
    )
    has_linkedin_auth = bool(user.linkedin_access_token)

    if not has_linkedin_app:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🚀 Настроить бот", callback_data="setup:start")]
            ]
        )
        await message.answer(
            f"👋 Привет, <b>{message.from_user.full_name}</b>!\n\n"
            f"Я бот для кросспостинга из Telegram в LinkedIn с переводом.\n\n"
            f"⚠️ <b>Нужно настроить LinkedIn App.</b>\n"
            f"Нажмите кнопку ниже — я проведу вас пошагово (3 шага) 👇",
            reply_markup=keyboard,
        )
        return

    # All configured — show status
    welcome = (
        f"👋 Привет, <b>{message.from_user.full_name}</b>!\n\n"
        f"Я бот для кросспостинга из Telegram в LinkedIn с переводом.\n\n"
        f"<b>📋 Статус:</b>\n"
        f"🌐 Переводчик: MyMemory ✅\n"
        f"🆔 LinkedIn App: ✅\n"
        f"💼 LinkedIn аккаунт: {'✅ Подключён' if has_linkedin_auth else '❌ Не подключён'}\n"
        f"🔤 Перевод: {'✅ вкл' if user.translate_enabled else '⏸ off'} ({user.source_lang} → {user.target_lang})\n"
        f"🔔 Подтверждение постов: {'✅ вкл' if user.approve_enabled else '⏸ off'}\n\n"
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
            "• <code>/translate off</code> — отключить перевод\n"
            "• <code>/approve on</code> — подтверждение постов перед публикацией\n"
            "• <code>/setemail ваш@email</code> — поднять лимит переводов\n"
            "• <code>/setup</code> — перенастроить LinkedIn"
        )
        await message.answer(welcome)
