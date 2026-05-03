import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from core.yookassa import yookassa_client
from core.marzban import PLANS
from config import settings

logger = logging.getLogger(__name__)
router = Router()


class BuyStates(StatesGroup):
    waiting_promo = State()


@router.message(F.text == "🛒 Купить VPN")
async def buy_handler(message: Message, state: FSMContext):
    """Начало покупки - показываем тарифы"""
    await state.clear()
    
    text = "📦 <b>Выберите тариф:</b>"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧪 Тестовый (1 день / 10 GB) - 20 ₽", callback_data="plan_1")],
        [InlineKeyboardButton(text="📱 1 месяц / Безлимит - 169 ₽", callback_data="plan_2")],
        [InlineKeyboardButton(text="🌟 3 месяца / Безлимит - 449 ₽", callback_data="plan_3")],
        [InlineKeyboardButton(text="⭐️ 12 месяцев / Безлимит - 1499 ₽", callback_data="plan_4")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")],
    ])
    
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("plan_"))
async def plan_selected(callback: CallbackQuery, state: FSMContext):
    """Выбор тарифа"""
    plan_id = int(callback.data.split("_")[1])
    plan = PLANS[plan_id]
    
    await state.update_data(plan_id=plan_id)
    
    traffic_text = f"{plan['traffic_gb']} GB" if plan['traffic_gb'] > 0 else "Безлимит"
    devices_text = f"{plan['devices']}" if plan['devices'] > 0 else "Безлимит"
    
    text = (
        f"📦 <b>Тариф:</b> {plan['label']}\n\n"
        f"💰 <b>Цена:</b> {plan['price']} ₽\n"
        f"📊 <b>Трафик:</b> {traffic_text}\n"
        f"🌐 <b>Устройств:</b> {devices_text}\n\n"
        f"🎟 Хотите применить промокод?"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, есть промокод", callback_data="has_promo")],
        [InlineKeyboardButton(text="❌ Нет, оплатить", callback_data="no_promo")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_plans")],
    ])
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "back_to_plans")
async def back_to_plans(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору тарифа"""
    await state.clear()
    
    text = "📦 <b>Выберите тариф:</b>"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧪 Тестовый (1 день / 10 GB) - 20 ₽", callback_data="plan_1")],
        [InlineKeyboardButton(text="📱 1 месяц / Безлимит - 169 ₽", callback_data="plan_2")],
        [InlineKeyboardButton(text="🌟 3 месяца / Безлимит - 449 ₽", callback_data="plan_3")],
        [InlineKeyboardButton(text="⭐️ 12 месяцев / Безлимит - 1499 ₽", callback_data="plan_4")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")],
    ])
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "has_promo")
async def promo_handler(callback: CallbackQuery, state: FSMContext):
    """Запрос промокода"""
    await state.set_state(BuyStates.waiting_promo)
    await callback.message.answer("🎟 Введите промокод:")
    await callback.answer()


@router.callback_query(F.data == "no_promo")
async def no_promo_handler(callback: CallbackQuery, state: FSMContext):
    """Оплата без промокода"""
    data = await state.get_data()
    plan_id = data.get("plan_id")
    plan = PLANS[plan_id]
    user_tg_id = callback.from_user.id
    
    try:
        payment_url = await yookassa_client.create_payment(
            amount=plan["price"],
            description=f"Подписка {plan['label']}",
            user_tg_id=user_tg_id,
            plan_id=plan_id
        )
        
        text = (
            f"💳 <b>Оплата заказа</b>\n\n"
            f"📦 Тариф: {plan['label']}\n"
            f"💰 К оплате: {plan['price']} ₽\n\n"
            f"Нажмите кнопку ниже для оплаты:"
        )
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=payment_url)],
            [InlineKeyboardButton(text="◀️ Отмена", callback_data="cancel_payment")],
        ])
        
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        await state.clear()
        
    except Exception as e:
        logger.error(f"YooKassa error: {e}")
        await callback.message.answer("❌ Ошибка при создании платежа. Попробуйте позже.")
    
    await callback.answer()


@router.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: CallbackQuery, state: FSMContext):
    """Отмена оплаты"""
    await state.clear()
    await callback.message.answer("❌ Оплата отменена.", reply_markup=back_to_menu_kb())
    await callback.answer()


@router.message(BuyStates.waiting_promo)
async def process_promo(message: Message, state: FSMContext):
    """Обработка промокода"""
    promo_code = message.text.strip().upper()
    data = await state.get_data()
    plan_id = data.get("plan_id")
    plan = PLANS[plan_id]
    user_tg_id = message.from_user.id
    
    # Проверка промокода (заглушка, нужно реализовать проверку в БД)
    discount = 0
    if promo_code == "TEST10":
        discount = 10
    elif promo_code == "WELCOME20":
        discount = 20
    
    final_price = plan["price"] * (100 - discount) // 100
    
    if discount > 0:
        text = (
            f"✅ <b>Промокод применён!</b>\n\n"
            f"📦 Тариф: {plan['label']}\n"
            f"💰 Скидка: {discount}%\n"
            f"🏷 Итого: {final_price} ₽"
        )
    else:
        text = (
            f"❌ <b>Промокод не найден!</b>\n\n"
            f"📦 Тариф: {plan['label']}\n"
            f"💰 К оплате: {plan['price']} ₽"
        )
    
    try:
        payment_url = await yookassa_client.create_payment(
            amount=final_price,
            description=f"Подписка {plan['label']} {f'(промокод {promo_code})' if discount > 0 else ''}",
            user_tg_id=user_tg_id,
            plan_id=plan_id,
            promo_code=promo_code if discount > 0 else None
        )
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=payment_url)],
            [InlineKeyboardButton(text="◀️ Отмена", callback_data="cancel_payment")],
        ])
        
        await message.answer(text, parse_mode="HTML", reply_markup=kb)
        await state.clear()
        
    except Exception as e:
        logger.error(f"YooKassa error: {e}")
        await message.answer("❌ Ошибка при создании платежа. Попробуйте позже.")


def back_to_menu_kb():
    from bots.user_bot.keyboards import main_menu_kb
    return main_menu_kb()
