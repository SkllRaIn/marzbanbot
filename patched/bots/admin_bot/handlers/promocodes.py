import csv
import io
import secrets
import logging
from datetime import datetime
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select
from core.database import async_session_maker, PromoCode
from bots.admin_bot.keyboards import promo_type_kb, admin_main_menu_kb
from config import settings

logger = logging.getLogger(__name__)
router = Router()

MENU_BUTTONS = [
    "👥 Пользователи", "📊 Статистика", "📦 Промокоды",
    "📢 Рассылка", "💳 Платежи", "📨 Тикеты",
    "🎁 Выдать подписку", "⚙️ Настройки",
]



class PromoStates(StatesGroup):
    waiting_type = State()
    waiting_value = State()
    waiting_limit = State()
    waiting_expires = State()
    waiting_bulk_count = State()
    waiting_bulk_params = State()


def is_admin(tg_id: int) -> bool:
    return tg_id in settings.admin_ids


@router.message(F.text == "📦 Промокоды")
async def promos_handler(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать промокод", callback_data="promo_create")],
        [InlineKeyboardButton(text="📋 Список промокодов", callback_data="promo_list")],
        [InlineKeyboardButton(text="📊 Массовая генерация", callback_data="promo_bulk")],
    ])
    await message.answer("📦 <b>Управление промокодами</b>", parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "promo_create")
async def promo_create_cb(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(PromoStates.waiting_type)
    await callback.message.answer("Выберите тип скидки:", reply_markup=promo_type_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("promo_type:"))
async def promo_type_cb(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    promo_type = callback.data.split(":")[1]
    await state.update_data(promo_type=promo_type)
    await state.set_state(PromoStates.waiting_value)
    unit = "%" if promo_type == "percent" else "₽"
    await callback.message.answer(f"Введите значение скидки ({unit}):")
    await callback.answer()


@router.message(PromoStates.waiting_value)
async def promo_value_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        value = float(message.text.strip())
    except ValueError:
        await message.answer("❌ Введите корректное число.")
        return
    await state.update_data(promo_value=value)
    await state.set_state(PromoStates.waiting_limit)
    await message.answer("Лимит активаций (введите 0 для безлимита):")


@router.message(PromoStates.waiting_limit)
async def promo_limit_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        limit = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введите целое число.")
        return
    await state.update_data(promo_limit=limit if limit > 0 else None)
    await state.set_state(PromoStates.waiting_expires)
    await message.answer("Срок действия (ДД.ММ.ГГГГ) или «-» для бессрочного:")


@router.message(PromoStates.waiting_expires)
async def promo_expires_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    text = message.text.strip()
    expires_at = None
    if text != "-":
        try:
            expires_at = datetime.strptime(text, "%d.%m.%Y")
        except ValueError:
            await message.answer("❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ или «-».")
            return

    data = await state.get_data()
    code = secrets.token_hex(4).upper()

    async with async_session_maker() as session:
        promo = PromoCode(
            code=code,
            type=data["promo_type"],
            value=data["promo_value"],
            max_activations=data.get("promo_limit"),
            expires_at=expires_at,
        )
        session.add(promo)
        await session.commit()

    await state.clear()
    unit = "%" if data["promo_type"] == "percent" else "₽"
    await message.answer(
        f"✅ <b>Промокод создан!</b>\n\n"
        f"🎟 Код: <code>{code}</code>\n"
        f"💰 Скидка: {data['promo_value']}{unit}\n"
        f"🔢 Лимит: {data.get('promo_limit') or '∞'}\n"
        f"📅 Истекает: {expires_at.strftime('%d.%m.%Y') if expires_at else 'Бессрочно'}",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "promo_list")
async def promo_list_cb(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    async with async_session_maker() as session:
        result = await session.execute(
            select(PromoCode).where(PromoCode.is_active == True).order_by(PromoCode.id.desc()).limit(20)
        )
        promos = result.scalars().all()

    if not promos:
        await callback.answer("Нет активных промокодов", show_alert=True)
        return

    text = "📋 <b>Активные промокоды:</b>\n\n"
    for p in promos:
        unit = "%" if p.type == "percent" else "₽"
        text += (
            f"• <code>{p.code}</code> — {p.value}{unit} | "
            f"{p.activations_count}/{p.max_activations or '∞'}\n"
        )
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "promo_bulk")
async def promo_bulk_cb(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(PromoStates.waiting_bulk_count)
    await callback.message.answer("Сколько промокодов сгенерировать?")
    await callback.answer()


@router.message(PromoStates.waiting_bulk_count)
async def promo_bulk_count(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        count = int(message.text.strip())
        if count < 1 or count > 1000:
            raise ValueError()
    except ValueError:
        await message.answer("❌ Введите число от 1 до 1000.")
        return

    await state.update_data(bulk_count=count)
    await state.set_state(PromoStates.waiting_bulk_params)
    await message.answer(
        "Введите параметры в формате:\n"
        "<code>тип значение лимит</code>\n\n"
        "Например: <code>percent 15 1</code> или <code>fixed 200 0</code>\n"
        "(0 = безлимит активаций)",
        parse_mode="HTML",
    )


@router.message(PromoStates.waiting_bulk_params)
async def promo_bulk_params(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.strip().split()
    if len(parts) != 3:
        await message.answer("❌ Неверный формат. Пример: percent 15 1")
        return

    promo_type, value_str, limit_str = parts
    if promo_type not in ("percent", "fixed"):
        await message.answer("❌ Тип должен быть percent или fixed")
        return

    try:
        value = float(value_str)
        limit = int(limit_str)
    except ValueError:
        await message.answer("❌ Неверные значения.")
        return

    data = await state.get_data()
    count = data["bulk_count"]

    codes = []
    async with async_session_maker() as session:
        for _ in range(count):
            code = secrets.token_hex(5).upper()
            promo = PromoCode(
                code=code,
                type=promo_type,
                value=value,
                max_activations=limit if limit > 0 else None,
            )
            session.add(promo)
            codes.append(code)
        await session.commit()

    await state.clear()

    # Generate CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Код", "Тип", "Значение", "Лимит"])
    unit = "%" if promo_type == "percent" else "₽"
    for code in codes:
        writer.writerow([code, promo_type, f"{value}{unit}", limit or "∞"])

    csv_bytes = output.getvalue().encode("utf-8-sig")
    file = BufferedInputFile(csv_bytes, filename=f"promocodes_{count}.csv")
    await message.answer_document(file, caption=f"✅ Сгенерировано {count} промокодов.")
