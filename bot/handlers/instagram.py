"""Instagram connect/disconnect commands and the SMS/email 2FA code FSM.

The /iglogin message is deleted immediately so the password never lingers in
chat history. If a login triggers an SMS/email challenge, the instagrapi
challenge handler calls ask_code(), which prompts the user and waits on the
InstagramClient's pending-code future; the FSM handler below resolves it.
"""
import asyncio
import logging

from aiogram import Router, types, Bot, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from services.crypto import Crypto
from services.instagram import InstagramClient
from services.storage import Storage

router = Router()
logger = logging.getLogger(__name__)


class IgChallenge(StatesGroup):
    waiting_code = State()


def _make_ask_code(bot: Bot, instagram: InstagramClient, state: FSMContext):
    """Builds the async ask_code callback the InstagramClient uses for 2FA.

    ask_code owns the pending-code future AND sets the FSM state so the user's
    reply is routed to receive_ig_code below. Single future owner — the client's
    challenge_handler just delegates here.
    """
    async def ask_code(user_id: int, choice) -> str:
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        instagram._pending_codes[user_id] = fut
        # Set FSM state so the user's code reply reaches receive_ig_code.
        await state.set_state(IgChallenge.waiting_code)
        await bot.send_message(
            user_id,
            "🔐 Instagram запросил код подтверждения (SMS/email).\n"
            "Отправьте код сюда в течение 5 минут:",
        )
        try:
            return await asyncio.wait_for(fut, timeout=300)
        except asyncio.TimeoutError:
            return ""
        finally:
            instagram._pending_codes.pop(user_id, None)
            await state.clear()
    return ask_code


@router.message(F.text.startswith("/iglogin"))
async def cmd_iglogin(
    message: types.Message,
    bot: Bot,
    state: FSMContext,
    storage: Storage,
    instagram_client: InstagramClient,
    crypto: Crypto,
) -> None:
    # /iglogin <username> <password> [totp_secret]
    parts = message.text.split(maxsplit=3)
    if len(parts) < 3:
        await message.answer(
            "❌ Использование: <code>/iglogin логин пароль [totp_секрет]</code>\n\n"
            "TOTP-секрет — опционально, только если включена 2FA через приложение "
            "(Authenticator). Это base32-секрет из QR-кода."
        )
        return

    username = parts[1]
    password = parts[2]
    totp_secret = parts[3].strip() if len(parts) == 4 else None

    # Delete the message so the password doesn't stay in chat history.
    try:
        await message.delete()
    except Exception:
        pass

    # Ensure the user exists.
    if await storage.get_user(message.from_user.id) is None:
        await storage.create_user(message.from_user.id)

    status = await bot.send_message(message.from_user.id, "⏳ Вхожу в Instagram...")

    # Wire up the interactive 2FA code prompt (single-user bot: ask_code is a
    # per-process attribute; concurrent multi-user logins would clobber it).
    instagram_client.ask_code = _make_ask_code(bot, instagram_client, state)

    try:
        await instagram_client.login(message.from_user.id, username, password, totp_secret)
    except Exception as e:
        logger.error(f"Instagram login failed: {e}")
        await status.edit_text(f"❌ Ошибка входа в Instagram: {e}")
        return
    finally:
        await state.clear()

    enc_password = crypto.encrypt(password)
    enc_totp = crypto.encrypt(totp_secret) if totp_secret else None
    await storage.set_instagram_creds(message.from_user.id, username, enc_password, enc_totp)
    await status.edit_text(
        f"✅ Instagram подключён: <b>@{username}</b>\n"
        f"Публикация включена. Выключить: <code>/instagram off</code>"
    )


@router.message(F.text.startswith("/iglogout"))
async def cmd_iglogout(
    message: types.Message,
    storage: Storage,
    instagram_client: InstagramClient,
) -> None:
    user = await storage.get_user(message.from_user.id)
    if user is None or not user.instagram_username:
        await message.answer("Instagram не подключён.")
        return
    await instagram_client.logout(message.from_user.id)
    await storage.clear_instagram_creds(message.from_user.id)
    await message.answer("✅ Instagram отключён (креды и сессия удалены).")


# ── 2FA code FSM handler ───────────────────────────────────

@router.message(IgChallenge.waiting_code, F.text)
async def receive_ig_code(message: types.Message, instagram_client: InstagramClient) -> None:
    code = message.text.strip()
    # The pending future lives on the client; resolve it so ask_code() unblocks.
    delivered = instagram_client.submit_code(message.from_user.id, code)
    if delivered:
        await message.answer("Код передан, продолжаю вход...")
    else:
        await message.answer("⚠️ Запрос кода уже не активен. Попробуйте /iglogin снова.")
