from aiogram import Router, types
from aiogram.filters import CommandStart

from services.storage import Storage

router = Router()


@router.message(CommandStart())
async def cmd_start(message: types.Message, storage: Storage) -> None:
    user = await storage.get_user(message.from_user.id)
    if user is None:
        user = await storage.create_user(message.from_user.id)

    from bot.handlers.panel import build_panel
    panel_text, kb = await build_panel(storage, message.from_user.id)

    await message.answer(
        f"👋 Привет, <b>{message.from_user.full_name}</b>!\n\n"
        f"Я бот для кросспостинга из Telegram в LinkedIn и Instagram (с переводом).\n\n"
        f"{panel_text}",
        reply_markup=kb,
    )
