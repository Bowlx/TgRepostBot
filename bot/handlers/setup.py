from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from services.storage import Storage

router = Router()


# ── FSM States ─────────────────────────────────────────────

class SetupStates(StatesGroup):
    waiting_linkedin_client_id = State()
    waiting_linkedin_client_secret = State()
    waiting_linkedin_redirect_uri = State()


# ── Status checker ─────────────────────────────────────────

async def get_setup_status(storage: Storage) -> dict[str, bool]:
    settings = await storage.get_all_settings()
    return {
        "linkedin_client_id": bool(settings.get("linkedin_client_id")),
        "linkedin_client_secret": bool(settings.get("linkedin_client_secret")),
        "linkedin_redirect_uri": bool(settings.get("linkedin_redirect_uri")),
    }


def build_status_text(status: dict[str, bool]) -> str:
    lines = ["<b>⚙️ Состояние настройки:</b>\n"]
    lines.append("🌐 <b>Переводчик:</b> MyMemory (бесплатно, без ключа) ✅")
    labels = {
        "linkedin_client_id": "🆔 LinkedIn Client ID",
        "linkedin_client_secret": "🔐 LinkedIn Client Secret",
        "linkedin_redirect_uri": "🔗 LinkedIn Redirect URI",
    }
    for key, label in labels.items():
        icon = "✅" if status[key] else "❌"
        lines.append(f"  {icon} {label}")

    all_done = all(status.values())
    if all_done:
        lines.append("\n🎉 <b>Всё настроено!</b> Можно подключить LinkedIn: /auth")
    else:
        lines.append("\n💡 Нажмите кнопку ниже для пошаговой настройки")
    return "\n".join(lines)


# ── /setup command ─────────────────────────────────────────

@router.message(Command("setup"))
async def cmd_setup(message: types.Message, storage: Storage) -> None:
    status = await get_setup_status(storage)
    text = build_status_text(status)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Начать настройку", callback_data="setup:start")],
            [InlineKeyboardButton(text="🔄 Сбросить все настройки", callback_data="setup:reset")],
        ]
    )
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data == "setup:start")
async def callback_setup_start(callback: types.CallbackQuery, storage: Storage, state: FSMContext) -> None:
    status = await get_setup_status(storage)

    if not status["linkedin_client_id"]:
        await _ask_linkedin_client_id(callback.message, state)
    elif not status["linkedin_client_secret"]:
        await _ask_linkedin_client_secret(callback.message, state)
    elif not status["linkedin_redirect_uri"]:
        await _ask_linkedin_redirect_uri(callback.message, state)
    else:
        await callback.message.edit_text("🎉 Все настройки заполнены!\n\nТеперь: /auth — подключить LinkedIn")

    await callback.answer()


# ── Step handlers ──────────────────────────────────────────

async def _ask_linkedin_client_id(message: types.Message, state: FSMContext) -> None:
    await state.set_state(SetupStates.waiting_linkedin_client_id)
    await message.answer(
        "<b>Шаг 1 из 3: LinkedIn Client ID</b>\n\n"
        "1. Откройте <a href='https://www.linkedin.com/developers/'>LinkedIn Developers</a>\n"
        "2. Нажмите <b>Create App</b> → заполните данные\n"
        "3. В разделе <b>Settings</b> — подтвердите приложение (Verify)\n"
        "4. В разделе <b>Products</b> включите ОБА:\n"
        "   • <b>Share on LinkedIn</b>\n"
        "   • <b>Sign In with LinkedIn using OpenID Connect</b>\n"
        "5. Скопируйте <b>Client ID</b> из раздела <b>Auth</b> и отправьте сюда:",
        disable_web_page_preview=True,
    )


@router.message(SetupStates.waiting_linkedin_client_id)
async def process_linkedin_client_id(message: types.Message, storage: Storage, state: FSMContext) -> None:
    value = message.text.strip()
    await storage.set_setting("linkedin_client_id", value)
    await message.answer("✅ LinkedIn Client ID сохранён!")
    await _ask_linkedin_client_secret(message, state)


async def _ask_linkedin_client_secret(message: types.Message, state: FSMContext) -> None:
    await state.set_state(SetupStates.waiting_linkedin_client_secret)
    await message.answer(
        "<b>Шаг 2 из 3: LinkedIn Client Secret</b>\n\n"
        "Скопируйте <b>Client Secret</b> из раздела <b>Auth</b> вашего LinkedIn App\n"
        "и отправьте сюда:"
    )


@router.message(SetupStates.waiting_linkedin_client_secret)
async def process_linkedin_client_secret(message: types.Message, storage: Storage, state: FSMContext) -> None:
    value = message.text.strip()
    await storage.set_setting("linkedin_client_secret", value)
    await message.answer("✅ LinkedIn Client Secret сохранён!")
    await _ask_linkedin_redirect_uri(message, state)


async def _ask_linkedin_redirect_uri(message: types.Message, state: FSMContext) -> None:
    await state.set_state(SetupStates.waiting_linkedin_redirect_uri)
    await message.answer(
        "<b>Шаг 3 из 3: LinkedIn Redirect URI</b>\n\n"
        "В разделе <b>Auth</b> вашего LinkedIn App добавьте Redirect URL,\n"
        "затем отправьте его сюда.\n\n"
        "<i>Пример: https://your-domain.com/callback</i>\n"
        "<i>Или просто: https://localhost</i> (для тестирования)"
    )


@router.message(SetupStates.waiting_linkedin_redirect_uri)
async def process_linkedin_redirect_uri(message: types.Message, storage: Storage, state: FSMContext) -> None:
    value = message.text.strip()
    if not value.startswith("http"):
        await message.answer("❌ URL должен начинаться с http:// или https://\nПопробуйте ещё раз:")
        return

    await storage.set_setting("linkedin_redirect_uri", value)
    await state.clear()

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Подключить LinkedIn", callback_data="setup:go_auth")]
        ]
    )
    await message.answer(
        "✅ LinkedIn Redirect URI сохранён!\n\n"
        "🎉 <b>Всё настроено!</b>\n\n"
        "Теперь нужно подключить ваш LinkedIn аккаунт.\n"
        "Нажмите кнопку ниже или используйте /auth",
        reply_markup=keyboard,
    )


# ── Reset ──────────────────────────────────────────────────

@router.callback_query(F.data == "setup:reset")
async def callback_setup_reset(callback: types.CallbackQuery, storage: Storage) -> None:
    for key in [
        "linkedin_client_id",
        "linkedin_client_secret",
        "linkedin_redirect_uri",
    ]:
        await storage.set_setting(key, "")

    await callback.message.edit_text(
        "🗑️ <b>Все настройки сброшены.</b>\n\n"
        "Начните заново: /setup"
    )
    await callback.answer()


# ── Navigate to /auth ──────────────────────────────────────

@router.callback_query(F.data == "setup:go_auth")
async def callback_go_auth(callback: types.CallbackQuery) -> None:
    await callback.message.answer("Используйте команду /auth для подключения LinkedIn")
    await callback.answer()
