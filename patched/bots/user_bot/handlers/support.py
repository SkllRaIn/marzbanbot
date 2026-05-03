import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select
from core.database import async_session_maker, Ticket, TicketMessage
from bots.user_bot.keyboards import support_cancel_kb, main_menu_kb
from config import settings

logger = logging.getLogger(__name__)
router = Router()


class SupportStates(StatesGroup):
    waiting_message = State()
    waiting_photo = State()


@router.message(F.text == "❓ Поддержка")
async def support_handler(message: Message, state: FSMContext):
    await state.set_state(SupportStates.waiting_message)
    await message.answer(
        "❓ <b>Поддержка BlayVPN</b>\n\n"
        "Опишите вашу проблему. Вы можете приложить скриншот.\n\n"
        "Среднее время ответа: до 2 часов.",
        parse_mode="HTML",
        reply_markup=support_cancel_kb(),
    )


@router.message(SupportStates.waiting_message, F.text | F.photo)
async def support_message(message: Message, state: FSMContext):
    text = message.text or message.caption or ""
    photo_id = None

    if message.photo:
        photo_id = message.photo[-1].file_id

    if not text and not photo_id:
        await message.answer("Пожалуйста, напишите текст сообщения.")
        return

    async with async_session_maker() as session:
        ticket = Ticket(
            user_tg_id=message.from_user.id,
            subject=text[:100] if text else "Скриншот",
            status="open",
        )
        session.add(ticket)
        await session.flush()

        msg = TicketMessage(
            ticket_id=ticket.id,
            sender_tg_id=message.from_user.id,
            is_admin=False,
            text=text,
            photo_file_id=photo_id,
        )
        session.add(msg)
        await session.commit()

        ticket_id = ticket.id

    await state.clear()
    await message.answer(
        f"✅ <b>Тикет #{ticket_id} создан!</b>\n\n"
        f"Мы ответим в ближайшее время. Следите за уведомлениями.",
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )

    # Notify admin bot
    admin_text = (
        f"🆕 <b>Новый тикет #{ticket_id}</b>\n\n"
        f"👤 Пользователь: @{message.from_user.username or 'N/A'} (ID: {message.from_user.id})\n"
        f"💬 Сообщение: {text[:200] if text else '(скриншот)'}"
    )
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Ответить", callback_data=f"ticket_reply:{ticket_id}"),
            InlineKeyboardButton(text="❌ Закрыть", callback_data=f"ticket_close:{ticket_id}"),
        ]
    ])

    for admin_id in settings.admin_ids:
        try:
            admin_bot_token = settings.BOT_TOKEN_ADMIN
            # We use a shared notification mechanism via the admin bot
            # This will be handled by the admin bot's notification system
            from bots.shared import notify_admin
            await notify_admin(admin_id, admin_text, photo_id, kb)
        except Exception as e:
            logger.warning(f"Failed to notify admin {admin_id}: {e}")


async def send_ticket_reply_to_user(bot: Bot, ticket_id: int, reply_text: str, admin_name: str):
    """Called by admin bot when replying to a ticket."""
    async with async_session_maker() as session:
        ticket_result = await session.execute(select(Ticket).where(Ticket.id == ticket_id))
        ticket = ticket_result.scalar_one_or_none()
        if not ticket:
            return

    await bot.send_message(
        ticket.user_tg_id,
        f"📨 <b>Ответ на тикет #{ticket_id}:</b>\n\n"
        f"{reply_text}\n\n"
        f"— {admin_name}",
        parse_mode="HTML",
    )
