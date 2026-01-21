"""User cache for fast balance and model lookups.

This module provides caching for user data that is frequently accessed:
- Balance (for balance_middleware checks)
- Model ID (for model selection)

Uses cache-aside pattern:
1. Check cache first
2. If miss, load from DB and cache
3. Invalidate on updates

TTL: 60 seconds (balance changes frequently)

NO __init__.py - use direct import:
    from cache.user_cache import get_cached_user, cache_user, invalidate_user
"""

from decimal import Decimal
import json
import time
from typing import Optional, TypedDict

from cache.client import get_redis
from cache.keys import user_key
from cache.keys import USER_TTL
from utils.metrics import record_cache_operation
from utils.metrics import record_redis_operation_time
from utils.structured_logging import get_logger

logger = get_logger(__name__)


class CachedUserData(TypedDict):
    """Cached user data structure."""

    balance: str  # Decimal as string for JSON serialization
    model_id: str
    first_name: str
    username: Optional[str]
    cached_at: float


async def get_cached_user(user_id: int) -> Optional[CachedUserData]:
    """Get cached user data.

    Args:
        user_id: Telegram user ID.

    Returns:
        CachedUserData dict if found, None if not cached or Redis unavailable.
    """
    start_time = time.time()
    redis = await get_redis()

    if redis is None:
        logger.debug("user_cache.redis_unavailable", user_id=user_id)
        return None

    try:
        key = user_key(user_id)
        data = await redis.get(key)

        elapsed = time.time() - start_time
        record_redis_operation_time("get", elapsed)

        if data is None:
            record_cache_operation("user", hit=False)
            logger.debug("user_cache.miss",
                         user_id=user_id,
                         elapsed_ms=elapsed * 1000)
            return None

        record_cache_operation("user", hit=True)
        cached = json.loads(data.decode("utf-8"))

        logger.debug(
            "user_cache.hit",
            user_id=user_id,
            balance=cached.get("balance"),
            model_id=cached.get("model_id"),
            elapsed_ms=elapsed * 1000,
        )

        return cached

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning("user_cache.get_error", user_id=user_id, error=str(e))
        return None


async def cache_user(
    user_id: int,
    balance: Decimal,
    model_id: str,
    first_name: str,
    username: Optional[str] = None,
) -> bool:
    """Cache user data.

    Args:
        user_id: Telegram user ID.
        balance: User balance in USD.
        model_id: Selected model ID.
        first_name: User's first name.
        username: User's username (optional).

    Returns:
        True if cached successfully, False otherwise.
    """
    start_time = time.time()
    redis = await get_redis()

    if redis is None:
        logger.debug("user_cache.redis_unavailable", user_id=user_id)
        return False

    try:
        key = user_key(user_id)
        data: CachedUserData = {
            "balance": str(balance),
            "model_id": model_id,
            "first_name": first_name,
            "username": username,
            "cached_at": time.time(),
        }

        await redis.setex(key, USER_TTL, json.dumps(data))

        elapsed = time.time() - start_time
        record_redis_operation_time("set", elapsed)

        logger.debug(
            "user_cache.set",
            user_id=user_id,
            balance=str(balance),
            model_id=model_id,
            ttl=USER_TTL,
            elapsed_ms=elapsed * 1000,
        )

        return True

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning("user_cache.set_error", user_id=user_id, error=str(e))
        return False


async def invalidate_user(user_id: int) -> bool:
    """Invalidate cached user data.

    Call this after any balance or model_id changes.

    Args:
        user_id: Telegram user ID.

    Returns:
        True if invalidated successfully, False otherwise.
    """
    start_time = time.time()
    redis = await get_redis()

    if redis is None:
        logger.debug("user_cache.redis_unavailable", user_id=user_id)
        return False

    try:
        key = user_key(user_id)
        deleted = await redis.delete(key)

        elapsed = time.time() - start_time
        record_redis_operation_time("delete", elapsed)

        logger.debug(
            "user_cache.invalidated",
            user_id=user_id,
            deleted=deleted,
            elapsed_ms=elapsed * 1000,
        )

        return deleted > 0

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning("user_cache.invalidate_error",
                       user_id=user_id,
                       error=str(e))
        return False


def get_balance_from_cached(cached: CachedUserData) -> Decimal:
    """Extract balance as Decimal from cached data.

    Args:
        cached: CachedUserData dict.

    Returns:
        Balance as Decimal.
    """
    return Decimal(cached["balance"])
