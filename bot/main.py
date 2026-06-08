import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.handlers import start, settings, channel, forward, post, setup
from config import get_settings
from services.storage import Storage
from services.translator import Translator
from services.linkedin import LinkedInClient

logger = logging.getLogger(__name__)


async def service_middleware(handler, event, data):
    data["storage"] = data["dispatcher"]["storage"]
    data["translator"] = data["dispatcher"]["translator"]
    data["linkedin_client"] = data["dispatcher"]["linkedin"]
    data["app_config"] = data["dispatcher"]["config"]
    return await handler(event, data)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    cfg = get_settings()

    storage = Storage(db_path=cfg.database_path)
    await storage.init()

    translator = Translator(storage=storage)
    linkedin = LinkedInClient(storage=storage)

    bot = Bot(token=cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    dp = Dispatcher()
    dp["storage"] = storage
    dp["translator"] = translator
    dp["linkedin"] = linkedin
    dp["config"] = cfg

    dp.update.middleware(service_middleware)

    dp.include_router(setup.router)
    dp.include_router(start.router)
    dp.include_router(settings.router)
    dp.include_router(channel.router)
    dp.include_router(forward.router)
    dp.include_router(post.router)

    logger.info("Bot starting...")
    await dp.start_polling(bot)
