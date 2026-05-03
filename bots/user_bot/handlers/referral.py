import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select, func
from core.database import async_session_maker, User, Referral
from bots.user_bot.keyboards import referral_kb

logger = logging.getLogger(__name__)
router = Router()


@router.message(F.text == "🔗 Рефералы")
async def referral_handler(message: Message):
    tg_id = message.from_user.id
    ref_link = f"https://t.me/BlayVPNBot?start=ref_{tg_id}"

    async with async_session_maker() as session:
        user_result = await session.execute(select(User).where(User.tg_id == tg_id))
        user = user_result.scalar_one_or_none()

        ref_result = await session.execute(
            select(func.count(Referral.id)).where(Referral.referrer_id == tg_id)
        )
        ref_count = ref_result.scalar() or 0

        bonus_result = await session.execute(
            select(func.sum(Referral.bonus_paid)).where(Referral.referrer_id == tg_id)
        )
        total_bonus = bonus_result.scalar() or 0.0

    balance = float(user.balance) if user else 0.0

    text = (
        f"🔗 <b>Реферальная программа</b>\n\n"
        f"Приглашайте друзей и получайте:\n"
        f"• <b>10%</b> от суммы оплаты реферала\n"
        f"• <b>+1 месяц</b> бесплатно при оплате реферала на 3 месяца\n\n"
        f"📊 <b>Ваша статистика:</b>\n"
        f"👥 Приглашено: <b>{ref_count}</b>\n"
        f"💎 Заработано всего: <b>{total_bonus:.0f} ₽</b>\n"
        f"💰 Текущий баланс: <b>{balance:.0f} ₽</b>\n\n"
        f"🔗 Ваша ссылка:\n"
        f"<code>{ref_link}</code>\n\n"
        f"💡 Баланс автоматически применяется при следующей оплате.\n"
        f"Вывод от 500 ₽ — через обращение в поддержку."
    )
    await message.answer(text, parse_mode="HTML", reply_markup=referral_kb(ref_link))


@router.callback_query(F.data == "withdraw_balance")
async def withdraw_balance_cb(callback: CallbackQuery):
    async with async_session_maker() as session:
        user_result = await session.execute(select(User).where(User.tg_id == callback.from_user.id))
        user = user_result.scalar_one_or_none()

    balance = float(user.balance) if user else 0.0
    if balance < 500:
        await callback.answer(
            f"❌ Минимальная сумма вывода — 500 ₽.\nВаш баланс: {balance:.0f} ₽",
            show_alert=True
        )
        return

    await callback.message.answer(
        f"💸 Для вывода баланса ({balance:.0f} ₽) обратитесь в поддержку.\n\n"
        f"Нажмите «❓ Поддержка» и укажите реквизиты для выплаты."
    )
    await callback.answer()
