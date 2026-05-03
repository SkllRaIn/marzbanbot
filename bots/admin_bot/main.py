import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage, DefaultKeyBuilder
from config import settings
from bots.admin_bot.handlers import start, users, stats, promocodes, broadcast, tickets, payments
from bots.admin_bot.handlers import pool_handler

logger = logging.getLogger(__name__)


def create_admin_bot() -> tuple[Bot, Dispatcher]:
    bot = Bot(token=settings.BOT_TOKEN_ADMIN)
    storage = RedisStorage.from_url(settings.REDIS_URL, key_builder=DefaultKeyBuilder(prefix="admin"))
    dp = Dispatcher(storage=storage)

    dp.include_router(start.router)
    dp.include_router(stats.router)
    dp.include_router(promocodes.router)
    dp.include_router(broadcast.router)
    dp.include_router(tickets.router)
    dp.include_router(payments.router)
    dp.include_router(pool_handler.router)  # Pool — до users (у users catch-all)
    dp.include_router(users.router)

    return bot, dp
