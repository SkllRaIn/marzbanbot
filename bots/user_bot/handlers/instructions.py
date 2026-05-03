import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select
from core.database import async_session_maker, Subscription
from bots.user_bot.keyboards import instructions_kb

logger = logging.getLogger(__name__)
router = Router()

PLATFORM_INSTRUCTIONS = {
    "inst_ios": (
        "📱 <b>Инструкция для iOS</b>\n\n"
        "1. Скачайте приложение <b>Streisand</b> из App Store\n"
        "2. Нажмите «⚡ Получить ссылку на конфиг» в боте\n"
        "3. Скопируйте ссылку\n"
        "4. В Streisand нажмите «+» → «Импорт из буфера обмена»\n"
        "5. Подключитесь и наслаждайтесь!"
    ),
    "inst_android": (
        "🤖 <b>Инструкция для Android</b>\n\n"
        "1. Скачайте приложение <b>v2rayNG</b> или <b>Hiddify</b> из Google Play / APK\n"
        "2. Нажмите «⚡ Получить ссылку на конфиг» в боте\n"
        "3. Скопируйте ссылку\n"
        "4. В приложении нажмите «+» → «Импорт из буфера обмена»\n"
        "5. Подключитесь!"
    ),
    "inst_windows": (
        "💻 <b>Инструкция для Windows</b>\n\n"
        "1. Скачайте <b>Hiddify</b> или <b>v2rayN</b> с GitHub\n"
        "2. Нажмите «⚡ Получить ссылку на конфиг» в боте\n"
        "3. Скопируйте ссылку\n"
        "4. В приложении: добавить сервер → вставить ссылку\n"
        "5. Запустите VPN!"
    ),
}


@router.message(F.text == "📋 Инструкция")
async def instructions_handler(message: Message):
    await message.answer(
        "📋 <b>Инструкция по подключению</b>\n\n"
        "Выберите вашу платформу или получите ссылку на конфиг:",
        parse_mode="HTML",
        reply_markup=instructions_kb(),
    )


@router.callback_query(F.data == "instructions")
async def instructions_cb(callback: CallbackQuery):
    await callback.message.answer(
        "📋 <b>Инструкция по подключению</b>\n\n"
        "Выберите вашу платформу:",
        parse_mode="HTML",
        reply_markup=instructions_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "get_config")
async def get_config_cb(callback: CallbackQuery):
    async with async_session_maker() as session:
        sub_result = await session.execute(
            select(Subscription).where(
                Subscription.user_tg_id == callback.from_user.id,
                Subscription.status == "active"
            ).order_by(Subscription.expires_at.desc())
        )
        sub = sub_result.scalar_one_or_none()

    if not sub or not sub.sub_url:
        await callback.answer(
            "❌ У вас нет активной подписки. Приобретите VPN в разделе «🛒 Купить VPN».",
            show_alert=True,
        )
        return

    await callback.message.answer(
        f"⚡ <b>Ваша ссылка на конфиг:</b>\n\n"
        f"<code>{sub.sub_url}</code>\n\n"
        f"📋 Скопируйте и добавьте в ваш VPN-клиент.",
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.in_(["inst_ios", "inst_android", "inst_windows"]))
async def platform_inst_cb(callback: CallbackQuery):
    text = PLATFORM_INSTRUCTIONS.get(callback.data, "Инструкция недоступна.")
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()
