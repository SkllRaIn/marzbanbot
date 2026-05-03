import logging
import secrets
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from core.redis_client import redis_client
from bots.admin_bot.keyboards import admin_main_menu_kb
from config import settings

logger = logging.getLogger(__name__)
router = Router()

OTP_TTL = 300  # 5 minutes


class AdminAuthStates(StatesGroup):
    waiting_otp = State()


def is_admin(tg_id: int) -> bool:
    return tg_id in settings.admin_ids


@router.message(CommandStart())
async def admin_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    session_key = f"admin_session:{message.from_user.id}"
    session_data = await redis_client.get(session_key)

    # Parse session data properly
    is_authenticated = False
    if session_data:
        try:
            import json
            session = json.loads(session_data) if isinstance(session_data, str) else session_data
            is_authenticated = session.get("authenticated", False) if isinstance(session, dict) else False
        except:
            is_authenticated = False

    if is_authenticated:
        await message.answer("👋 С возвращением!", reply_markup=admin_main_menu_kb())
        return

    # Generate OTP
    otp = secrets.token_hex(3).upper()
    await redis_client.set(f"admin_otp:{message.from_user.id}", otp, ttl=OTP_TTL)
    await state.set_state(AdminAuthStates.waiting_otp)

    logger.info(f"Admin OTP for {message.from_user.id}: {otp}")
    await message.answer(
        f"🔐 <b>Введите одноразовый код доступа</b>\n\n"
        f"Код отправлен в консоль сервера (journalctl -u blayvpn).\n"
        f"Код действителен 5 минут.",
        parse_mode="HTML",
    )


@router.message(AdminAuthStates.waiting_otp)
async def verify_otp(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    otp_key = f"admin_otp:{message.from_user.id}"
    stored_otp = await redis_client.get(otp_key)

    if not stored_otp or message.text.strip().upper() != stored_otp:
        await message.answer("❌ Неверный код. Попробуйте снова /start")
        return

    session_key = f"admin_session:{message.from_user.id}"
    import json
    session_data = json.dumps({"authenticated": True, "auth_at": datetime.utcnow().isoformat()})
    await redis_client.set(session_key, session_data, ttl=86400)
    await state.clear()

    await message.answer(
        "✅ <b>Авторизация прошла успешно!</b>\n\nДобро пожаловать в панель управления BlayVPN.",
        parse_mode="HTML",
        reply_markup=admin_main_menu_kb(),
    )


@router.callback_query(F.data == "admin_cancel")
async def admin_cancel_cb(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Отменено.", reply_markup=admin_main_menu_kb())
    await callback.answer()
