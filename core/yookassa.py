import uuid
import hashlib
import json
import logging
import aiohttp
from typing import Optional
from config import settings
from core.marzban import PLANS

logger = logging.getLogger(__name__)


class YooKassaClient:
    BASE_URL = "https://api.yookassa.ru/v3"

    def __init__(self):
        self.shop_id = settings.YOOKASSA_SHOP_ID
        self.secret_key = settings.YOOKASSA_SECRET_KEY
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            auth = aiohttp.BasicAuth(self.shop_id, self.secret_key)
            self._session = aiohttp.ClientSession(auth=auth)
        return self._session

    async def create_payment(
        self,
        user_tg_id: int,
        plan_id: int,
        amount: float,
        promo_code: Optional[str] = None,
        return_url: Optional[str] = None,
    ) -> dict:
        plan = PLANS[plan_id]
        idempotence_key = str(uuid.uuid4())
        payload = {
            "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
            "payment_method_data": {"type": "bank_card"},
            "confirmation": {
                "type": "redirect",
                "return_url": return_url or f"https://t.me/{settings.REQUIRED_CHANNEL.lstrip('@')}",
            },
            "capture": True,
            "description": f"BlayVPN — {plan['label']} (TG: {user_tg_id})",
            "metadata": {
                "user_tg_id": str(user_tg_id),
                "plan_id": str(plan_id),
                "promo_code": promo_code or "",
            },
        }
        session = await self._get_session()
        async with session.post(
            f"{self.BASE_URL}/payments",
            json=payload,
            headers={"Idempotence-Key": idempotence_key},
        ) as resp:
            data = await resp.json()
            if resp.status != 200:
                logger.error(f"YooKassa create_payment error: {data}")
                raise ValueError(f"YooKassa error: {data.get('description', 'Unknown error')}")
            return data

    async def get_payment(self, payment_id: str) -> dict:
        session = await self._get_session()
        async with session.get(f"{self.BASE_URL}/payments/{payment_id}") as resp:
            return await resp.json()

    def verify_webhook(self, body: bytes, signature: str) -> bool:
        """Verify YooKassa webhook signature."""
        computed = hashlib.sha256(
            (settings.WEBHOOK_SECRET + body.decode()).encode()
        ).hexdigest()
        return computed == signature

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()


yookassa_client = YooKassaClient()
