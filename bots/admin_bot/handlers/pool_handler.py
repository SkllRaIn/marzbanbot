"""
Хендлер для загрузки pool.txt в админ-боте.

Поддерживает:
  - Отправку файла pool.txt как документа
  - Отправку текста с vless-конфигами прямо в сообщении
"""

import logging

from aiogram import Router, F
from aiogram.types import Message

from bots.admin_bot.handlers.start import is_admin
from core.pool_manager import process_pool_file, get_pool_stats

logger = logging.getLogger(__name__)
router = Router()


async def _progress_sender(message: Message, status_msg: Message):
    """Замыкание для отправки прогресса в Telegram."""
    async def callback(current: int, total: int, text: str):
        try:
            pct = int(current / total * 100)
            bar_filled = int(pct / 5)
            bar = "█" * bar_filled + "░" * (20 - bar_filled)
            await status_msg.edit_text(
                f"⏳ <b>Обработка pool.txt...</b>\n\n"
                f"[{bar}] {pct}%\n"
                f"{current}/{total} конфигов\n\n"
                f"{text}",
                parse_mode="HTML"
            )
        except Exception:
            pass
    return callback


@router.message(F.document)
async def handle_pool_document(message: Message):
    """Обработка загруженного pool.txt как документа."""
    if not is_admin(message.from_user.id):
        return

    doc = message.document
    if not doc:
        return

    # Принимаем любой текстовый файл или pool.txt
    filename = doc.file_name or ""
    if not (filename.endswith(".txt") or "pool" in filename.lower() or "vless" in filename.lower()):
        # Не наш файл — пропускаем (другие хендлеры обработают)
        return

    status_msg = await message.answer(
        "📥 <b>Получен файл, начинаю обработку...</b>",
        parse_mode="HTML"
    )

    try:
        # Скачиваем файл
        bot = message.bot
        file = await bot.get_file(doc.file_id)
        file_bytes = await bot.download_file(file.file_path)
        raw_text = file_bytes.read().decode("utf-8", errors="ignore")
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка скачивания файла: {e}")
        return

    vless_count = sum(1 for line in raw_text.splitlines() if line.strip().startswith("vless://"))
    if vless_count == 0:
        await status_msg.edit_text("❌ В файле не найдено vless-конфигов.")
        return

    await status_msg.edit_text(
        f"🔍 <b>Найдено {vless_count} конфигов.</b>\n"
        f"Запускаю проверку через xray...\n\n"
        f"⏳ Это займёт несколько минут.",
        parse_mode="HTML"
    )

    progress_cb = await _progress_sender(message, status_msg)

    try:
        result = await process_pool_file(raw_text, progress_callback=progress_cb)
    except Exception as e:
        logger.error(f"Pool processing error: {e}")
        await status_msg.edit_text(f"❌ Ошибка обработки: {e}")
        return

    stats = await get_pool_stats()

    await status_msg.edit_text(
        f"✅ <b>Pool обновлён!</b>\n\n"
        f"📊 <b>Результат проверки:</b>\n"
        f"• Всего в файле: {result['total']}\n"
        f"• 🇷🇺 Россия (рабочих): {result['ru_ok']}\n"
        f"• 🌍 Иностранных (рабочих): {result['foreign_ok']}\n"
        f"• ❌ Недоступных (удалено): {result['failed']}\n\n"
        f"💾 <b>Сейчас в пуле:</b>\n"
        f"• 🇷🇺 RU: {stats['ru_count']} конфигов\n"
        f"• 🌍 Foreign: {stats['foreign_count']} конфигов\n"
        f"• Итого: {stats['total']}\n\n"
        f"При следующем обновлении подписки пользователи получат новые серверы.",
        parse_mode="HTML"
    )


@router.message(F.text.startswith("vless://"))
async def handle_pool_text(message: Message):
    """Обработка vless-конфигов вставленных текстом прямо в чат."""
    if not is_admin(message.from_user.id):
        return

    raw_text = message.text
    vless_count = sum(1 for line in raw_text.splitlines() if line.strip().startswith("vless://"))

    if vless_count == 0:
        return

    status_msg = await message.answer(
        f"🔍 Найдено {vless_count} конфигов в тексте. Проверяю...",
        parse_mode="HTML"
    )

    progress_cb = await _progress_sender(message, status_msg)

    try:
        result = await process_pool_file(raw_text, progress_callback=progress_cb)
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка: {e}")
        return

    stats = await get_pool_stats()
    await status_msg.edit_text(
        f"✅ <b>Pool обновлён!</b>\n\n"
        f"🇷🇺 RU рабочих: {result['ru_ok']}\n"
        f"🌍 Иностр. рабочих: {result['foreign_ok']}\n"
        f"❌ Недоступных: {result['failed']}\n\n"
        f"💾 В пуле сейчас: {stats['total']} конфигов",
        parse_mode="HTML"
    )


@router.message(F.text == "📡 Pool")
async def pool_stats_handler(message: Message):
    """Статистика пула по нажатию кнопки."""
    if not is_admin(message.from_user.id):
        return

    stats = await get_pool_stats()

    if stats["total"] == 0:
        text = (
            "📡 <b>Pool пустой</b>\n\n"
            "Отправьте pool.txt как документ в этот чат.\n"
            "Бот проверит серверы и сохранит рабочие."
        )
    else:
        text = (
            f"📡 <b>Статистика Pool</b>\n\n"
            f"🇷🇺 Российских: {stats['ru_count']}\n"
            f"🌍 Иностранных: {stats['foreign_count']}\n"
            f"📊 Всего: {stats['total']}\n\n"
            f"<i>Пользователи получают 5 RU + 5 иностранных при обновлении подписки.</i>\n\n"
            f"Чтобы обновить пул — отправьте новый pool.txt как документ."
        )

    await message.answer(text, parse_mode="HTML")
