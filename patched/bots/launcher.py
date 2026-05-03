#!/usr/bin/env python3
import asyncio
import logging
from aiohttp import web
from core.database import init_db
from core.redis_client import redis_client
from core.scheduler import start_scheduler
from webhook_server import create_webhook_app
from bots.user_bot.main import create_user_bot
from bots.admin_bot.main import create_admin_bot
from config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    logger.info("BlayVPN starting up...")
    
    # Initialize database
    await init_db()
    logger.info("Database initialized.")
    
    # Initialize Redis
    await redis_client.init()
    logger.info("Redis connected.")
    
    # Start scheduler
    await start_scheduler()
    
    # Автозагрузка пула из pool.txt если Redis пустой
    from core.scheduler import load_pool_on_startup
    await load_pool_on_startup()

    # Create bots
    user_bot, user_dp = create_user_bot()
    admin_bot, admin_dp = create_admin_bot()
    
    # Set bots for shared notifications
    from bots.shared import set_user_bot, set_admin_bot
    set_user_bot(user_bot)
    set_admin_bot(admin_bot)
    logger.info("Bots set for notifications.")
    
    # Create webhook app
    app = create_webhook_app(user_dp, admin_dp, user_bot, admin_bot)
    
    # Run webhook server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", settings.WEBHOOK_PORT)
    await site.start()
    
    logger.info(f"Webhook server listening on 127.0.0.1:{settings.WEBHOOK_PORT}")
    logger.info("BlayVPN is running. Press Ctrl+C to stop.")
    
    # Keep running
    try:
        await asyncio.Future()
    finally:
        await runner.cleanup()
        await user_bot.session.close()
        await admin_bot.session.close()
        await redis_client.close()


if __name__ == "__main__":
    asyncio.run(main())
