import asyncio
import logging
from datetime import datetime
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, and_
from core.database import async_session_maker, User, Subscription, BroadcastTask
from bots.admin_bot.keyboards import broadcast_audience_kb, admin_main_menu_kb
from config import settings

logger = logging.getLogger(__name__)
router = Router()

_active_broadcasts: dict[int, bool] = {}

MENU_BUTTONS = [
    "👥 Пользователи", "📊 Статистика", "📦 Промокоды",
    "📢 Рассылка", "💳 Платежи", "📨 Тикеты",
    "🎁 Выдать подписку", "⚙️ Настройки",
]


def is_admin(tg_id: int) -> bool:
    return tg_id in settings.admin_ids


class BroadcastStates(StatesGroup):
    waiting_text = State()
    waiting_button = State()
    waiting_audience = State()
    waiting_schedule = State()


@router.message(F.text == "📢 Рассылка")
async def broadcast_handler(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await state.set_state(BroadcastStates.waiting_text)
    await message.answer(
        "📢 <b>Создание рассылки</b>\n\n"
        "Введите текст сообщения (поддерживается HTML):\n\n"
        "Можно прикрепить фото вместе с текстом.",
        parse_mode="HTML",
    )


@router.message(BroadcastStates.waiting_text, F.text | F.photo)
async def broadcast_text_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text and message.text in MENU_BUTTONS:
        await state.clear()
        await message.answer("Рассылка отменена.", reply_markup=admin_main_menu_kb())
        return

    text = message.text or message.caption or ""
    photo_id = message.photo[-1].file_id if message.photo else None
    await state.update_data(bc_text=text, bc_photo=photo_id)
    await state.set_state(BroadcastStates.waiting_button)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ Без кнопки", callback_data="bc_no_button")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="bc_cancel_flow")],
    ])
    await message.answer(
        "Добавить кнопку?\n\nОтправьте в формате: <code>Текст кнопки|https://url.com</code>\nИли нажмите «Без кнопки».",
        parse_mode="HTML",
        reply_markup=kb,
    )


@router.message(BroadcastStates.waiting_button, F.text)
async def broadcast_button_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text in MENU_BUTTONS:
        await state.clear()
        await message.answer("Рассылка отменена.", reply_markup=admin_main_menu_kb())
        return

    if "|" not in message.text:
        await message.answer("❌ Неверный формат. Используйте: Текст|https://url.com\nИли нажмите «Без кнопки».")
        return
    parts = message.text.split("|", 1)
    await state.update_data(bc_button_text=parts[0].strip(), bc_button_url=parts[1].strip())
    await state.set_state(BroadcastStates.waiting_audience)
    await message.answer("Выберите целевую аудиторию:", reply_markup=broadcast_audience_kb())


@router.callback_query(F.data == "bc_cancel_flow")
async def bc_cancel_flow(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Рассылка отменена.", reply_markup=admin_main_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "bc_no_button")
async def bc_no_button(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.update_data(bc_button_text=None, bc_button_url=None)
    await state.set_state(BroadcastStates.waiting_audience)
    await callback.message.answer("Выберите целевую аудиторию:", reply_markup=broadcast_audience_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("bc_audience:"))
async def bc_audience_selected(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    audience = callback.data.split(":")[1]
    await state.update_data(bc_audience=audience)
    await state.set_state(BroadcastStates.waiting_schedule)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Отправить сейчас", callback_data="bc_send_now")],
        [InlineKeyboardButton(text="⏰ Запланировать", callback_data="bc_schedule")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="bc_cancel_flow")],
    ])
    await callback.message.answer("Когда отправить?", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "bc_schedule")
async def bc_schedule_cb(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await callback.message.answer(
        "Введите дату и время отправки:\n<code>ДД.ММ.ГГГГ ЧЧ:ММ</code>",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(BroadcastStates.waiting_schedule, F.text)
async def bc_schedule_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text in MENU_BUTTONS:
        await state.clear()
        await message.answer("Рассылка отменена.", reply_markup=admin_main_menu_kb())
        return
    try:
        scheduled_at = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M")
    except ValueError:
        await message.answer("❌ Неверный формат. Используйте: ДД.ММ.ГГГГ ЧЧ:ММ")
        return
    await state.update_data(bc_scheduled_at=scheduled_at.isoformat())
    await _save_and_confirm_broadcast(message, state, scheduled_at)


@router.callback_query(F.data == "bc_send_now")
async def bc_send_now(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.update_data(bc_scheduled_at=None)
    await _save_and_confirm_broadcast(callback.message, state, None)
    await callback.answer()


async def _save_and_confirm_broadcast(message: Message, state: FSMContext, scheduled_at: datetime = None):
    data = await state.get_data()
    await state.clear()

    async with async_session_maker() as session:
        task = BroadcastTask(
            text=data.get("bc_text", ""),
            photo_file_id=data.get("bc_photo"),
            button_text=data.get("bc_button_text"),
            button_url=data.get("bc_button_url"),
            audience=data.get("bc_audience", "all"),
            scheduled_at=scheduled_at,
            status="pending",
        )
        session.add(task)
        await session.commit()
        task_id = task.id

    audience_labels = {
        "all": "Все пользователи", "active": "Активные подписки",
        "expiring": "Истекают через 3 дня", "no_pay": "Никогда не платили",
        "referrals": "Рефералы",
    }
    audience_label = audience_labels.get(data.get("bc_audience", "all"), "—")
    schedule_info = f"\n⏰ Запланировано: {scheduled_at.strftime('%d.%m.%Y %H:%M')}" if scheduled_at else "\n🚀 Отправить немедленно"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"bc_confirm:{task_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"bc_cancel_task:{task_id}"),
        ]
    ])
    await message.answer(
        f"📋 <b>Рассылка #{task_id}</b>\n\n"
        f"👥 Аудитория: {audience_label}\n"
        f"{schedule_info}\n\nПодтвердить отправку?",
        parse_mode="HTML",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("bc_confirm:"))
