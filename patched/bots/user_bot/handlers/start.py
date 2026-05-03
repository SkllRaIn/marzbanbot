import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from core.database import async_session_maker, User
from bots.user_bot.keyboards import main_menu_kb, subscribe_channel_kb

from bots.user_bot.keyboards import main_menu_kb, subscribe_channel_kb
from config import settings

logger = logging.getLogger(__name__)
router = Router()

WELCOME_TEXT = """🌐 <b>Добро пожаловать в BlayVPN!</b>

Быстрый, безопасный и анонимный VPN.

🔐 Для доступа подпишитесь на канал:
➡️ {channel}

После подписки нажмите «Проверить»."""


async def check_channel_subscription(bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(settings.REQUIRED_CHANNEL_ID, user_id)
        return member.status not in ("left", "kicked", "banned")
    except Exception as e:
        logger.warning(f"Failed to check channel membership for {user_id}: {e}")
        return False


async def get_or_create_user(tg_id: int, first_name: str, username: str, referrer_id: int = None) -> User:
    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.tg_id == tg_id))
        user = result.scalar_one_or_none()
        if not user:
            user = User(
                tg_id=tg_id,
                first_name=first_name,
                username=username,
                referrer_id=referrer_id,
            )
            session.add(user)
            # Record referral if referrer exists
            if referrer_id:
                ref_result = await session.execute(select(User).where(User.tg_id == referrer_id))
                referrer = ref_result.scalar_one_or_none()
                if referrer:
                    from core.database import Referral
                    referral = Referral(referrer_id=referrer_id, referred_id=tg_id)
                    session.add(referral)
            await session.commit()
            await session.refresh(user)
        return user


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    args = message.text.split(maxsplit=1)
    referrer_id = None

    if len(args) > 1:
        param = args[1]
        if param.startswith("ref_"):
            try:
                referrer_id = int(param[4:])
            except ValueError:
                pass

    user = await get_or_create_user(
        tg_id=message.from_user.id,
        first_name=message.from_user.first_name or "",
        username=message.from_user.username or "",
        referrer_id=referrer_id,
    )

    if user.is_banned:
        await message.answer("❌ Ваш аккаунт заблокирован. Обратитесь в поддержку.")
        return

    subscribed = await check_channel_subscription(message.bot, message.from_user.id)
    if not subscribed:
        await message.answer(
            WELCOME_TEXT.format(channel=settings.REQUIRED_CHANNEL),
            parse_mode="HTML",
            reply_markup=subscribe_channel_kb(),
        )
        return

    await message.answer(
        f"👋 Привет, <b>{message.from_user.first_name}</b>!\n\nВыберите действие:",
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )


@router.callback_query(F.data == "check_subscription")
async def check_subscription_cb(callback: CallbackQuery):
    subscribed = await check_channel_subscription(callback.bot, callback.from_user.id)
    if not subscribed:
        await callback.answer("❌ Вы ещё не подписались на канал!", show_alert=True)
        return

    await callback.message.edit_text(
        f"✅ Подписка подтверждена! Добро пожаловать, <b>{callback.from_user.first_name}</b>!",
        parse_mode="HTML",
    )
    await callback.message.answer(
        "Выберите действие:",
        reply_markup=main_menu_kb(),
    )


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Главное меню:", reply_markup=main_menu_kb())
    await callback.answer()
