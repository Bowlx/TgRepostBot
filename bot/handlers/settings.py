from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import Settings
from services.storage import Storage
from services.linkedin import LinkedInClient

router = Router()


@router.message(Command("setlang"))
async def cmd_setlang(message: types.Message, storage: Storage) -> None:
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer(
            "❌ Использование: <code>/setlang source target</code>\n"
            "Пример: <code>/setlang ru en</code>"
        )
        return

    source_lang, target_lang = parts[1].lower(), parts[2].lower()
    user = await storage.get_user(message.from_user.id)
    if user is None:
        await message.answer("Сначала нажмите /start")
        return

    await storage.update_languages(message.from_user.id, source_lang, target_lang)
    await message.answer(f"✅ Языки перевода обновлены: <b>{source_lang} → {target_lang}</b>")


@router.message(Command("auth"))
async def cmd_auth(message: types.Message, linkedin_client: LinkedInClient) -> None:
    auth_url = linkedin_client.get_auth_url()
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Подключить LinkedIn", url=auth_url)]
        ]
    )
    await message.answer(
        "Для подключения LinkedIn:\n\n"
        "1. Нажмите кнопку ниже\n"
        "2. Разрешите доступ\n"
        "3. Скопируйте код из URL редиректа\n"
        "4. Отправьте: <code>/callback ВАШ_КОД</code>",
        reply_markup=keyboard,
    )


@router.message(Command("callback"))
async def cmd_callback(
    message: types.Message,
    storage: Storage,
    linkedin_client: LinkedInClient,
) -> None:
    parts = message.text.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("❌ Использование: <code>/callback КОД_ИЗ_URL</code>")
        return

    code = parts[1].strip()
    await message.answer("⏳ Обмениваю код на токен...")

    try:
        access_token, person_urn = await linkedin_client.exchange_code(code)
        await storage.update_linkedin_token(message.from_user.id, access_token, person_urn)
        await message.answer("✅ LinkedIn успешно подключён!")
    except Exception as e:
        await message.answer(f"❌ Ошибка авторизации: {e}\nПопробуйте снова: /auth")
