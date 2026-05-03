import logging
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func
from core.database import async_session_maker, User, Subscription, Payment
from core.marzban import marzban_client, PLANS
from bots.admin_bot.keyboards import user_card_kb, admin_main_menu_kb
from config import settings

logger = logging.getLogger(__name__)
router = Router()

USERS_PER_PAGE = 15


class UserSearchStates(StatesGroup):
    waiting_query = State()
    waiting_balance_amount = State()
    waiting_give_sub_user = State()
    waiting_give_sub_plan = State()


def is_admin(tg_id: int) -> bool:
    return tg_id in settings.admin_ids


async def get_user_card_text(tg_id: int) -> str:
    async with async_session_maker() as session:
        user_result = await session.execute(select(User).where(User.tg_id == tg_id))
        user = user_result.scalar_one_or_none()
        if not user:
            return "❌ Пользователь не найден."

        sub_result = await session.execute(
            select(Subscription).where(
                Subscription.user_tg_id == tg_id,
            ).order_by(Subscription.expires_at.desc())
        )
        sub = sub_result.scalar_one_or_none()

        pay_result = await session.execute(
            select(func.count()).select_from(Payment).where(
                Payment.user_tg_id == tg_id, Payment.status == "succeeded"
            )
        )
        pay_count = pay_result.scalar() or 0

        reg_date = user.created_at.strftime("%d.%m.%Y %H:%M")
        name_parts = [p for p in [user.first_name, user.last_name] if p]
        display_name = " ".join(name_parts) if name_parts else "—"
        username_str = f"@{user.username}" if user.username else "нет username"

        now = datetime.utcnow()
        if sub:
            if sub.status == "active" and sub.expires_at and sub.expires_at > now:
                days_left = (sub.expires_at - now).days
                expires = sub.expires_at.strftime("%d.%m.%Y")
                plan = PLANS.get(sub.plan_id, {})
                sub_info = (
                    f"✅ <b>Активна</b> до {expires} ({days_left} дн.)\n"
                    f"   📦 {plan.get('label', f'Тариф #{sub.plan_id}')}"
                )
                # Ссылка подписки через наш сервер
                domain = settings.SERVER_DOMAIN.replace("https://", "").replace("http://", "").rstrip("/")
                our_sub_url = f"https://{domain}/sub/{tg_id}"
                sub_info += f"\n   🔗 <code>{our_sub_url}</code>"
            elif sub.status in ("expired", "active") and sub.expires_at and sub.expires_at <= now:
                sub_info = f"⏰ <b>Истекла</b> {sub.expires_at.strftime('%d.%m.%Y')}"
            else:
                sub_info = "❌ Нет активной подписки"
        else:
            sub_info = "❌ Нет подписки"

        text = (
            f"👤 <b>{display_name}</b> ({username_str})\n"
            f"🆔 ID: <code>{tg_id}</code>\n"
            f"📅 Регистрация: {reg_date}\n"
            f"📱 Подписка: {sub_info}\n"
            f"💰 Баланс: <b>{float(user.balance):.0f} ₽</b> | Потрачено: {float(user.total_spent):.0f} ₽\n"
            f"💳 Платежей: {pay_count}\n"
            f"🔒 Статус: {'🚫 <b>Заблокирован</b>' if user.is_banned else '✅ Активен'}"
        )
        return text


