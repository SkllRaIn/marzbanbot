import json
import logging
from datetime import datetime, timedelta
from aiohttp import web
from aiogram import Bot
from sqlalchemy import select
from core.database import async_session_maker, Payment, User, Subscription, PromoCode, Referral
from core.marzban import marzban_client, PLANS
from core.pool_manager import get_pool_configs
from config import settings

logger = logging.getLogger(__name__)


async def handle_yookassa_webhook(request: web.Request) -> web.Response:
    """Handle incoming YooKassa payment notifications."""
    try:
        body = await request.read()
        data = json.loads(body)
    except Exception as e:
        logger.error(f"Webhook parse error: {e}")
        return web.Response(status=400)

    event = data.get("event", "")
    payment_obj = data.get("object", {})

    if event != "payment.succeeded":
        return web.Response(status=200)

    yookassa_id = payment_obj.get("id")
    metadata = payment_obj.get("metadata", {})
    user_tg_id = int(metadata.get("user_tg_id", 0))
    plan_id = int(metadata.get("plan_id", 0))
    promo_code = metadata.get("promo_code", "")

    if not user_tg_id or not plan_id:
        logger.error(f"Invalid webhook metadata: {metadata}")
        return web.Response(status=400)

    logger.info(f"Payment succeeded: {yookassa_id} for user {user_tg_id}, plan {plan_id}")

    async with async_session_maker() as session:
        pay_result = await session.execute(select(Payment).where(Payment.yookassa_id == yookassa_id))
        payment = pay_result.scalar_one_or_none()

        if payment and payment.status == "succeeded":
            logger.info(f"Payment {yookassa_id} already processed, skipping.")
            return web.Response(status=200)

        if payment:
            payment.status = "succeeded"
        else:
            payment = Payment(
                user_tg_id=user_tg_id,
                yookassa_id=yookassa_id,
                plan_id=plan_id,
                amount=float(payment_obj.get("amount", {}).get("value", 0)),
                status="succeeded",
                promo_code=promo_code or None,
                payment_metadata=metadata,
            )
            session.add(payment)

        if promo_code:
            promo_result = await session.execute(
                select(PromoCode).where(PromoCode.code == promo_code)
            )
            promo = promo_result.scalar_one_or_none()
            if promo:
                promo.activations_count += 1

        user_result = await session.execute(select(User).where(User.tg_id == user_tg_id))
        user = user_result.scalar_one_or_none()
        if user:
            paid_amount = float(payment_obj.get("amount", {}).get("value", 0))
            user.total_spent = float(user.total_spent) + paid_amount
            meta_balance_used = float(metadata.get("balance_used", 0))
            if meta_balance_used > 0:
                user.balance = max(0.0, float(user.balance) - meta_balance_used)

        await session.commit()

    try:
        await _provision_subscription(user_tg_id, plan_id, yookassa_id)
    except Exception as e:
        logger.error(f"Failed to provision subscription for {user_tg_id}: {e}")

    try:
        await _handle_referral_bonus(user_tg_id, plan_id, float(payment_obj.get("amount", {}).get("value", 0)))
    except Exception as e:
        logger.warning(f"Referral bonus error: {e}")

    return web.Response(status=200)


async def _provision_subscription(user_tg_id: int, plan_id: int, yookassa_id: str):
    """Provision subscription: Marzban + pool-конфиги 5 RU + 5 foreign."""
    plan = PLANS[plan_id]
    expires_at = datetime.utcnow() + timedelta(days=plan["days"])
    username = f"user_{user_tg_id}"

    # Получаем Marzban sub_url
    try:
        await marzban_client.get_user(username)
        await marzban_client.update_user(username, expire=int(expires_at.timestamp()))
        logger.info(f"Updated Marzban user {username}")
    except Exception:
        await marzban_client.create_user(username, expire=int(expires_at.timestamp()))
        logger.info(f"Created Marzban user {username}")

    sub_url = await marzban_client.get_user_subscription_url(username)

    # Берём 5 RU + 5 foreign из пула
    pool_configs = await get_pool_configs(count_ru=5, count_foreign=5)
    logger.info(f"Assigned {len(pool_configs)} pool configs to user {user_tg_id}")

    async with async_session_maker() as session:
        sub_result = await session.execute(
            select(Subscription).where(Subscription.user_tg_id == user_tg_id)
        )
        existing_sub = sub_result.scalar_one_or_none()

        if existing_sub:
            existing_sub.expires_at = expires_at
            existing_sub.status = "active"
            existing_sub.plan_id = plan_id
            existing_sub.traffic_limit_gb = plan["traffic_gb"] if plan["traffic_gb"] > 0 else None
            existing_sub.sub_url = sub_url
            existing_sub.pool_configs = pool_configs  # обновляем pool при продлении
        else:
            new_sub = Subscription(
                user_tg_id=user_tg_id,
                plan_id=plan_id,
                status="active",
                expires_at=expires_at,
                traffic_limit_gb=plan["traffic_gb"] if plan["traffic_gb"] > 0 else None,
                sub_url=sub_url,
                pool_configs=pool_configs,
            )
            session.add(new_sub)

        await session.commit()

    # Ссылка на подписку — через наш subscription_server
    domain = settings.SERVER_DOMAIN.replace("https://", "").replace("http://", "").rstrip("/")
    our_sub_url = f"https://{domain}/sub/{user_tg_id}"

    from bots.shared import notify_user, notify_admin
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 Моя подписка", callback_data="show_key")],
    ])

    pool_note = ""
    if pool_configs:
        ru_count = sum(1 for c in pool_configs if "🇷🇺" in c or "Россия" in c)
        foreign_count = len(pool_configs) - ru_count
        pool_note = (
            f"\n🌐 <b>Дополнительные серверы из пула:</b>\n"
            f"🇷🇺 Россия: {ru_count} сервера\n"
            f"🌍 Иностранных: {foreign_count} серверов\n"
            f"<i>(обновляются при каждом обновлении подписки)</i>"
        )

    await notify_user(
        user_tg_id,
        f"✅ <b>Оплата прошла успешно!</b>\n\n"
        f"📦 Тариф: {plan['label']}\n"
        f"📅 Действует до: {expires_at.strftime('%d.%m.%Y')}\n\n"
        f"🔗 <b>Ссылка на подписку:</b>\n"
        f"<code>{our_sub_url}</code>\n\n"
        f"📱 <b>Как подключиться:</b>\n"
        f"1. Скачайте Nekobox, v2rayNG или Hiddify\n"
        f"2. Скопируйте ссылку выше\n"
        f"3. Нажмите «Импорт из буфера обмена»\n"
        f"4. Включите подключение\n"
        f"{pool_note}",
        reply_markup=kb,
    )

    for admin_id in settings.admin_ids:
        await notify_admin(
            admin_id,
            f"💰 <b>Новый платёж!</b>\n"
            f"👤 TG ID: <code>{user_tg_id}</code>\n"
            f"📦 Тариф: {plan['label']}\n"
            f"💳 YooKassa ID: <code>{yookassa_id}</code>\n"
            f"🌐 Pool: {len(pool_configs)} конфигов назначено",
        )


