"""
Pool Manager — управление vless-конфигами из pool.txt.

Логика:
  1. Админ пересылает pool.txt как документ в админ-бот
  2. Бот парсит, проверяет TCP + xray, переименовывает по стране
  3. Валидные конфиги сохраняются в Redis (pool:ru / pool:foreign)
  4. При покупке/обновлении подписки: 5 RU + 5 foreign случайных конфигов
  5. При обновлении подписки — pool-конфиги пересматриваются (новые 5+5)
  6. Marzban sub_url остаётся неизменным — конфиги из него не трогаем
"""

import asyncio
import json
import logging
import os
import random
import re
import tempfile
import urllib.parse
from typing import Optional

import aiohttp

from core.redis_client import redis_client

logger = logging.getLogger(__name__)

POOL_RU_KEY = "pool:ru"
POOL_FOREIGN_KEY = "pool:foreign"

# Российские маркеры в метке конфига
RU_MARKERS = ["🇷🇺", "russia", "россия", "moscow", "мск", "spb"]

COUNTRY_EMOJI_MAP = {
    "🇷🇺": "🇷🇺 Россия",
    "🇩🇪": "🇩🇪 Германия",
    "🇫🇷": "🇫🇷 Франция",
    "🇳🇱": "🇳🇱 Нидерланды",
    "🇫🇮": "🇫🇮 Финляндия",
    "🇸🇪": "🇸🇪 Швеция",
    "🇵🇱": "🇵🇱 Польша",
    "🇺🇸": "🇺🇸 США",
    "🇬🇧": "🇬🇧 Великобритания",
    "🇨🇭": "🇨🇭 Швейцария",
    "🇦🇹": "🇦🇹 Австрия",
    "🇨🇿": "🇨🇿 Чехия",
    "🇺🇦": "🇺🇦 Украина",
    "🇱🇹": "🇱🇹 Литва",
    "🇱🇻": "🇱🇻 Латвия",
    "🇪🇪": "🇪🇪 Эстония",
    "🇧🇬": "🇧🇬 Болгария",
    "🇷🇴": "🇷🇴 Румыния",
    "🇸🇬": "🇸🇬 Сингапур",
    "🇯🇵": "🇯🇵 Япония",
    "🇰🇷": "🇰🇷 Корея",
    "🇹🇷": "🇹🇷 Турция",
    "🇲🇩": "🇲🇩 Молдова",
    "🇬🇷": "🇬🇷 Греция",
    "🇧🇪": "🇧🇪 Бельгия",
    "🇨🇦": "🇨🇦 Канада",
    "🇦🇺": "🇦🇺 Австралия",
    "🇭🇰": "🇭🇰 Гонконг",
    "🇩🇰": "🇩🇰 Дания",
    "🇳🇴": "🇳🇴 Норвегия",
    "🇮🇸": "🇮🇸 Исландия",
    "🇮🇹": "🇮🇹 Италия",
    "🇪🇸": "🇪🇸 Испания",
    "🇵🇹": "🇵🇹 Португалия",
    "🇭🇺": "🇭🇺 Венгрия",
    "🇸🇰": "🇸🇰 Словакия",
    "🇸🇮": "🇸🇮 Словения",
    "🇭🇷": "🇭🇷 Хорватия",
    "🇷🇸": "🇷🇸 Сербия",
    "🇧🇦": "🇧🇦 Босния",
    "🇦🇲": "🇦🇲 Армения",
    "🇬🇪": "🇬🇪 Грузия",
    "🇰🇿": "🇰🇿 Казахстан",
    "🇦🇿": "🇦🇿 Азербайджан",
}

# Российские серверы-маркеры (мобильная/LTE/обычные)
RU_LTE_MARKERS = ["мтс", "mts", "beeline", "билайн", "megafon", "мегафон", "tele2", "теле2", "lte", "мобильн", "4g", "mobile"]

BOT_LINK = "@VpnBlay_bot"
BRAND = "BlayVPN"


def _extract_label(config_line: str) -> str:
    """Извлекает метку после # из vless-конфига."""
    try:
        if "#" in config_line:
            fragment = config_line.split("#", 1)[1].strip()
            return urllib.parse.unquote(fragment)
    except Exception:
        pass
    return ""


def _is_russian(label: str) -> bool:
    label_lower = label.lower()
    return any(m in label_lower for m in RU_MARKERS)


