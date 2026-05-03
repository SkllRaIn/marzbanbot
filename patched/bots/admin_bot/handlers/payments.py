import logging
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, and_
from datetime import datetime, timedelta
from core.database import async_session_maker, Payment, User
from core.marzban import PLANS
from config import settings

logger = logging.getLogger(__name__)
router = Router()

MENU_BUTTONS = [
    "👥 Пользователи", "📊 Статистика", "📦 Промокоды",
    "📢 Рассылка", "💳 Платежи", "📨 Тикеты",
    "🎁 Выдать подписку", "⚙️ Настройки",
]



def is_admin(tg_id: int) -> bool:
    return tg_id in settings.admin_ids


@router.message(F.text == "💳 Платежи")
async def payments_handler(message: Message):
    if not is_admin(message.from_user.id):
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Последние 20 платежей", callback_data="pay_recent")],
        [InlineKeyboardButton(text="📊 За сегодня", callback_data="pay_today")],
        [InlineKeyboardButton(text="🔍 Найти по ID платежа", callback_data="pay_search")],
    ])
    await message.answer("💳 <b>Управление платежами</b>", parse_mode="HTML", reply_markup=kb)


async def _format_payments(payments: list) -> str:
    if not payments:
        return "Платежей не найдено."
    text = ""
    for p in payments:
        plan = PLANS.get(p.plan_id, {})
        status_icon = "✅" if p.status == "succeeded" else ("⏳" if p.status == "pending" else "❌")
        text += (
            f"{status_icon} #{p.id} | {p.created_at.strftime('%d.%m %H:%M')}\n"
            f"   👤 <code>{p.user_tg_id}</code> | {plan.get('label', '?')} | {float(p.amount):.0f} ₽"
            + (f" (-{float(p.discount):.0f})" if float(p.discount) > 0 else "") + "\n\n"
        )
    return text


from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram import Router as _Router


class PaySearchState(StatesGroup):
    waiting_id = State()


@router.callback_query(F.data == "pay_recent")
async def pay_recent_cb(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    async with async_session_maker() as session:
        result = await session.execute(
            select(Payment).order_by(Payment.created_at.desc()).limit(20)
        )
        payments = result.scalars().all()

    text = "💳 <b>Последние платежи:</b>\n\n" + await _format_payments(payments)
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "pay_today")
async def pay_today_cb(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    async with async_session_maker() as session:
        result = await session.execute(
            select(Payment).where(
                and_(Payment.status == "succeeded", Payment.created_at >= today)
            ).order_by(Payment.created_at.desc())
        )
        payments = result.scalars().all()

    from sqlalchemy import func
    async with async_session_maker() as session:
        total = (await session.execute(
            select(func.sum(Payment.amount)).where(
                and_(Payment.status == "succeeded", Payment.created_at >= today)
            )
        )).scalar() or 0

    text = (
        f"💳 <b>Платежи за сегодня</b>\n"
        f"💰 Итого: <b>{float(total):.0f} ₽</b> ({len(payments)} платежей)\n\n"
        + await _format_payments(payments)
    )
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "pay_search")
async def pay_search_cb(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(PaySearchState.waiting_id)
    await callback.message.answer("Введите ID платежа YooKassa или Telegram ID пользователя:")
    await callback.answer()


@router.message(PaySearchState.waiting_id)
async def pay_search_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    query = message.text.strip()
    await state.clear()

    async with async_session_maker() as session:
        if query.isdigit() and len(query) < 12:
            result = await session.execute(
                select(Payment).where(Payment.user_tg_id == int(query)).order_by(Payment.created_at.desc()).limit(10)
            )
        else:
            result = await session.execute(
                select(Payment).where(Payment.yookassa_id == query)
            )
        payments = result.scalars().all()

    text = "🔍 <b>Результаты поиска:</b>\n\n" + await _format_payments(payments)
    await message.answer(text, parse_mode="HTML")
