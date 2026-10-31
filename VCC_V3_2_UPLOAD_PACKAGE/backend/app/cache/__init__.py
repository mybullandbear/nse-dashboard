"""Redis caching layer for NSE data with optional import fallback."""
import json
import logging
from typing import Any, Optional

try:
    import redis.asyncio as redis
    HAS_REDIS = True
except ImportError:
    redis = None
    HAS_REDIS = False

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_redis_pool: Optional[Any] = None


async def get_redis() -> Optional[Any]:
    """Get or create Redis connection."""
    global _redis_pool
    if not HAS_REDIS:
        return None
        
    if _redis_pool is None:
        try:
            _redis_pool = redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )
            await _redis_pool.ping()
            logger.info("Redis connected successfully")
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}. Using in-memory fallback.")
            _redis_pool = None
    return _redis_pool


import time

class CacheManager:
    """Manages caching with Redis (primary) or in-memory dict with TTL (fallback)."""

    def __init__(self):
        self._memory_cache: dict[str, tuple[float, Any]] = {}

    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        val = None
        try:
            r = await get_redis()
            if r:
                raw_val = await r.get(key)
                if raw_val:
                    val = json.loads(raw_val)
        except Exception:
            pass

        if val is None and key in self._memory_cache:
            exp_time, mem_val = self._memory_cache[key]
            if time.time() < exp_time:
                val = mem_val
            else:
                self._memory_cache.pop(key, None)

        if isinstance(val, dict) and "error" in val:
            return None

        return val

    async def set(self, key: str, value: Any, ttl: int = None) -> None:
        """Set value in cache."""
        if ttl is None:
            ttl = settings.REDIS_CACHE_TTL
        exp_time = time.time() + ttl
        self._memory_cache[key] = (exp_time, value)
        try:
            r = await get_redis()
            if r:
                serialized = json.dumps(value, default=str)
                await r.setex(key, ttl, serialized)
        except Exception:
            pass

    async def delete(self, key: str) -> None:
        """Delete value from cache."""
        self._memory_cache.pop(key, None)
        try:
            r = await get_redis()
            if r:
                await r.delete(key)
        except Exception:
            pass

    async def get_all_keys(self, pattern: str = "*") -> list[str]:
        """Get all valid keys matching pattern."""
        now = time.time()
        # Clean expired
        expired = [k for k, (exp, _) in self._memory_cache.items() if now >= exp]
        for k in expired:
            self._memory_cache.pop(k, None)
            
        try:
            r = await get_redis()
            if r:
                return await r.keys(pattern)
        except Exception:
            pass
        return [k for k in self._memory_cache.keys() if pattern == "*" or pattern.rstrip("*") in k]

    async def clear(self) -> None:
        """Clear all keys from cache."""
        self._memory_cache.clear()
        try:
            r = await get_redis()
            if r:
                await r.flushdb()
        except Exception:
            pass


cache = CacheManager()