def _make_pretty_label(label: str, index: int, expires_at=None) -> str:
    """
    Красивое переименование: BlayVPN | 🇷🇺 Россия #1 | до 01.06.2025 | @VpnBlay_bot
    Российские мобильные/LTE серверы: 🇷🇺 Мобильная связь LTE #1
    Глобальный Anycast: 🌐 Anycast Global #1
    """
    flag_pattern = re.compile(r'[\U0001F1E0-\U0001F1FF]{2}')
    flags = flag_pattern.findall(label)
    label_lower = label.lower()

    # Определяем название страны
    country_name = None
    for flag in flags:
        if flag in COUNTRY_EMOJI_MAP:
            country_name = COUNTRY_EMOJI_MAP[flag]
            break

    # Anycast / глобальный IP
    if "anycast" in label_lower or (not flags and not country_name):
        country_name = "🌐 Anycast Global"

    # Российский LTE/мобильный
    if "🇷🇺 Россия" in (country_name or ""):
        if any(m in label_lower for m in RU_LTE_MARKERS):
            country_name = "🇷🇺 Мобильная связь LTE"

    if not country_name:
        country_name = "🌐 Сервер"

    # Срок действия
    expires_part = ""
    if expires_at:
        try:
            if isinstance(expires_at, str):
                from datetime import datetime as dt
                expires_at = dt.fromisoformat(expires_at)
            expires_part = f" | до {expires_at.strftime('%d.%m.%Y')}"
        except Exception:
            pass

    return f"{country_name} {index}"


def _set_label(config_line: str, new_label: str) -> str:
    """Заменяет метку конфига."""
    base = config_line.rsplit("#", 1)[0] if "#" in config_line else config_line
    return base + "#" + urllib.parse.quote(new_label, safe=" ,.|#()🇦🇧🇨🇩🇪🇫🇬🇭🇮🇯🇰🇱🇲🇳🇴🇵🇶🇷🇸🇹🇺🇻🇼🇽🇾🇿-")


def _parse_host_port(config_line: str) -> Optional[tuple]:
    """Извлекает host и port из vless://."""
    try:
        m = re.match(r'vless://[^@]+@([^:/?#\[\]]+|\[[^\]]+\]):(\d+)', config_line.strip())
        if m:
            return m.group(1).strip("[]"), int(m.group(2))
    except Exception:
        pass
    return None


