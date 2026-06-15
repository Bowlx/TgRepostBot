"""Control panel with colored inline buttons.

Each updatable state has one button whose color + emoji reflect its current
state (🟢/success = on, ⚪️ default = paused, ❌/danger = not connected).
Tapping a button toggles the state in place (the panel re-renders with the
new color). Connect/language buttons send a short instruction instead.

Note: Telegram's `style` button field ('success'/'danger'/'primary') is new and
may not render for all bots, so every button also carries an emoji indicator —
the state is always legible regardless of whether the color comes through.
"""
import logging

from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from services.storage import Storage
from services.linkedin import LinkedInClient

router = Router()
logger = logging.getLogger(__name__)


def _btn(text: str, data: str, style: str | None = None) -> InlineKeyboardButton:
    """Build one button, passing style through if given."""
    if style:
        return InlineKeyboardButton(text=text, callback_data=data, style=style)
    return InlineKeyboardButton(text=text, callback_data=data)


async def build_panel(storage: Storage, user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Render the control-panel text + keyboard for a user."""
    user = await storage.get_user(user_id)
    settings = await storage.get_all_settings()

    rows: list[list[InlineKeyboardButton]] = []

    # ── LinkedIn ────────────────────────────────────────────
    li_connected = bool(user.linkedin_access_token)
    if li_connected:
        if user.linkedin_enabled:
            rows.append([_btn("💼 LinkedIn: 🟢 вкл", "panel:li", "success")])
        else:
            rows.append([_btn("💼 LinkedIn: ⏸ пауза", "panel:li")])
    else:
        rows.append([_btn("💼 LinkedIn: ❌ подключить", "panel:li", "danger")])

    # ── Instagram ───────────────────────────────────────────
    ig_connected = bool(
        user.instagram_username or user.instagram_sessionid_encrypted
    )
    if ig_connected:
        if user.instagram_enabled:
            rows.append([_btn("📸 Instagram: 🟢 вкл", "panel:ig", "success")])
        else:
            rows.append([_btn("📸 Instagram: ⏸ пауза", "panel:ig")])
    else:
        rows.append([_btn("📸 Instagram: ❌ подключить", "panel:ig", "danger")])

    # ── Translation ─────────────────────────────────────────
    if user.translate_enabled:
        label = f"🔤 Перевод: 🟢 ({user.source_lang}→{user.target_lang})"
        rows.append([_btn(label, "panel:tr", "success")])
    else:
        rows.append([_btn("🔤 Перевод: ⏸ off", "panel:tr")])

    # ── Approval gate ───────────────────────────────────────
    if user.approve_enabled:
        rows.append([_btn("🔔 Подтверждение постов: 🟢", "panel:ap", "success")])
    else:
        rows.append([_btn("🔔 Подтверждение постов: ⏸ off", "panel:ap")])

    # ── Languages (action, not a toggle) ────────────────────
    rows.append([_btn(f"🌐 Сменить языки ({user.source_lang}→{user.target_lang})", "panel:lang")])

    # ── Refresh ─────────────────────────────────────────────
    rows.append([_btn("🔄 Обновить", "panel:refresh")])

    text = (
        "🎛 <b>Панель управления</b>\n\n"
        "Тап по кнопке меняет состояние. Цвет/эмодзи = текущий статус:\n"
        "🟢 вкл · ⏸ пауза · ❌ не подключено"
    )
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


async def _refresh(callback: types.CallbackQuery, storage: Storage) -> None:
    text, kb = await build_panel(storage, callback.from_user.id)
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception as e:
        # edit_text throws if the text is unchanged — harmless.
        logger.debug(f"panel refresh no-op: {e}")


@router.message(Command("menu"))
async def cmd_menu(message: types.Message, storage: Storage) -> None:
    text, kb = await build_panel(storage, message.from_user.id)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "panel:refresh")
async def cb_refresh(callback: types.CallbackQuery, storage: Storage) -> None:
    await _refresh(callback, storage)
    await callback.answer()


@router.callback_query(F.data == "panel:li")
async def cb_li(
    callback: types.CallbackQuery,
    storage: Storage,
    linkedin_client: LinkedInClient,
) -> None:
    user = await storage.get_user(callback.from_user.id)
    if user.linkedin_access_token:
        # Connected → toggle pause.
        await storage.set_linkedin_enabled(callback.from_user.id, not user.linkedin_enabled)
        await _refresh(callback, storage)
        await callback.answer()
        return

    # Not connected → guide to auth (or setup first).
    settings = await storage.get_all_settings()
    if settings.get("linkedin_client_id"):
        try:
            url = await linkedin_client.get_auth_url()
            kb = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="🔗 Подключить LinkedIn", url=url)]]
            )
            await callback.message.answer(
                "Нажмите кнопку, разрешите доступ, затем пришлите "
                "<code>/callback КОД</code> из URL редиректа:",
                reply_markup=kb,
            )
        except Exception as e:
            await callback.message.answer(f"❌ {e}")
    else:
        await callback.message.answer(
            "Сначала настройте LinkedIn App командой /setup (3 шага)."
        )
    await callback.answer()


@router.callback_query(F.data == "panel:ig")
async def cb_ig(callback: types.CallbackQuery, storage: Storage) -> None:
    user = await storage.get_user(callback.from_user.id)
    if user.instagram_username or user.instagram_sessionid_encrypted:
        # Connected → toggle pause.
        await storage.set_instagram_enabled(callback.from_user.id, not user.instagram_enabled)
        await _refresh(callback, storage)
        await callback.answer()
        return

    # Not connected → offer both login methods.
    await callback.message.answer(
        "Подключить Instagram одним из способов:\n\n"
        "• <code>/iglogin логин пароль [totp]</code> — по логину/паролю\n"
        "• <code>/igsession КУКА</code> — по sessionid из браузера (без пароля)"
    )
    await callback.answer()


@router.callback_query(F.data == "panel:tr")
async def cb_tr(callback: types.CallbackQuery, storage: Storage) -> None:
    user = await storage.get_user(callback.from_user.id)
    await storage.set_translate_enabled(callback.from_user.id, not user.translate_enabled)
    await _refresh(callback, storage)
    await callback.answer()


@router.callback_query(F.data == "panel:ap")
async def cb_ap(callback: types.CallbackQuery, storage: Storage) -> None:
    user = await storage.get_user(callback.from_user.id)
    await storage.set_approve_enabled(callback.from_user.id, not user.approve_enabled)
    await _refresh(callback, storage)
    await callback.answer()


@router.callback_query(F.data == "panel:lang")
async def cb_lang(callback: types.CallbackQuery) -> None:
    await callback.message.answer(
        "Отправьте команду вида:\n"
        "<code>/setlang ru en</code>\n\n"
        "(исходный язык, целевой язык)"
    )
    await callback.answer()
