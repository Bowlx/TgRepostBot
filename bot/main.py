import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from bot.handlers import start, settings, channel, forward, post, setup, instagram, panel, preview_ui
from config import get_settings
from services.storage import Storage
from services.translator import Translator
from services.linkedin import LinkedInClient
from services.crypto import Crypto
from services.instagram import InstagramClient
from services.publisher import Publisher

logger = logging.getLogger(__name__)


async def service_middleware(handler, event, data):
    dp = data["dispatcher"]
    data["storage"] = dp["storage"]
    data["translator"] = dp["translator"]
    data["linkedin_client"] = dp["linkedin"]
    data["instagram_client"] = dp["instagram"]
    data["publisher"] = dp["publisher"]
    data["crypto"] = dp["crypto"]
    data["app_config"] = dp["config"]
    return await handler(event, data)


async def _setup_bot_menu(bot: Bot) -> None:
    """Register the Telegram command menu (the "/" dropdown) + profile text."""
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Статус и помощь"),
            BotCommand(command="menu", description="🎛 Панель управления"),
            BotCommand(command="post", description="Опубликовать пост"),
            BotCommand(command="preview", description="Превью поста"),
            BotCommand(command="skip", description="Отменить пост"),
            BotCommand(command="destinations", description="Куда публикуем"),
            BotCommand(command="translate", description="Перевод вкл/выкл"),
            BotCommand(command="approve", description="Подтверждение постов вкл/выкл"),
            BotCommand(command="linkedin", description="LinkedIn вкл/выкл"),
            BotCommand(command="instagram", description="Instagram вкл/выкл"),
            BotCommand(command="setlang", description="Языки перевода (ru en)"),
            BotCommand(command="iglogin", description="Подключить Instagram"),
            BotCommand(command="igsession", description="Instagram по sessionid"),
            BotCommand(command="iglogout", description="Отключить Instagram"),
            BotCommand(command="auth", description="Подключить LinkedIn"),
            BotCommand(command="setup", description="Настроить LinkedIn App"),
        ]
    )
    await bot.set_my_short_description(
        "Кросспостинг из Telegram в LinkedIn и Instagram (перевод опционален)."
    )
    await bot.set_my_description(
        "Пересылайте посты — бот опубликует их в LinkedIn и Instagram "
        "(переведёт, если включён).\n\n"
        "Режимы:\n"
        "• Авто — добавьте бота в Telegram-канал\n"
        "• Ручной — перешлите пост и нажмите /post\n\n"
        "Подключение:\n"
        "• LinkedIn — /setup, затем /auth\n"
        "• Instagram — /iglogin (логин/пароль) или /igsession (без пароля)\n\n"
        "Перевод, подтверждение постов и пауза любой платформы — всё через команды в чате."
    )


async def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    cfg = get_settings()

    storage = Storage(db_path=cfg.database_path)
    await storage.init()

    translator = Translator(storage=storage)
    linkedin = LinkedInClient(storage=storage)
    crypto = Crypto(cfg.encryption_key)
    instagram_client = InstagramClient(session_dir="data", crypto=crypto)

    bot = Bot(token=cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    publisher = Publisher(linkedin=linkedin, instagram=instagram_client, bot=bot)

    await _setup_bot_menu(bot)

    dp = Dispatcher()
    dp["storage"] = storage
    dp["translator"] = translator
    dp["linkedin"] = linkedin
    dp["instagram"] = instagram_client
    dp["publisher"] = publisher
    dp["crypto"] = crypto
    dp["config"] = cfg

    dp.update.middleware(service_middleware)

    dp.include_router(setup.router)
    dp.include_router(start.router)
    dp.include_router(panel.router)
    dp.include_router(preview_ui.router)
    dp.include_router(settings.router)
    dp.include_router(instagram.router)
    dp.include_router(channel.router)
    dp.include_router(forward.router)
    dp.include_router(post.router)

    logger.info("Bot starting...")
    await dp.start_polling(bot)
