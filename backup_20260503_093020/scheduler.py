import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime, timedelta
from sqlalchemy import select
from core.database import async_session_maker, Subscription
from config import settings

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def sync_subscriptions():
    """Sync subscriptions - placeholder for Marzban"""
    # TODO: Implement sync with Marzban if needed
    pass


async def notify_expiring_subscriptions():
    """Notify users about expiring subscriptions"""
    async with async_session_maker() as session:
        # Get subscriptions expiring in next 3 days
        expire_threshold = datetime.utcnow() + timedelta(days=3)
        result = await session.execute(
            select(Subscription).where(
                Subscription.status == "active",
                Subscription.expires_at <= expire_threshold,
                Subscription.expires_at > datetime.utcnow()
            )
        )
        subscriptions = result.scalars().all()
        
        for sub in subscriptions:
            days_left = (sub.expires_at - datetime.utcnow()).days
            from bots.shared import notify_user
            await notify_user(
                sub.user_tg_id,
                f"⚠️ <b>Ваша подписка истекает через {days_left} дней!</b>\n\n"
                f"📅 Дата окончания: {sub.expires_at.strftime('%d.%m.%Y')}\n\n"
                f"Продлите подписку в разделе «Купить VPN»"
            )
            logger.info(f"Notified user {sub.user_tg_id} about expiring subscription")


async def start_scheduler():
    """Start the scheduler"""
    scheduler.add_job(
        sync_subscriptions,
        trigger=IntervalTrigger(minutes=5),
        id="sync_subscriptions",
        replace_existing=True
    )
    scheduler.add_job(
        notify_expiring_subscriptions,
        trigger=IntervalTrigger(minutes=5),
        id="notify_expiring_subscriptions",
        replace_existing=True
    )
    scheduler.start()
    logger.info("Scheduler started.")


async def stop_scheduler():
    """Stop the scheduler"""
    scheduler.shutdown()
    logger.info("Scheduler stopped.")


async def load_pool_on_startup():
    """Загружает пул из pool.txt при старте если Redis пустой."""
    import os
    from core.pool_manager import process_pool_file, redis_client
    ru = await redis_client.get('pool:ru')
    if ru:
        return  # пул уже есть
    pool_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'pool.txt')
    if not os.path.exists(pool_path):
        return
    with open(pool_path) as f:
        text = f.read()
    result = await process_pool_file(text)
    import logging
    logging.getLogger(__name__).info(f"Pool auto-loaded on startup: {result}")
