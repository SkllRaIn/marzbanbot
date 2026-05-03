import logging
import requests
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

USERS_PER_PAGE = 10


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
                Subscription.status == "active"
            ).order_by(Subscription.expires_at.desc())
        )
        sub = sub_result.scalar_one_or_none()

        reg_date = user.created_at.strftime("%d.%m.%Y")
        username_str = f"@{user.username}" if user.username else "N/A"
        sub_info = "❌ Нет активной подписки"
        if sub and sub.expires_at:
            expires = sub.expires_at.strftime("%d.%m.%Y") if sub.expires_at else "—"
            traffic = f"{float(sub.traffic_used_gb):.1f} / {sub.traffic_limit_gb or '∞'} GB"
            sub_info = f"✅ активна до {expires}\n📊 Трафик: {traffic}"
        elif sub:
            sub_info = "✅ Активна (безлимит)"

        text = (
            f"👤 {username_str} | ID: <code>{tg_id}</code>\n"
            f"📅 Регистрация: {reg_date}\n"
            f"📱 Подписка: {sub_info}\n"
            f"💰 Баланс: {float(user.balance):.0f} ₽ | Потрачено: {float(user.total_spent):.0f} ₽\n"
            f"🔒 Статус: {'🚫 Заблокирован' if user.is_banned else '✅ Активен'}"
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
    
    text = f"👥 <b>Список пользователей (стр. 1/{total_pages}):</b>\n\n"
    for i, user in enumerate(users, 1):
        status_icon = "✅" if not user.is_banned else "❌"
        username = user.username or "—"
        text += f"{i}. {status_icon} <code>{user.tg_id}</code> | @{username}\n"
    text += f"\n📊 Всего: {total} пользователей"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Поиск", callback_data="users_search")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_cancel")],
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "users_search")
async def users_search_callback(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(UserSearchStates.waiting_query)
    await callback.message.answer("🔍 Введите Telegram ID или username для поиска:")
    await callback.answer()


@router.message(UserSearchStates.waiting_query)
async def user_search(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    query = message.text.strip()
    
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
        user = await session.execute(select(User).where(User.tg_id == tg_id))
        user = user.scalar_one_or_none()
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
        user = await session.execute(select(User).where(User.tg_id == tg_id))
        user = user.scalar_one_or_none()
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
        user = await session.execute(select(User).where(User.tg_id == tg_id))
        user = user.scalar_one_or_none()
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
    tg_id = int(callback.data.split(":")[1])
    await callback.answer("🔄 Трафик сброшен", show_alert=True)


@router.callback_query(F.data.startswith("admin_payments:"))
async def admin_user_payments(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    tg_id = int(callback.data.split(":")[1])
    async with async_session_maker() as session:
        payments = await session.execute(
            select(Payment).where(Payment.user_tg_id == tg_id, Payment.status == "succeeded")
            .order_by(Payment.created_at.desc()).limit(10)
        )
        payments = payments.scalars().all()
    
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
    async with async_session_maker() as session:
        sub = await session.execute(
            select(Subscription).where(Subscription.user_tg_id == tg_id, Subscription.status == "active")
        )
        sub = sub.scalar_one_or_none()
    
    if not sub or not sub.sub_url:
        await callback.answer("❌ Нет активной подписки/конфига", show_alert=True)
        return
    
    await callback.message.answer(
        f"🔑 Конфиг пользователя <code>{tg_id}</code>:\n\n<code>{sub.sub_url}</code>",
        parse_mode="HTML"
    )
    await callback.answer()


# ==================== БЕСПЛАТНАЯ ВЫДАЧА ПОДПИСКИ ====================

@router.message(F.text == "🎁 Выдать подписку")
async def give_free_subscription(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(UserSearchStates.waiting_give_sub_user)
    await message.answer("🎁 Введите Telegram ID пользователя для бесплатной выдачи подписки:")


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
        [InlineKeyboardButton(text=f"{p['label']} | {p.get('traffic_gb') or '∞'} GB", callback_data=f"admin_give_plan:{pid}")]
        for pid, p in PLANS.items()
    ])
    await message.answer(f"Выберите тариф для пользователя <code>{tg_id}</code>:", parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("admin_give_plan:"))
async def give_sub_plan(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    
    plan_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    tg_id = data.get("give_sub_tg_id")
    
    await state.clear()
    
    username = f"user_{tg_id}"
    plan = PLANS[plan_id]
    expires_at = datetime.utcnow() + timedelta(days=plan.get("days", 30))
    
    await callback.message.answer(f"⏳ Выдача подписки пользователю <code>{tg_id}</code>...", parse_mode="HTML")
    
    try:
        # Получаем токен Marzban
        token_url = f"{settings.MARZBAN_API_URL}/api/admin/token"
        token_resp = requests.post(token_url, data={
            "grant_type": "password",
            "username": settings.MARZBAN_USERNAME,
            "password": settings.MARZBAN_PASSWORD
        }, timeout=10)
        token_data = token_resp.json()
        token = token_data.get("access_token")
        
        if not token:
            await callback.message.answer(f"❌ Ошибка авторизации в Marzban: {token_data}")
            return
        
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        
        # Сначала проверим, существует ли пользователь
        check_resp = requests.get(f"{settings.MARZBAN_API_URL}/api/user/{username}", headers=headers, timeout=10)
        
        user_data = {
            "username": username,
            "proxies": {"vless": {"flow": "xtls-rprx-vision"}},
            "expire": int(expires_at.timestamp()),
            "data_limit": plan.get("traffic_gb", 0) * 1024**3 if plan.get("traffic_gb", 0) > 0 else 0,
            "status": "active",
            "inbounds": {"vless": ["all"]}
        }
        
        if check_resp.status_code == 200:
            # Пользователь существует - обновляем
            resp = requests.put(f"{settings.MARZBAN_API_URL}/api/user/{username}", headers=headers, json=user_data, timeout=10)
            action = "Обновлен"
        else:
            # Создаем нового
            resp = requests.post(f"{settings.MARZBAN_API_URL}/api/user", headers=headers, json=user_data, timeout=10)
            action = "Создан"
        
        if resp.status_code not in [200, 201]:
            await callback.message.answer(f"❌ Ошибка Marzban: {resp.status_code} - {resp.text}")
            return
        
        # Формируем ссылку
        sub_url = f"https://panel.komissarovka.ru/sub/{username}"
        
        # Сохраняем в локальную БД
        async with async_session_maker() as session:
            result = await session.execute(
                select(Subscription).where(Subscription.user_tg_id == tg_id)
            )
            existing_sub = result.scalar_one_or_none()
            
            if existing_sub:
                existing_sub.expires_at = expires_at
                existing_sub.status = "active"
                existing_sub.plan_id = plan_id
                existing_sub.traffic_limit_gb = plan.get("traffic_gb", 0)
                existing_sub.sub_url = sub_url
            else:
                new_sub = Subscription(
                    user_tg_id=tg_id,
                    plan_id=plan_id,
                    status="active",
                    expires_at=expires_at,
                    traffic_limit_gb=plan.get("traffic_gb", 0),
                    sub_url=sub_url,
                )
                session.add(new_sub)
            await session.commit()
        
        await callback.message.answer(
            f"✅ <b>Подписка {action}!</b>\n\n"
            f"👤 Пользователь: <code>{tg_id}</code>\n"
            f"📦 Тариф: {plan['label']}\n"
            f"📅 Действует до: {expires_at.strftime('%d.%m.%Y')}\n\n"
            f"🔗 Ссылка: {sub_url}",
            parse_mode="HTML"
        )
        
        # Уведомляем пользователя
        from bots.shared import notify_user
        await notify_user(
            tg_id,
            f"🎁 <b>Вам выдана подписка!</b>\n\n"
            f"📦 Тариф: {plan['label']}\n"
            f"📅 Действует до: {expires_at.strftime('%d.%m.%Y')}\n\n"
            f"🔗 Ваша ссылка для подключения:\n{sub_url}"
        )
        
    except Exception as e:
        logger.error(f"Failed to give subscription: {e}")
        await callback.message.answer(f"❌ Ошибка при выдаче подписки: {e}", parse_mode="HTML")
    
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
    await callback.message.answer(f"Выберите тариф:", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "admin_cancel")
async def admin_cancel_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("◀️ Возврат в меню", reply_markup=admin_main_menu_kb())
    await callback.answer()
