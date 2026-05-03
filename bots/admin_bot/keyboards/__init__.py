from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)


def admin_main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👥 Пользователи"), KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="📦 Промокоды"), KeyboardButton(text="📢 Рассылка")],
            [KeyboardButton(text="💳 Платежи"), KeyboardButton(text="📨 Тикеты")],
            [KeyboardButton(text="🎁 Выдать подписку"), KeyboardButton(text="📡 Pool")],
        ],
        resize_keyboard=True,
    )


def user_card_kb(tg_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎁 Выдать подписку", callback_data=f"admin_give_sub:{tg_id}"),
            InlineKeyboardButton(text="📅 Продлить", callback_data=f"admin_extend:{tg_id}"),
        ],
        [
            InlineKeyboardButton(text="🚫 Заблокировать", callback_data=f"admin_ban:{tg_id}"),
            InlineKeyboardButton(text="✅ Разблокировать", callback_data=f"admin_unban:{tg_id}"),
        ],
        [
            InlineKeyboardButton(text="💰 Начислить баланс", callback_data=f"admin_add_balance:{tg_id}"),
            InlineKeyboardButton(text="🔄 Сбросить трафик", callback_data=f"admin_reset_traffic:{tg_id}"),
        ],
        [
            InlineKeyboardButton(text="💳 История платежей", callback_data=f"admin_payments:{tg_id}"),
            InlineKeyboardButton(text="🔑 Конфиг", callback_data=f"admin_config:{tg_id}"),
        ],
    ])


def ticket_kb(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Ответить", callback_data=f"ticket_reply:{ticket_id}"),
            InlineKeyboardButton(text="❌ Закрыть", callback_data=f"ticket_close:{ticket_id}"),
        ]
    ])


def broadcast_audience_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Все пользователи", callback_data="bc_audience:all")],
        [InlineKeyboardButton(text="✅ Активные подписки", callback_data="bc_audience:active")],
        [InlineKeyboardButton(text="⚠️ Истекают через 3 дня", callback_data="bc_audience:expiring")],
        [InlineKeyboardButton(text="💤 Никогда не платили", callback_data="bc_audience:no_pay")],
        [InlineKeyboardButton(text="🔗 Рефералы", callback_data="bc_audience:referrals")],
        [InlineKeyboardButton(text="◀️ Отмена", callback_data="admin_cancel")],
    ])


def promo_type_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="% Процент", callback_data="promo_type:percent"),
            InlineKeyboardButton(text="₽ Фиксированная", callback_data="promo_type:fixed"),
        ],
        [InlineKeyboardButton(text="◀️ Отмена", callback_data="admin_cancel")],
    ])


def confirm_kb(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm:{action}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel"),
        ]
    ])
