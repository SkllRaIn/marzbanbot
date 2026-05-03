import base64
import logging
import re
import urllib.parse
from datetime import datetime

import aiohttp
from aiohttp import web
from sqlalchemy import select

from core.database import async_session_maker, Subscription
from core.pool_manager import get_pool_configs, COUNTRY_EMOJI_MAP

logger = logging.getLogger(__name__)

_PROTO_RE = re.compile(r'^(vless|vmess|trojan|ss|hysteria2|hysteria|tuic)://', re.IGNORECASE)
_FLAG_RE = re.compile(r'[\U0001F1E0-\U0001F1FF]{2}')

_EN_MAP = {
    "russia": "🇷🇺 Россия", "st petersburg": "🇷🇺 Россия", "moscow": "🇷🇺 Россия",
    "germany": "🇩🇪 Германия", "frankfurt": "🇩🇪 Германия", "falkenstein": "🇩🇪 Германия",
    "france": "🇫🇷 Франция", "paris": "🇫🇷 Франция", "orleans": "🇫🇷 Франция",
    "netherlands": "🇳🇱 Нидерланды", "amsterdam": "🇳🇱 Нидерланды",
    "finland": "🇫🇮 Финляндия", "helsinki": "🇫🇮 Финляндия",
    "sweden": "🇸🇪 Швеция", "stockholm": "🇸🇪 Швеция",
    "poland": "🇵🇱 Польша", "warsaw": "🇵🇱 Польша",
    "united states": "🇺🇸 США", "miami": "🇺🇸 США",
    "united kingdom": "🇬🇧 Великобритания", "london": "🇬🇧 Великобритания",
    "switzerland": "🇨🇭 Швейцария", "austria": "🇦🇹 Австрия",
    "czech": "🇨🇿 Чехия", "ukraine": "🇺🇦 Украина",
    "lithuania": "🇱🇹 Литва", "latvia": "🇱🇻 Латвия",
    "estonia": "🇪🇪 Эстония", "tallinn": "🇪🇪 Эстония",
    "bulgaria": "🇧🇬 Болгария", "romania": "🇷🇴 Румыния",
    "singapore": "🇸🇬 Сингапур", "japan": "🇯🇵 Япония",
    "korea": "🇰🇷 Корея", "turkey": "🇹🇷 Турция",
    "moldova": "🇲🇩 Молдова", "chisinau": "🇲🇩 Молдова",
    "greece": "🇬🇷 Греция", "thessaloniki": "🇬🇷 Греция",
    "belgium": "🇧🇪 Бельгия", "canada": "🇨🇦 Канада",
    "australia": "🇦🇺 Австралия", "hong kong": "🇭🇰 Гонконг",
    "denmark": "🇩🇰 Дания", "norway": "🇳🇴 Норвегия",
    "italy": "🇮🇹 Италия", "spain": "🇪🇸 Испания",
    "serbia": "🇷🇸 Сербия", "armenia": "🇦🇲 Армения",
    "georgia": "🇬🇪 Грузия", "kazakhstan": "🇰🇿 Казахстан",
}
_SAFE = " #🇦🇧🇨🇩🇪🇫🇬🇭🇮🇯🇰🇱🇲🇳🇴🇵🇶🇷🇸🇹🇺🇻🇼🇽🇾🇿🌐-"


def _country(raw_label):
    ll = raw_label.lower()
    for f in _FLAG_RE.findall(raw_label):
        if f in COUNTRY_EMOJI_MAP:
            return COUNTRY_EMOJI_MAP[f]
    for kw, name in _EN_MAP.items():
        if kw in ll:
            return name
    if "anycast" in ll:
        return "🌐 Anycast"
    return None


def _rename_marzban(cfg, index):
    """Переименовываем Marzban конфиги — они идут как основные серверы."""
    cfg = cfg.strip()
    if not _PROTO_RE.match(cfg):
        return cfg
    base = cfg.rsplit("#", 1)[0] if "#" in cfg else cfg
    label = f"🇷🇺 Основной сервер {index}"
    return base + "#" + urllib.parse.quote(label, safe=_SAFE)


async def _fetch_marzban(sub_url):
    if not sub_url:
        return []
    token = sub_url.rstrip("/").rsplit("/", 1)[-1]
    url = f"http://127.0.0.1:8000/sub/{token}"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    logger.warning(f"Marzban {resp.status} for {url}")
                    return []
                raw = await resp.text()
                try:
                    decoded = base64.b64decode(raw.strip()).decode("utf-8")
                    return [l.strip() for l in decoded.splitlines() if l.strip() and _PROTO_RE.match(l.strip())]
                except Exception:
                    return [l.strip() for l in raw.splitlines() if l.strip() and _PROTO_RE.match(l.strip())]
    except Exception as e:
        logger.warning(f"Marzban fetch error: {e}")
        return []


async def handle_subscription(request: web.Request) -> web.Response:
    raw_id = request.match_info.get("user_tg_id", "").replace("user_", "", 1)
    try:
        user_tg_id = int(raw_id)
    except ValueError:
        return web.Response(status=404)

    async with async_session_maker() as session:
        result = await session.execute(
            select(Subscription).where(
                Subscription.user_tg_id == user_tg_id,
                Subscription.status == "active",
            ).order_by(Subscription.expires_at.desc())
        )
        sub = result.scalar_one_or_none()

    # Нет подписки или истекла — один конфиг-заглушка
    if not sub or (sub.expires_at and sub.expires_at < datetime.utcnow()):
        label = urllib.parse.quote("Подписка закончилась — продлите @VpnBlay_bot", safe=_SAFE)
        cfg = f"vless://00000000-0000-0000-0000-000000000000@127.0.0.1:1#{label}"
        encoded = base64.b64encode(cfg.encode()).decode()
        return web.Response(
            text=encoded, content_type="text/plain",
            headers={"Profile-Title": "BlayVPN | no subscription",
                     "Support-URL": "https://t.me/VpnBlay_bot"})

    exp = sub.expires_at
    exp_str = exp.strftime("%d.%m.%Y") if exp else "∞"

    # Marzban конфиги — называем "Основной сервер"
    raw_marz = await _fetch_marzban(sub.sub_url)
    marz_configs = [_rename_marzban(c, i + 1) for i, c in enumerate(raw_marz)]
    logger.info(f"Marzban configs: {len(marz_configs)}")

    # Pool конфиги — метки уже чистые (флаг Страна #N) из pool_manager
    pool_configs = await get_pool_configs(count_ru=5, count_foreign=5, expires_at=exp)
    logger.info(f"Pool configs: {len(pool_configs)}")

    # Сохраняем pool в БД
    async with async_session_maker() as session:
        r2 = await session.execute(
            select(Subscription).where(Subscription.user_tg_id == user_tg_id, Subscription.status == "active")
        )
        s2 = r2.scalar_one_or_none()
        if s2:
            s2.pool_configs = pool_configs
            await session.commit()

    all_configs = marz_configs + pool_configs
    if not all_configs:
        return web.Response(status=204)

    encoded = base64.b64encode("\n".join(all_configs).encode()).decode()
    return web.Response(
        text=encoded, content_type="text/plain",
        headers={
            "Content-Disposition": f'attachment; filename="blayvpn_{user_tg_id}.txt"',
            "Profile-Title": f"BlayVPN | до {exp_str}",
            "Support-URL": "https://t.me/VpnBlay_bot",
        }
    )


def create_subscription_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/sub/{user_tg_id}", handle_subscription)
    return app
