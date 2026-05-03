import redis.asyncio as redis
import logging
from config import settings

logger = logging.getLogger(__name__)


class RedisClient:
    def __init__(self):
        self.client = None

    async def init(self):
        try:
            self.client = await redis.from_url(
                settings.REDIS_URL, 
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5
            )
            await self.client.ping()
            logger.info("Redis connection established")
            return self.client
        except Exception as e:
            logger.error(f"Redis connection failed: {e}")
            self.client = None
            raise

    async def get(self, key: str):
        if not self.client:
            return None
        return await self.client.get(key)

    async def set(self, key: str, value: str, ttl: int = None):
        if not self.client:
            return
        if ttl:
            await self.client.set(key, value, ex=ttl)
        else:
            await self.client.set(key, value)

    async def delete(self, key: str):
        if not self.client:
            return
        await self.client.delete(key)

    async def close(self):
        if self.client:
            await self.client.close()
            logger.info("Redis connection closed")


redis_client = RedisClient()


# Helper functions for cache operations
async def cache_get(key: str):
    return await redis_client.get(key)


async def cache_set(key: str, value: str, ttl: int = None):
    await redis_client.set(key, value, ttl)


async def cache_delete(key: str):
    await redis_client.delete(key)