@router.message(F.text == "👥 Пользователи")
async def users_list_handler(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()

    async with async_session_maker() as session:
        total = await session.scalar(select(func.count()).select_from(User))
        total_pages = (total + USERS_PER_PAGE - 1) // USERS_PER_PAGE if total > 0 else 1

        result = await session.execute(
            select(User).order_by(User.created_at.desc()).limit(USERS_PER_PAGE)
        )
        users = result.scalars().all()

        # Получаем активные подписки для этих юзеров одним запросом
        user_ids = [u.tg_id for u in users]
        subs_result = await session.execute(
            select(Subscription.user_tg_id, Subscription.expires_at, Subscription.status).where(
                Subscription.user_tg_id.in_(user_ids),
                Subscription.status == "active",
            )
        )
        active_subs = {row.user_tg_id: row for row in subs_result.fetchall()}

    now = datetime.utcnow()
    lines = []
    for user in users:
        sub = active_subs.get(user.tg_id)
        if sub and sub.expires_at and sub.expires_at > now:
            days = (sub.expires_at - now).days
            sub_icon = f"✅{days}д"
        elif sub:
            sub_icon = "⏰"
        else:
            sub_icon = "❌"

        name = user.username or (user.first_name or str(user.tg_id))
        lines.append(f"{sub_icon} <code>{user.tg_id}</code> | @{name}")

    text = (
        f"👥 <b>Пользователи (стр. 1/{total_pages})</b>\n"
        f"📊 Всего: <b>{total}</b> | Легенда: ✅N — N дней активно | ⏰ истекла | ❌ нет\n\n"
        + "\n".join(lines)
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Найти пользователя", callback_data="users_search")],
        [InlineKeyboardButton(text="📊 Активные подписки", callback_data="users_active")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_cancel")],
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "users_active")
async def users_active_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    now = datetime.utcnow()
    async with async_session_maker() as session:
        result = await session.execute(
            select(Subscription, User).join(User, User.tg_id == Subscription.user_tg_id).where(
                Subscription.status == "active",
                Subscription.expires_at > now,
            ).order_by(Subscription.expires_at.asc()).limit(30)
        )
        rows = result.fetchall()

    if not rows:
        await callback.answer("Нет активных подписок", show_alert=True)
        return

    lines = []
    for sub, user in rows:
        days = (sub.expires_at - now).days
        name = user.username or str(user.tg_id)
        plan = PLANS.get(sub.plan_id, {})
        lines.append(
            f"• <code>{user.tg_id}</code> @{name} — {days} дн. | {plan.get('label', '?')}"
        )

    await callback.message.answer(
        f"✅ <b>Активные подписки ({len(rows)}):</b>\n\n" + "\n".join(lines),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "users_search")
async def users_search_callback(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(UserSearchStates.waiting_query)
    await callback.message.answer("🔍 Введите Telegram ID или @username для поиска:")
    await callback.answer()


@router.message(UserSearchStates.waiting_query)
async def user_search(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    query = message.text.strip().lstrip("@")

    async with async_session_maker() as session:
        if query.isdigit():
            result = await session.execute(select(User).where(User.tg_id == int(query)))
        else:
            result = await session.execute(select(User).where(User.username.ilike(f"%{query}%")))
        user = result.scalar_one_or_none()

    if not user:
        await message.answer("❌ Пользователь не найден.")
        return

    await state.clear()
    text = await get_user_card_text(user.tg_id)
    await message.answer(text, parse_mode="HTML", reply_markup=user_card_kb(user.tg_id))


@router.callback_query(F.data.startswith("admin_ban:"))
async def admin_ban(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    tg_id = int(callback.data.split(":")[1])
    async with async_session_maker() as session:
        user = (await session.execute(select(User).where(User.tg_id == tg_id))).scalar_one_or_none()
        if user:
            user.is_banned = True
            await session.commit()
    await callback.answer("✅ Пользователь заблокирован", show_alert=True)


@router.callback_query(F.data.startswith("admin_unban:"))
async def admin_unban(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    tg_id = int(callback.data.split(":")[1])
    async with async_session_maker() as session:
        user = (await session.execute(select(User).where(User.tg_id == tg_id))).scalar_one_or_none()
        if user:
            user.is_banned = False
            await session.commit()
    await callback.answer("✅ Пользователь разблокирован", show_alert=True)


@router.callback_query(F.data.startswith("admin_add_balance:"))
async def admin_add_balance(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    tg_id = int(callback.data.split(":")[1])
    await state.update_data(target_user_id=tg_id)
    await state.set_state(UserSearchStates.waiting_balance_amount)
    await callback.message.answer(f"💰 Введите сумму для начисления пользователю <code>{tg_id}</code>:", parse_mode="HTML")
    await callback.answer()


@router.message(UserSearchStates.waiting_balance_amount)
async def process_add_balance(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    try:
        amount = float(message.text.strip())
    except ValueError:
        await message.answer("❌ Введите корректное число.")
        return

    data = await state.get_data()
    tg_id = data.get("target_user_id")
    async with async_session_maker() as session:
        user = (await session.execute(select(User).where(User.tg_id == tg_id))).scalar_one_or_none()
        if user:
            user.balance = float(user.balance) + amount
            await session.commit()

    await state.clear()
    await message.answer(f"✅ Начислено {amount:.0f} ₽ пользователю <code>{tg_id}</code>", parse_mode="HTML")

    from bots.shared import notify_user
    await notify_user(tg_id, f"💰 Вам начислено <b>{amount:.0f} ₽</b> на баланс.")


@router.callback_query(F.data.startswith("admin_reset_traffic:"))
async def admin_reset_traffic(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    await callback.answer("🔄 Трафик сброшен", show_alert=True)


@router.callback_query(F.data.startswith("admin_payments:"))
async def admin_user_payments(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    tg_id = int(callback.data.split(":")[1])
    async with async_session_maker() as session:
        payments = (await session.execute(
            select(Payment).where(Payment.user_tg_id == tg_id, Payment.status == "succeeded")
            .order_by(Payment.created_at.desc()).limit(10)
        )).scalars().all()

    if not payments:
        await callback.answer("Нет платежей", show_alert=True)
        return

    text = f"💳 <b>История платежей {tg_id}:</b>\n\n"
    for p in payments:
        plan = PLANS.get(p.plan_id, {})
        text += f"• {p.created_at.strftime('%d.%m.%Y')} — {plan.get('label', '?')} — {float(p.amount):.0f} ₽\n"
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_config:"))
async def admin_user_config(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    tg_id = int(callback.data.split(":")[1])

    domain = settings.SERVER_DOMAIN.replace("https://", "").replace("http://", "").rstrip("/")
    our_sub_url = f"https://{domain}/sub/{tg_id}"

    async with async_session_maker() as session:
        sub = (await session.execute(
            select(Subscription).where(Subscription.user_tg_id == tg_id, Subscription.status == "active")
        )).scalar_one_or_none()

    if not sub:
        await callback.answer("❌ Нет активной подписки", show_alert=True)
        return

    expires = sub.expires_at.strftime("%d.%m.%Y") if sub.expires_at else "—"
    await callback.message.answer(
        f"🔑 <b>Подписка пользователя <code>{tg_id}</code></b>\n\n"
        f"📅 Действует до: {expires}\n"
        f"🔗 Ссылка для подключения:\n<code>{our_sub_url}</code>",
        parse_mode="HTML"
    )
    await callback.answer()


# ==================== БЕСПЛАТНАЯ ВЫДАЧА ПОДПИСКИ ====================

@router.message(F.text == "🎁 Выдать подписку")
async def give_free_subscription(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(UserSearchStates.waiting_give_sub_user)
    await message.answer("🎁 Введите Telegram ID пользователя:")


@router.message(UserSearchStates.waiting_give_sub_user)
async def give_sub_user_id(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    try:
        tg_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введите числовой ID.")
        return

    await state.update_data(give_sub_tg_id=tg_id)
    await state.set_state(UserSearchStates.waiting_give_sub_plan)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{p['label']}",
            callback_data=f"admin_give_plan:{pid}"
        )]
        for pid, p in PLANS.items()
    ])
    await message.answer(f"Выберите тариф для <code>{tg_id}</code>:", parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("admin_give_plan:"))
async def give_sub_plan(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    plan_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    tg_id = data.get("give_sub_tg_id")
    await state.clear()

    plan = PLANS[plan_id]
    expires_at = datetime.utcnow() + timedelta(days=plan.get("days", 30))
    username = f"user_{tg_id}"

    await callback.message.answer(f"⏳ Выдаю подписку пользователю <code>{tg_id}</code>...", parse_mode="HTML")

    try:
        # Создаём/обновляем пользователя в Marzban через async marzban_client
        try:
            await marzban_client.get_user(username)
            await marzban_client.update_user(
                username,
                expire=int(expires_at.timestamp()),
                proxies={"vless": {"flow": "xtls-rprx-vision"}},
                inbounds={"vless": ["VLESS TCP XTLS"]},
                status="active",
            )
            action = "Обновлён"
        except Exception:
            await marzban_client.create_user(
                username,
                expire=int(expires_at.timestamp()),
                data_limit=plan.get("traffic_gb", 0) * 1024 ** 3 if plan.get("traffic_gb", 0) > 0 else 0,
            )
            action = "Создан"

        # Получаем токен Marzban подписки
        marzban_sub_url = await marzban_client.get_user_subscription_url(username)

        # Ссылка для пользователя — через наш subscription_server
        domain = settings.SERVER_DOMAIN.replace("https://", "").replace("http://", "").rstrip("/")
        our_sub_url = f"https://{domain}/sub/{tg_id}"

        # Получаем пул конфигов
        from core.pool_manager import get_pool_configs
        pool_configs = await get_pool_configs(count_ru=5, count_foreign=5, expires_at=expires_at)

        # Сохраняем в БД
        async with async_session_maker() as session:
            result = await session.execute(
                select(Subscription).where(Subscription.user_tg_id == tg_id)
            )
            existing_sub = result.scalar_one_or_none()

            if existing_sub:
                existing_sub.expires_at = expires_at
                existing_sub.status = "active"
                existing_sub.plan_id = plan_id
                existing_sub.traffic_limit_gb = plan.get("traffic_gb") or None
                existing_sub.sub_url = marzban_sub_url  # токен Marzban
                existing_sub.pool_configs = pool_configs
            else:
                new_sub = Subscription(
                    user_tg_id=tg_id,
                    plan_id=plan_id,
                    status="active",
                    expires_at=expires_at,
                    traffic_limit_gb=plan.get("traffic_gb") or None,
                    sub_url=marzban_sub_url,
                    pool_configs=pool_configs,
                )
                session.add(new_sub)
            await session.commit()

        await callback.message.answer(
            f"✅ <b>Подписка {action}!</b>\n\n"
            f"👤 Пользователь: <code>{tg_id}</code>\n"
            f"📦 Тариф: {plan['label']}\n"
            f"📅 Действует до: {expires_at.strftime('%d.%m.%Y')}\n"
            f"🌐 Пул: {len(pool_configs)} конфигов\n\n"
            f"🔗 Ссылка: <code>{our_sub_url}</code>",
            parse_mode="HTML"
        )

        # Уведомляем пользователя
        from bots.shared import notify_user
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔑 Моя подписка", callback_data="show_key")],
        ])
        await notify_user(
            tg_id,
            f"🎁 <b>Вам выдана подписка!</b>\n\n"
            f"📦 Тариф: {plan['label']}\n"
            f"📅 Действует до: {expires_at.strftime('%d.%m.%Y')}\n\n"
            f"🔗 Ваша ссылка для подключения:\n<code>{our_sub_url}</code>\n\n"
            f"📱 Импортируйте ссылку в Nekobox, v2rayNG или Hiddify.",
            reply_markup=kb,
        )

    except Exception as e:
        logger.error(f"Failed to give subscription to {tg_id}: {e}")
        await callback.message.answer(f"❌ Ошибка при выдаче подписки:\n<code>{e}</code>", parse_mode="HTML")

    await callback.answer()


@router.callback_query(F.data.startswith("admin_give_sub:"))
async def admin_give_sub_from_card(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    tg_id = int(callback.data.split(":")[1])
    await state.update_data(give_sub_tg_id=tg_id)
    await state.set_state(UserSearchStates.waiting_give_sub_plan)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=p["label"], callback_data=f"admin_give_plan:{pid}")]
        for pid, p in PLANS.items()
    ])
    await callback.message.answer("Выберите тариф:", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "admin_cancel")
async def admin_cancel_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("◀️ Возврат в меню", reply_markup=admin_main_menu_kb())
    await callback.answer()
