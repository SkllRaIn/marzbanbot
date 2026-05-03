import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, and_
from core.database import async_session_maker, Ticket, TicketMessage, User
from bots.admin_bot.keyboards import ticket_kb, admin_main_menu_kb
from config import settings

logger = logging.getLogger(__name__)
router = Router()

MENU_BUTTONS = [
    "👥 Пользователи", "📊 Статистика", "📦 Промокоды",
    "📢 Рассылка", "💳 Платежи", "📨 Тикеты",
    "🎁 Выдать подписку", "⚙️ Настройки",
]



class TicketStates(StatesGroup):
    waiting_reply = State()


def is_admin(tg_id: int) -> bool:
    return tg_id in settings.admin_ids


@router.message(F.text == "📨 Тикеты")
async def tickets_handler(message: Message):
    if not is_admin(message.from_user.id):
        return

    async with async_session_maker() as session:
        result = await session.execute(
            select(Ticket).where(Ticket.status == "open").order_by(Ticket.created_at.desc()).limit(10)
        )
        tickets = result.scalars().all()

    if not tickets:
        await message.answer("✅ Нет открытых тикетов.")
        return

    text = "📨 <b>Открытые тикеты:</b>\n\n"
    buttons = []
    for t in tickets:
        text += f"#{t.id} — {t.subject or 'Без темы'} | {t.created_at.strftime('%d.%m %H:%M')}\n"
        buttons.append([InlineKeyboardButton(text=f"#{t.id} — {t.subject or 'Без темы'[:30]}", callback_data=f"ticket_open:{t.id}")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("ticket_open:"))
async def ticket_open_cb(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    ticket_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        ticket_result = await session.execute(select(Ticket).where(Ticket.id == ticket_id))
        ticket = ticket_result.scalar_one_or_none()

        user_result = await session.execute(select(User).where(User.tg_id == ticket.user_tg_id))
        user = user_result.scalar_one_or_none()

        msgs_result = await session.execute(
            select(TicketMessage).where(TicketMessage.ticket_id == ticket_id).order_by(TicketMessage.created_at)
        )
        messages = msgs_result.scalars().all()

    if not ticket:
        await callback.answer("Тикет не найден", show_alert=True)
        return

    username_str = f"@{user.username}" if user and user.username else f"ID:{ticket.user_tg_id}"
    text = (
        f"📨 <b>Тикет #{ticket_id}</b>\n"
        f"👤 Пользователь: {username_str}\n"
        f"📅 Создан: {ticket.created_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"🔖 Статус: {ticket.status}\n\n"
        f"<b>Переписка:</b>\n"
    )
    for m in messages:
        sender = "🛡 Админ" if m.is_admin else "👤 Пользователь"
        text += f"\n{sender} [{m.created_at.strftime('%H:%M')}]:\n{m.text or '📷 Фото'}\n"

    await callback.message.answer(text, parse_mode="HTML", reply_markup=ticket_kb(ticket_id))
    await callback.answer()


@router.callback_query(F.data.startswith("ticket_reply:"))
async def ticket_reply_cb(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    ticket_id = int(callback.data.split(":")[1])
    await state.set_state(TicketStates.waiting_reply)
    await state.update_data(reply_ticket_id=ticket_id)
    await callback.message.answer(f"✍️ Введите ответ на тикет #{ticket_id}:")
    await callback.answer()


@router.message(TicketStates.waiting_reply)
async def ticket_reply_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    ticket_id = data.get("reply_ticket_id")
    reply_text = message.text.strip()

    async with async_session_maker() as session:
        ticket_result = await session.execute(select(Ticket).where(Ticket.id == ticket_id))
        ticket = ticket_result.scalar_one_or_none()
        if not ticket:
            await message.answer("❌ Тикет не найден.")
            await state.clear()
            return

        msg = TicketMessage(
            ticket_id=ticket_id,
            sender_tg_id=message.from_user.id,
            is_admin=True,
            text=reply_text,
        )
        ticket.status = "answered"
        session.add(msg)
        await session.commit()
        user_tg_id = ticket.user_tg_id

    await state.clear()
    await message.answer(f"✅ Ответ на тикет #{ticket_id} отправлен!")

    # Notify user via user_bot
    from bots.shared import notify_user
    admin_name = message.from_user.first_name or "Поддержка"
    await notify_user(
        user_tg_id,
        f"📨 <b>Ответ на тикет #{ticket_id}:</b>\n\n"
        f"{reply_text}\n\n"
        f"— {admin_name}, BlayVPN Support",
    )


@router.callback_query(F.data.startswith("ticket_close:"))
async def ticket_close_cb(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    ticket_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        result = await session.execute(select(Ticket).where(Ticket.id == ticket_id))
        ticket = result.scalar_one_or_none()
        if ticket:
            ticket.status = "closed"
            await session.commit()
            user_tg_id = ticket.user_tg_id

    await callback.answer(f"✅ Тикет #{ticket_id} закрыт", show_alert=True)

    from bots.shared import notify_user
    await notify_user(
        user_tg_id,
        f"✅ <b>Тикет #{ticket_id} закрыт.</b>\n\nСпасибо за обращение в поддержку BlayVPN!",
    )
