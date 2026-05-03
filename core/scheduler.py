import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta
from sqlalchemy import select
from core.database import async_session_maker, Subscription
from config import settings

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# Храним уже отправленные уведомления чтобы не спамить каждые 5 минут
_notified_expiring: set = set()


async def sync_subscriptions():
    """Синхронизация подписок с Marzban — помечает истёкшие как expired."""
    now = datetime.utcnow()
    async with async_session_maker() as session:
        result = await session.execute(
            select(Subscription).where(
                Subscription.status == "active",
                Subscription.expires_at < now,
            )
        )
        expired = result.scalars().all()
        for sub in expired:
            sub.status = "expired"
            logger.info(f"Marked subscription {sub.id} (user {sub.user_tg_id}) as expired")
        if expired:
            await session.commit()


async def notify_expiring_subscriptions():
    """
    Уведомляем пользователей об истекающих подписках.
    Уведомление за 3 дня — 1 раз, за 1 день — 1 раз.
    После истечения — сообщение с ссылкой на бот.
    """
    now = datetime.utcnow()
    from bots.shared import notify_user
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    async with async_session_maker() as session:
        # Истекающие через 1-3 дня
        result = await session.execute(
            select(Subscription).where(
                Subscription.status == "active",
                Subscription.expires_at <= now + timedelta(days=3),
                Subscription.expires_at > now,
            )
        )
        subscriptions = result.scalars().all()

    for sub in subscriptions:
        days_left = max(0, (sub.expires_at - now).days)
        # Уведомляем за 3 дня и за 1 день (не повторяем)
        notify_key = f"{sub.user_tg_id}:{days_left}"
        if notify_key in _notified_expiring:
            continue
        if days_left not in (1, 3):
            continue

        _notified_expiring.add(notify_key)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Продлить подписку", url="https://t.me/VpnBlay_bot")],
        ])
        await notify_user(
            sub.user_tg_id,
            f"⚠️ <b>Ваша подписка истекает через {days_left} {'день' if days_left == 1 else 'дня'}!</b>\n\n"
            f"📅 Дата окончания: {sub.expires_at.strftime('%d.%m.%Y')}\n\n"
            f"Не забудьте продлить подписку, чтобы не потерять доступ к VPN.",
            reply_markup=kb,
        )
        logger.info(f"Notified user {sub.user_tg_id} about expiring subscription ({days_left} days left)")

    # Уже истёкшие — уведомляем один раз
    async with async_session_maker() as session:
        result = await session.execute(
            select(Subscription).where(
                Subscription.status == "active",
                Subscription.expires_at <= now,
                Subscription.expires_at >= now - timedelta(minutes=10),  # только свежеистёкшие
            )
        )
        just_expired = result.scalars().all()

    for sub in just_expired:
        expired_key = f"{sub.user_tg_id}:expired"
        if expired_key in _notified_expiring:
            continue
        _notified_expiring.add(expired_key)

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Купить подписку", url="https://t.me/VpnBlay_bot")],
        ])
        await notify_user(
            sub.user_tg_id,
            f"❌ <b>Ваша подписка закончилась!</b>\n\n"
            f"Чтобы продолжить пользоваться BlayVPN — купите новую подписку.\n\n"
            f"👇 Нажмите кнопку ниже или перейдите в @VpnBlay_bot",
            reply_markup=kb,
        )
        logger.info(f"Notified user {sub.user_tg_id} about expired subscription")


async def nightly_pool_recheck():
    """
    Ночная перепроверка всего пула серверов в 03:00 UTC.
    Перечитывает pool.txt, заново проверяет TCP/xray, обновляет Redis.
    """
    from core.pool_manager import recheck_pool_nightly
    logger.info("Nightly pool recheck starting...")
    try:
        result = await recheck_pool_nightly()
        logger.info(f"Nightly pool recheck completed: {result}")
    except Exception as e:
        logger.error(f"Nightly pool recheck failed: {e}")


async def start_scheduler():
    """Start the scheduler"""
    # Синхронизация подписок каждые 5 минут
    scheduler.add_job(
        sync_subscriptions,
        trigger=IntervalTrigger(minutes=5),
        id="sync_subscriptions",
        replace_existing=True,
    )
    # Уведомления об истечении каждые 5 минут
    scheduler.add_job(
        notify_expiring_subscriptions,
        trigger=IntervalTrigger(minutes=5),
        id="notify_expiring_subscriptions",
        replace_existing=True,
    )
    # Ночная перепроверка пула в 03:00 UTC каждый день
    scheduler.add_job(
        nightly_pool_recheck,
        trigger=CronTrigger(hour=3, minute=0),
        id="nightly_pool_recheck",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started (sync every 5m, notify every 5m, pool recheck at 03:00 UTC).")


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
    logger.info(f"Pool auto-loaded on startup: {result}")