async def bc_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    task_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        result = await session.execute(select(BroadcastTask).where(BroadcastTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            await callback.answer("Задача не найдена", show_alert=True)
            return
        if task.scheduled_at and task.scheduled_at > datetime.utcnow():
            task.status = "scheduled"
            await session.commit()
            await callback.message.edit_text(f"✅ Рассылка #{task_id} запланирована на {task.scheduled_at.strftime('%d.%m.%Y %H:%M')} UTC")
            await callback.answer()
            return
        task.status = "running"
        await session.commit()

    await callback.message.edit_text(f"🚀 Рассылка #{task_id} запущена...")
    await callback.answer()
    asyncio.create_task(_run_broadcast(callback.bot, task_id, callback.from_user.id))


@router.callback_query(F.data.startswith("bc_cancel_task:"))
async def bc_cancel_task(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    task_id = int(callback.data.split(":")[1])
    async with async_session_maker() as session:
        result = await session.execute(select(BroadcastTask).where(BroadcastTask.id == task_id))
        task = result.scalar_one_or_none()
        if task:
            task.status = "cancelled"
            await session.commit()
    await callback.message.edit_text(f"❌ Рассылка #{task_id} отменена.")
    await callback.answer()


@router.callback_query(F.data.startswith("bc_stop:"))
async def bc_stop(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    task_id = int(callback.data.split(":")[1])
    _active_broadcasts[task_id] = False
    await callback.answer("🛑 Останавливаем рассылку...", show_alert=True)


async def _get_audience_ids(audience: str) -> list[int]:
    from datetime import timedelta
    now = datetime.utcnow()
    async with async_session_maker() as session:
        if audience == "all":
            result = await session.execute(select(User.tg_id).where(User.is_banned == False))
        elif audience == "active":
            result = await session.execute(
                select(User.tg_id).join(Subscription, Subscription.user_tg_id == User.tg_id).where(
                    and_(Subscription.status == "active", User.is_banned == False)
                )
            )
        elif audience == "expiring":
            result = await session.execute(
                select(User.tg_id).join(Subscription, Subscription.user_tg_id == User.tg_id).where(
                    and_(
                        Subscription.status == "active",
                        Subscription.expires_at <= now + timedelta(days=3),
                        Subscription.expires_at >= now,
                        User.is_banned == False,
                    )
                )
            )
        elif audience == "no_pay":
            from core.database import Payment
            paid_ids = select(Payment.user_tg_id).where(Payment.status == "succeeded")
            result = await session.execute(
                select(User.tg_id).where(and_(User.tg_id.not_in(paid_ids), User.is_banned == False))
            )
        elif audience == "referrals":
            from core.database import Referral
            result = await session.execute(
                select(User.tg_id).join(Referral, Referral.referrer_id == User.tg_id).where(
                    User.is_banned == False
                ).distinct()
            )
        else:
            result = await session.execute(select(User.tg_id).where(User.is_banned == False))
        return [row[0] for row in result.fetchall()]


async def _run_broadcast(bot: Bot, task_id: int, admin_id: int):
    async with async_session_maker() as session:
        result = await session.execute(select(BroadcastTask).where(BroadcastTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return

    user_ids = await _get_audience_ids(task.audience)
    total = len(user_ids)
    sent = 0
    failed = 0
    blocked = 0
    _active_broadcasts[task_id] = True

    kb = None
    if task.button_text and task.button_url:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=task.button_text, url=task.button_url)]
        ])

    stop_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛑 Остановить", callback_data=f"bc_stop:{task_id}")]
    ])

    try:
        await bot.send_message(admin_id, f"📤 Начинаю рассылку #{task_id} для {total} пользователей...", reply_markup=stop_kb)
    except Exception:
        pass

    for tg_id in user_ids:
        if not _active_broadcasts.get(task_id, True):
            break
        try:
            if task.photo_file_id:
                await bot.send_photo(tg_id, task.photo_file_id, caption=task.text, parse_mode="HTML", reply_markup=kb)
            else:
                await bot.send_message(tg_id, task.text, parse_mode="HTML", reply_markup=kb)
            sent += 1
        except Exception as e:
            err_str = str(e).lower()
            if "blocked" in err_str or "deactivated" in err_str or "chat not found" in err_str:
                blocked += 1
            else:
                failed += 1
        await asyncio.sleep(0.05)

    async with async_session_maker() as session:
        result = await session.execute(select(BroadcastTask).where(BroadcastTask.id == task_id))
        task = result.scalar_one_or_none()
        if task:
            task.status = "done"
            task.sent_count = sent
            task.failed_count = failed
            task.blocked_count = blocked
            await session.commit()

    _active_broadcasts.pop(task_id, None)

    try:
        await bot.send_message(
            admin_id,
            f"✅ <b>Рассылка #{task_id} завершена!</b>\n\n"
            f"📤 Отправлено: {sent}\n🚫 Заблокировали: {blocked}\n❌ Ошибок: {failed}\n📊 Всего: {total}",
            parse_mode="HTML",
        )
    except Exception:
        pass
