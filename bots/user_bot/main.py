import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from config import settings
from bots.user_bot.handlers import start, profile, buy, referral, instructions, support

logger = logging.getLogger(__name__)


def create_user_bot() -> tuple[Bot, Dispatcher]:
    bot = Bot(token=settings.BOT_TOKEN_USER)
    storage = RedisStorage.from_url(settings.REDIS_URL)
    dp = Dispatcher(storage=storage)

    # Register routers
    dp.include_router(start.router)
    dp.include_router(profile.router)
    dp.include_router(buy.router)
    dp.include_router(referral.router)
    dp.include_router(instructions.router)
    dp.include_router(support.router)

    return bot, dp
