import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.handlers import start, settings, channel, forward, post, setup, approval, instagram
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


async def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    cfg = get_settings()

    storage = Storage(db_path=cfg.database_path)
    await storage.init()

    translator = Translator(storage=storage)
    linkedin = LinkedInClient(storage=storage)
    crypto = Crypto(cfg.encryption_key)
    instagram = InstagramClient(session_dir="data", crypto=crypto)
    publisher = Publisher(linkedin=linkedin, instagram=instagram, bot=None)

    bot = Bot(token=cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    publisher.bot = bot  # bot is needed at publish time

    dp = Dispatcher()
    dp["storage"] = storage
    dp["translator"] = translator
    dp["linkedin"] = linkedin
    dp["instagram"] = instagram
    dp["publisher"] = publisher
    dp["crypto"] = crypto
    dp["config"] = cfg

    dp.update.middleware(service_middleware)

    dp.include_router(setup.router)
    dp.include_router(start.router)
    dp.include_router(settings.router)
    dp.include_router(instagram.router)
    dp.include_router(approval.router)
    dp.include_router(channel.router)
    dp.include_router(forward.router)
    dp.include_router(post.router)

    logger.info("Bot starting...")
    await dp.start_polling(bot)
