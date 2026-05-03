import aiohttp
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
from config import settings

logger = logging.getLogger(__name__)

PLANS = {
    1: {"days": 1, "price": 20, "traffic_gb": 10, "devices": 0, "label": "Тестовый (1 день / 10 GB)"},
    2: {"days": 30, "price": 169, "traffic_gb": 0, "devices": 0, "label": "1 месяц / Безлимит"},
    3: {"days": 90, "price": 449, "traffic_gb": 0, "devices": 0, "label": "3 месяца / Безлимит"},
    4: {"days": 365, "price": 1499, "traffic_gb": 0, "devices": 0, "label": "12 месяцев / Безлимит"},
}


class MarzbanClient:
    def __init__(self):
        self.base_url = settings.MARZBAN_API_URL.rstrip('/')
        self.username = settings.MARZBAN_USERNAME
        self.password = settings.MARZBAN_PASSWORD
        self._token: Optional[str] = None
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _auth(self) -> str:
        """Get admin token from Marzban"""
        session = await self._get_session()
        async with session.post(
            f"{self.base_url}/api/admin/token",
            data={"grant_type": "password", "username": self.username, "password": self.password}
        ) as resp:
            data = await resp.json()
            self._token = data.get("access_token")
            if not self._token:
                raise Exception(f"Auth failed: {data}")
            logger.info("Successfully authenticated with Marzban")
            return self._token

    async def _headers(self) -> dict:
        if not self._token:
            await self._auth()
        return {"Authorization": f"Bearer {self._token}"}

    async def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        session = await self._get_session()
        headers = await self._headers()
        url = f"{self.base_url}{path}"

        try:
            async with session.request(method, url, headers=headers, **kwargs) as resp:
                if resp.status == 401:
                    await self._auth()
                    return await self._request(method, path, **kwargs)
                if resp.status >= 400:
                    text = await resp.text()
                    logger.error(f"API error {resp.status}: {text}")
                    raise Exception(f"API error {resp.status}: {text}")
                return await resp.json()
        except aiohttp.ClientError as e:
            logger.error(f"Request failed: {e}")
            raise

    async def get_user(self, username: str) -> Dict[str, Any]:
        """Get user by username"""
        return await self._request("GET", f"/api/user/{username}")

    async def get_user_subscription_url(self, username: str) -> str:
        """Get subscription URL for user - returns full URL without /api"""
        user = await self.get_user(username)
        sub_url = user.get("subscription_url")
        if sub_url:
            # Build full URL using SERVER_DOMAIN (without /api)
            full_url = f"https://{settings.SERVER_DOMAIN}{sub_url}"
            logger.info(f"Subscription URL: {full_url}")
            return full_url
        links = user.get("links", [])
        if links:
            logger.info(f"Found link: {links[0]}")
            return links[0]
        raise Exception(f"No subscription URL found for user {username}")

    async def create_user(self, username: str, expire: int = 0, data_limit: int = 0) -> Dict[str, Any]:
        """Create user in Marzban"""
        data = {
            "username": username,
            "proxies": {"shadowsocks": {}},
            "expire": expire,
            "data_limit": data_limit,
            "status": "active"
        }
        logger.info(f"Creating user in Marzban: {username}")
        return await self._request("POST", "/api/user", json=data)

    async def update_user(self, username: str, **kwargs) -> Dict[str, Any]:
        """Update user in Marzban"""
        logger.info(f"Updating user {username} with {kwargs}")
        return await self._request("PUT", f"/api/user/{username}", json=kwargs)

    async def ensure_user_exists(self, username: str, expire: int = 0) -> str:
        """Ensure user exists, create if not, return subscription URL"""
        try:
            user = await self.get_user(username)
            logger.info(f"User {username} exists, updating expire to {expire}")
            await self.update_user(username, expire=expire)
        except Exception:
            logger.info(f"User {username} not found, creating new user")
            await self.create_user(username, expire=expire)
        
        return await self.get_user_subscription_url(username)


marzban_client = MarzbanClient()
