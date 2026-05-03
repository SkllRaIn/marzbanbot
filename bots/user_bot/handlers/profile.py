import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from core.database import async_session_maker, User, Subscription
from bots.user_bot.keyboards import main_menu_kb

logger = logging.getLogger(__name__)
router = Router()


def subscription_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для страницы с подпиской"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Инструкция", callback_data="instructions")],
        [InlineKeyboardButton(text="❓ Поддержка", callback_data="support")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")],
    ])


@router.message(F.text == "📊 Мой профиль")
async def show_profile(message: Message):
    user_tg_id = message.from_user.id
    
    async with async_session_maker() as session:
        user_result = await session.execute(select(User).where(User.tg_id == user_tg_id))
        user = user_result.scalar_one_or_none()
        
        sub_result = await session.execute(
            select(Subscription).where(
                Subscription.user_tg_id == user_tg_id,
                Subscription.status == "active"
            ).order_by(Subscription.expires_at.desc())
        )
        sub = sub_result.scalar_one_or_none()
    
    if not user:
        await message.answer("❌ Пользователь не найден. Нажмите /start")
        return
    
    if sub and sub.expires_at:
        days_left = (sub.expires_at - datetime.utcnow()).days
        if days_left < 0:
            expires_text = "❌ Подписка истекла"
        else:
            expires_text = f"✅ Активна до: {sub.expires_at.strftime('%d.%m.%Y')} (осталось {days_left} дн.)"
    else:
        expires_text = "❌ Нет активной подписки"
    
    text = (
        f"👤 <b>Ваш профиль</b>\n\n"
        f"🆔 ID: <code>{user.tg_id}</code>\n"
        f"👤 Username: @{user.username or 'Не указан'}\n"
        f"💰 Баланс: {float(user.balance):.0f} ₽\n\n"
        f"{expires_text}\n\n"
        f"🔑 Нажмите «Мой ключ» для получения ссылки на подписку"
    )
    
    await message.answer(text, parse_mode="HTML", reply_markup=subscription_keyboard())


@router.message(F.text == "🔑 Мой ключ")
@router.callback_query(F.data == "show_key")
async def show_key(message_or_callback):
    """Показать ссылку на подписку"""
    if isinstance(message_or_callback, CallbackQuery):
        message = message_or_callback.message
        user_tg_id = message_or_callback.from_user.id
        await message_or_callback.answer()
    else:
        message = message_or_callback
        user_tg_id = message.from_user.id
    
    # Получаем подписку из локальной БД
    async with async_session_maker() as session:
        result = await session.execute(
            select(Subscription).where(
                Subscription.user_tg_id == user_tg_id,
                Subscription.status == "active"
            ).order_by(Subscription.expires_at.desc())
        )
        sub = result.scalar_one_or_none()
    
    if not sub:
        await message.answer(
            "❌ У вас нет активной подписки.\n\n"
            "Купите подписку в разделе «🛒 Купить VPN»"
        )
        return
    
    # Генерируем ссылку на подписку
    sub_url = f"https://panel.komissarovka.ru/sub/user_{user_tg_id}"

    if sub.expires_at:
        days_left = (sub.expires_at - datetime.utcnow()).days
        if days_left < 0:
            status_icon = "❌"
            expires_text = f"Истекла {sub.expires_at.strftime('%d.%m.%Y')} — продлите в @VpnBlay_bot"
        elif days_left <= 3:
            status_icon = "⚠️"
            expires_text = f"Истекает {sub.expires_at.strftime('%d.%m.%Y')} (осталось {days_left} дн.) — продлите в @VpnBlay_bot"
        else:
            status_icon = "✅"
            expires_text = f"Активна до {sub.expires_at.strftime('%d.%m.%Y')} · осталось {days_left} дн."
    else:
        status_icon = "✅"
        expires_text = "Бессрочная"

    await message.answer(
        f"🔑 <b>Ваша подписка BlayVPN</b>\n\n"
        f"{status_icon} {expires_text}\n"
        f"📊 Трафик: {'Безлимит' if not sub.traffic_limit_gb else f'{sub.traffic_limit_gb} GB'}\n\n"
        f"📎 <b>Ссылка для подключения:</b>\n"
        f"<code>{sub_url}</code>\n\n"
        f"📱 <b>Как подключиться:</b>\n"
        f"1. Скопируйте ссылку выше\n"
        f"2. Откройте приложение: Nekobox / v2rayNG / Hiddify\n"
        f"3. Нажмите «Импорт из буфера обмена»\n"
        f"4. Готово — серверы загружены автоматически 🎉\n\n"
        f"🔄 Серверы обновляются при каждом обновлении подписки в приложении\n"
        f"💬 Поддержка: @VpnBlay_bot",
        parse_mode="HTML",
        reply_markup=subscription_keyboard()
    )


@router.callback_query(F.data == "instructions")
async def instructions_callback(callback: CallbackQuery):
    text = (
        "📋 <b>Инструкция по подключению</b>\n\n"
        "1️⃣ Скачайте приложение:\n"
        "   • Android: NekoBox, v2rayNG, Hiddify\n"
        "   • iOS: Streisand, Shadowrocket\n"
        "   • Windows/Mac: NekoBox, v2rayN\n\n"
        "2️⃣ Скопируйте ссылку из раздела «Мой ключ»\n\n"
        "3️⃣ В приложении нажмите «Импорт из буфера обмена»\n\n"
        "4️⃣ Включите подключение\n\n"
        "🔁 При проблемах нажмите «Обновить подписку» в приложении"
    )
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "support")
async def support_callback(callback: CallbackQuery):
    text = (
        "❓ <b>Поддержка</b>\n\n"
        "По всем вопросам обращайтесь:\n"
        "📱 Telegram: @blayvpn_support\n"
        "📧 Email: support@blayvpn.ru\n\n"
        "⏰ Обычно отвечаем в течение 15 минут"
    )
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery):
    await callback.message.answer("🏠 Главное меню", reply_markup=main_menu_kb())
    await callback.answer()
