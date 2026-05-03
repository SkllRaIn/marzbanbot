from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

def main_menu_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛒 Купить VPN")],
            [KeyboardButton(text="📊 Мой профиль"), KeyboardButton(text="🔑 Мой ключ")],
            [KeyboardButton(text="👥 Реферальная система"), KeyboardButton(text="📋 Инструкции")],
            [KeyboardButton(text="❓ Поддержка")],
        ],
        resize_keyboard=True,
    )

def plans_kb(plans=None):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧪 Тестовый (1 день / 10 GB) - 20 ₽", callback_data="plan_1")],
        [InlineKeyboardButton(text="📱 1 месяц / Безлимит - 169 ₽", callback_data="plan_2")],
        [InlineKeyboardButton(text="🌟 3 месяца / Безлимит - 449 ₽", callback_data="plan_3")],
        [InlineKeyboardButton(text="⭐️ 12 месяцев / Безлимит - 1499 ₽", callback_data="plan_4")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")],
    ])

def payment_confirm_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить", callback_data="confirm_payment")],
        [InlineKeyboardButton(text="◀️ Отмена", callback_data="cancel_payment")],
    ])

def support_cancel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Отмена", callback_data="cancel_support")],
    ])

def referral_kb(ref_link=""):
    buttons = []
    if ref_link:
        buttons.append([InlineKeyboardButton(text="📤 Пригласить друга", url=ref_link)])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def instructions_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🪟 Windows", callback_data="inst_windows")],
        [InlineKeyboardButton(text="🍎 MacOS", callback_data="inst_macos")],
        [InlineKeyboardButton(text="🐧 Linux", callback_data="inst_linux")],
        [InlineKeyboardButton(text="📱 Android", callback_data="inst_android")],
        [InlineKeyboardButton(text="🍏 iOS", callback_data="inst_ios")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")],
    ])

def profile_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 Получить ключ", callback_data="show_key")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")],
    ])

def subscribe_channel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на канал", url="https://t.me/vpnBlay")],
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_subscribe")],
    ])

def back_to_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ В главное меню", callback_data="back_to_menu")],
    ])
