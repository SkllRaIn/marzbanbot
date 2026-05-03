"""Shared state and notification helpers between user_bot and admin_bot."""
import logging
from typing import Optional
from aiogram import Bot

logger = logging.getLogger(__name__)

_admin_bot: Optional[Bot] = None
_user_bot: Optional[Bot] = None


def set_admin_bot(bot: Bot):
    global _admin_bot
    _admin_bot = bot


def set_user_bot(bot: Bot):
    global _user_bot
    _user_bot = bot


def get_admin_bot() -> Optional[Bot]:
    return _admin_bot


def get_user_bot() -> Optional[Bot]:
    return _user_bot


async def notify_admin(admin_id: int, text: str, photo_id: Optional[str] = None, reply_markup=None):
    if not _admin_bot:
        logger.warning("Admin bot not set, cannot send notification")
        return
    try:
        if photo_id:
            await _admin_bot.send_photo(admin_id, photo_id, caption=text, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await _admin_bot.send_message(admin_id, text, parse_mode="HTML", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Failed to notify admin {admin_id}: {e}")


async def notify_user(user_tg_id: int, text: str, reply_markup=None):
    if not _user_bot:
        logger.warning("User bot not set, cannot send notification")
        return
    try:
        await _user_bot.send_message(user_tg_id, text, parse_mode="HTML", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Failed to notify user {user_tg_id}: {e}")