async def _handle_referral_bonus(user_tg_id: int, plan_id: int, amount: float):
    """Referral bonus — +3 дня рефереру."""
    async with async_session_maker() as session:
        user_result = await session.execute(select(User).where(User.tg_id == user_tg_id))
        user = user_result.scalar_one_or_none()

        if not user or not user.referrer_id:
            return

        ref_result = await session.execute(
            select(Referral).where(
                Referral.referrer_id == user.referrer_id,
                Referral.referred_id == user_tg_id,
            )
        )
        referral = ref_result.scalar_one_or_none()
        if not referral:
            return

        bonus = round(amount * 0.10, 2)
        referral.bonus_paid = float(referral.bonus_paid) + bonus

        referrer_result = await session.execute(select(User).where(User.tg_id == user.referrer_id))
        referrer = referrer_result.scalar_one_or_none()
        if referrer:
            referrer.balance = float(referrer.balance) + bonus

        sub_result = await session.execute(
            select(Subscription).where(
                Subscription.user_tg_id == user.referrer_id,
                Subscription.status == "active"
            )
        )
        referrer_sub = sub_result.scalar_one_or_none()

        if referrer_sub and referrer_sub.expires_at:
            referrer_sub.expires_at = referrer_sub.expires_at + timedelta(days=3)
            try:
                ref_username = f"user_{user.referrer_id}"
                await marzban_client.update_user(ref_username, expire=int(referrer_sub.expires_at.timestamp()))
            except Exception as e:
                logger.warning(f"Failed to update Marzban for bonus: {e}")

        referrer_tg_id = user.referrer_id
        await session.commit()

    from bots.shared import notify_user
    await notify_user(
        referrer_tg_id,
        f"🎉 <b>Реферальный бонус!</b>\n\n"
        f"Ваш реферал совершил оплату!\n"
        f"💰 Начислено: <b>{bonus:.0f} ₽</b>\n"
        f"📅 <b>+3 дня</b> к вашей подписке!"
    )


def create_webhook_app(user_dp, admin_dp, user_bot: Bot, admin_bot: Bot) -> web.Application:
    """Create combined webhook + subscription app."""
    from subscription_server import handle_subscription

    app = web.Application()

    async def on_startup(app):
        logger.info("Webhook server starting up...")
        domain = settings.SERVER_DOMAIN.replace("https://", "").replace("http://", "").rstrip("/")
        await user_bot.set_webhook(
            url=f"https://{domain}/webhook/user",
            drop_pending_updates=True,
        )
        await admin_bot.set_webhook(
            url=f"https://{domain}/webhook/admin",
            drop_pending_updates=True,
        )
        logger.info("Telegram webhooks set.")

    async def on_shutdown(app):
        logger.info("Webhook server shutting down...")
        try:
            await user_bot.delete_webhook()
        except Exception as e:
            logger.warning(f"Failed to delete user_bot webhook: {e}")
        try:
            await admin_bot.delete_webhook()
        except Exception as e:
            logger.warning(f"Failed to delete admin_bot webhook: {e}")

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    # YooKassa webhook
    app.router.add_post(settings.WEBHOOK_PATH, handle_yookassa_webhook)

    # Подписка — /sub/{user_tg_id}
    app.router.add_get("/sub/{user_tg_id}", handle_subscription)

    from aiogram.webhook.aiohttp_server import SimpleRequestHandler
    SimpleRequestHandler(dispatcher=user_dp, bot=user_bot).register(app, path="/webhook/user")
    SimpleRequestHandler(dispatcher=admin_dp, bot=admin_bot).register(app, path="/webhook/admin")

    return app
