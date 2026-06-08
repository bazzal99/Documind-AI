import redis.asyncio as aioredis
from typing import Optional
from backend.app.core.config import settings
import structlog

logger = structlog.get_logger()


class CacheService:
    """
    Wrapper around Redis.
    All Redis operations go through this class.
    """

    def __init__(self):
        self._client: Optional[aioredis.Redis] = None

    async def get_client(self) -> aioredis.Redis:
        """
        Returns Redis client, creating it if it doesn't exist.
        Uses a single shared connection pool for efficiency.
        """
        if self._client is None:
            self._client = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,  # returns strings instead of bytes
            )
        return self._client

    # ── Token blacklist ───────────────────────────────────────────────────────

    async def blacklist_token(self, token: str, expires_in_seconds: int) -> None:
        """
        Adds a token to the blacklist when user logs out.
        Token automatically removed from Redis after it would have expired anyway.
        """
        client = await self.get_client()
        key = f"blacklist:{token}"
        await client.setex(key, expires_in_seconds, "1")
        logger.info("Token blacklisted")

    async def is_token_blacklisted(self, token: str) -> bool:
        """
        Checks if a token has been blacklisted (user logged out).
        Called on every protected API request.
        """
        client = await self.get_client()
        key = f"blacklist:{token}"
        result = await client.get(key)
        return result is not None

    # ── Rate limiting ─────────────────────────────────────────────────────────

    async def check_rate_limit(self, user_id: str, limit: int = 20) -> tuple[bool, int]:
        """
        Checks if user has exceeded their request limit (default 20/minute).
        Returns: (is_allowed, requests_remaining)

        How it works:
        - First request: create counter = 1, set expiry to 60 seconds
        - Each request: increment counter
        - If counter > limit: reject the request
        - After 60 seconds: counter resets automatically
        """
        client = await self.get_client()
        key = f"rate_limit:{user_id}"

        # Increment counter (creates it at 1 if it doesn't exist)
        current = await client.incr(key)

        # Set expiry only on first request (so it resets after 60s)
        if current == 1:
            await client.expire(key, 60)

        remaining = max(0, limit - current)
        is_allowed = current <= limit

        return is_allowed, remaining

    # ── General cache ─────────────────────────────────────────────────────────

    async def set(self, key: str, value: str, expires_in_seconds: int = 3600) -> None:
        """Store any value with an expiry time."""
        client = await self.get_client()
        await client.setex(key, expires_in_seconds, value)

    async def get(self, key: str) -> Optional[str]:
        """Retrieve a cached value. Returns None if not found or expired."""
        client = await self.get_client()
        return await client.get(key)

    async def delete(self, key: str) -> None:
        """Delete a cached value."""
        client = await self.get_client()
        await client.delete(key)

    async def close(self) -> None:
        """Close Redis connection cleanly on app shutdown."""
        if self._client:
            await self._client.aclose()


# Single instance shared across the entire app
cache_service = CacheService()