async def _tcp_check(host: str, port: int, timeout: float = 5.0) -> bool:
    """Быстрая TCP-проверка."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False


def _build_xray_config(config_line: str, socks_port: int) -> dict:
    """Строит конфиг xray для проверки одного vless-конфига."""
    hp = _parse_host_port(config_line)
    if not hp:
        return {}
    host, port = hp

    params = {}
    if "?" in config_line:
        qs = config_line.split("?", 1)[1].split("#")[0]
        params = dict(urllib.parse.parse_qsl(qs))

    # UUID
    m = re.match(r'vless://([^@]+)@', config_line.strip())
    uuid = m.group(1) if m else ""

    user = {"id": uuid, "encryption": "none"}
    if params.get("flow"):
        user["flow"] = params["flow"]

    network = params.get("type", "tcp")
    security = params.get("security", "none")

    stream = {"network": network}
    if security == "reality":
        stream["security"] = "reality"
        stream["realitySettings"] = {
            "serverName": params.get("sni", ""),
            "fingerprint": params.get("fp", "chrome"),
            "publicKey": params.get("pbk", ""),
            "shortId": params.get("sid", ""),
            "spiderX": params.get("spx", ""),
        }
    elif security == "tls":
        stream["security"] = "tls"
        stream["tlsSettings"] = {
            "serverName": params.get("sni", ""),
            "fingerprint": params.get("fp", "chrome"),
            "allowInsecure": params.get("allowInsecure", "0") == "1",
        }

    if network == "ws":
        stream["wsSettings"] = {
            "path": params.get("path", "/"),
            "headers": {"Host": params.get("host", "")}
        }
    elif network == "grpc":
        stream["grpcSettings"] = {
            "serviceName": params.get("serviceName", ""),
            "multiMode": params.get("mode", "gun") == "multi",
        }
    elif network in ("xhttp", "splithttp"):
        stream["xhttpSettings"] = {
            "path": params.get("path", "/"),
            "host": params.get("host", ""),
            "mode": params.get("mode", "auto"),
        }

    return {
        "log": {"loglevel": "none"},
        "inbounds": [{
            "port": socks_port,
            "listen": "127.0.0.1",
            "protocol": "socks",
            "settings": {"auth": "noauth", "udp": False}
        }],
        "outbounds": [{
            "protocol": "vless",
            "settings": {
                "vnext": [{"address": host, "port": port, "users": [user]}]
            },
            "streamSettings": stream,
        }]
    }


async def _xray_check(config_line: str) -> bool:
    """
    Полноценная проверка через xray.
    Если xray не установлен — fallback на TCP.
    """
    xray_bin = "/usr/local/bin/xray"

    hp = _parse_host_port(config_line)
    if not hp:
        return False
    host, port = hp

    # Сначала быстрый TCP
    if not await _tcp_check(host, port, timeout=5.0):
        return False

    if not os.path.exists(xray_bin):
        # xray не установлен — TCP достаточно
        logger.debug(f"xray not found, TCP OK for {host}:{port}")
        return True

    socks_port = random.randint(30000, 50000)
    xray_cfg = _build_xray_config(config_line, socks_port)
    if not xray_cfg:
        return False

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(xray_cfg, f)
        cfg_path = f.name

    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            xray_bin, "run", "-c", cfg_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.sleep(2.0)  # ждём старт

        connector = aiohttp.TCPConnector()
        async with aiohttp.ClientSession(connector=connector) as session:
            try:
                async with session.get(
                    "http://cp.cloudflare.com/generate_204",
                    proxy=f"socks5://127.0.0.1:{socks_port}",
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    return resp.status in (200, 204)
            except Exception as e:
                logger.debug(f"xray traffic check failed {host}:{port}: {e}")
                return False
    except Exception as e:
        logger.debug(f"xray process error {host}:{port}: {e}")
        return False
    finally:
        if proc:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
        try:
            os.unlink(cfg_path)
        except Exception:
            pass


async def process_pool_file(raw_text: str, progress_callback=None, expires_at=None) -> dict:
    """
    Парсит pool.txt, проверяет серверы, переименовывает, сохраняет в Redis.

    expires_at — дата окончания подписки для отображения в метке (datetime или None).
    progress_callback(current, total, text) — для прогресса в Telegram.

    Возвращает {"total", "ru_ok", "foreign_ok", "failed"}
    """
    lines = [
        line.strip()
        for line in raw_text.splitlines()
        if line.strip().startswith("vless://")
    ]

    if not lines:
        return {"total": 0, "ru_ok": 0, "foreign_ok": 0, "failed": 0}

    # Дедупликация по хосту:порту
    seen = set()
    unique_lines = []
    for line in lines:
        hp = _parse_host_port(line)
        key = f"{hp[0]}:{hp[1]}" if hp else line[:80]
        if key not in seen:
            seen.add(key)
            unique_lines.append(line)
    lines = unique_lines

    total = len(lines)
    logger.info(f"Pool: processing {total} unique configs")

    ru_configs, foreign_configs = [], []
    failed = 0
    ru_idx = foreign_idx = 1
    batch_size = 8  # параллельно проверяем по 8

    for i in range(0, total, batch_size):
        batch = lines[i:i + batch_size]
        results = await asyncio.gather(*[_xray_check(c) for c in batch], return_exceptions=True)

        for cfg, result in zip(batch, results):
            if result is True:
                label = _extract_label(cfg)
                if _is_russian(label):
                    pretty = _make_pretty_label(label, ru_idx, expires_at=expires_at)
                    ru_idx += 1
                    ru_configs.append(_set_label(cfg, pretty))
                else:
                    pretty = _make_pretty_label(label, foreign_idx, expires_at=expires_at)
                    foreign_idx += 1
                    foreign_configs.append(_set_label(cfg, pretty))
            else:
                failed += 1

        done = min(i + batch_size, total)
        if progress_callback:
            await progress_callback(
                done, total,
                f"🇷🇺 RU: {len(ru_configs)} | 🌍 Иностр: {len(foreign_configs)} | ❌ Недост: {failed}"
            )
        await asyncio.sleep(0.3)

    await redis_client.set(POOL_RU_KEY, json.dumps(ru_configs))
    await redis_client.set(POOL_FOREIGN_KEY, json.dumps(foreign_configs))

    logger.info(f"Pool saved: {len(ru_configs)} RU, {len(foreign_configs)} foreign, {failed} failed")
    return {"total": total, "ru_ok": len(ru_configs), "foreign_ok": len(foreign_configs), "failed": failed}


async def get_pool_configs(count_ru: int = 5, count_foreign: int = 5, expires_at=None) -> list:
    """
    Возвращает случайные 5 RU + 5 foreign из пула.
    expires_at — дата окончания подписки пользователя (datetime), нужна для красивого названия.
    Конфиги переименовываются «на лету» под конкретного пользователя.
    """
    ru_raw = await redis_client.get(POOL_RU_KEY)
    foreign_raw = await redis_client.get(POOL_FOREIGN_KEY)

    ru_pool = json.loads(ru_raw) if ru_raw else []
    foreign_pool = json.loads(foreign_raw) if foreign_raw else []

    selected_ru = random.sample(ru_pool, min(count_ru, len(ru_pool)))
    selected_foreign = random.sample(foreign_pool, min(count_foreign, len(foreign_pool)))

    def relabel(configs, start_idx=1):
        result = []
        for i, cfg in enumerate(configs):
            label = _extract_label(cfg)
            new_label = _make_pretty_label(label, start_idx + i, expires_at=expires_at)
            result.append(_set_label(cfg, new_label))
        return result

    labeled_ru = relabel(selected_ru, start_idx=1)
    labeled_foreign = relabel(selected_foreign, start_idx=1)

    return labeled_ru + labeled_foreign


async def get_pool_stats() -> dict:
    """Текущая статистика пула."""
    ru_raw = await redis_client.get(POOL_RU_KEY)
    foreign_raw = await redis_client.get(POOL_FOREIGN_KEY)

    ru_pool = json.loads(ru_raw) if ru_raw else []
    foreign_pool = json.loads(foreign_raw) if foreign_raw else []

    return {
        "ru_count": len(ru_pool),
        "foreign_count": len(foreign_pool),
        "total": len(ru_pool) + len(foreign_pool),
    }
