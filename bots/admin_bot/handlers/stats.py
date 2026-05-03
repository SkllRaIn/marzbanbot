import logging
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy import select, func, and_
from core.database import async_session_maker, User, Subscription, Payment
from bots.admin_bot.keyboards import admin_main_menu_kb
from config import settings

logger = logging.getLogger(__name__)
router = Router()


def is_admin(tg_id: int) -> bool:
    return tg_id in settings.admin_ids


@router.message(F.text == "📊 Статистика")
async def stats_handler(message: Message):
    if not is_admin(message.from_user.id):
        return

    now = datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    async with async_session_maker() as session:
        # Total users
        total_users = (await session.execute(select(func.count(User.id)))).scalar()

        # New today
        new_today = (await session.execute(
            select(func.count(User.id)).where(User.created_at >= today)
        )).scalar()

        # New this week
        new_week = (await session.execute(
            select(func.count(User.id)).where(User.created_at >= week_ago)
        )).scalar()

        # Active subscriptions
        active_subs = (await session.execute(
            select(func.count(Subscription.id)).where(Subscription.status == "active")
        )).scalar()

        # Expiring in 3 days
        expiring_soon = (await session.execute(
            select(func.count(Subscription.id)).where(
                and_(
                    Subscription.status == "active",
                    Subscription.expires_at <= now + timedelta(days=3),
                    Subscription.expires_at >= now,
                )
            )
        )).scalar()

        # Revenue today
        revenue_today = (await session.execute(
            select(func.sum(Payment.amount)).where(
                and_(Payment.status == "succeeded", Payment.created_at >= today)
            )
        )).scalar() or 0

        # Revenue month
        revenue_month = (await session.execute(
            select(func.sum(Payment.amount)).where(
                and_(Payment.status == "succeeded", Payment.created_at >= month_ago)
            )
        )).scalar() or 0

        # Total payments
        total_payments = (await session.execute(
            select(func.count(Payment.id)).where(Payment.status == "succeeded")
        )).scalar()

        # Blocked users
        blocked = (await session.execute(
            select(func.count(User.id)).where(User.is_banned == True)
        )).scalar()

    text = (
        f"📊 <b>Статистика BlayVPN</b>\n"
        f"<i>{now.strftime('%d.%m.%Y %H:%M')} UTC</i>\n\n"
        f"👥 <b>Пользователи:</b>\n"
        f"  Всего: <b>{total_users}</b>\n"
        f"  Сегодня: <b>+{new_today}</b>\n"
        f"  За неделю: <b>+{new_week}</b>\n"
        f"  Заблокировано: {blocked}\n\n"
        f"📱 <b>Подписки:</b>\n"
        f"  Активных: <b>{active_subs}</b>\n"
        f"  Истекают (3 дня): ⚠️ {expiring_soon}\n\n"
        f"💰 <b>Доходы:</b>\n"
        f"  Сегодня: <b>{revenue_today:.0f} ₽</b>\n"
        f"  За месяц: <b>{revenue_month:.0f} ₽</b>\n"
        f"  Платежей всего: {total_payments}"
    )
    await message.answer(text, parse_mode="HTML")
