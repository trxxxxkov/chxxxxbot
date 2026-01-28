"""E2B Sandbox caching for reuse between execute_python calls.

Sandboxes are expensive to create (~2-5 seconds). By caching sandbox_id:
- Packages (apt-get, pip) stay installed between calls
- Intermediate files persist for iterative work
- Input files don't need re-upload
- Faster iteration on code fixes

TTL: 3600 seconds (1 hour) — same as EXEC_FILE_TTL
Key: sandbox:{thread_id}

E2B sandboxes auto-terminate after idle timeout (configurable, default ~5 min).
If reconnect fails, we simply create a new sandbox.

NO __init__.py - use direct import:
    from cache.sandbox_cache import (
        get_cached_sandbox, cache_sandbox, invalidate_sandbox
    )
"""

import json
import time
from typing import Optional, TypedDict

from cache.client import get_redis
from cache.keys import sandbox_key
from cache.keys import SANDBOX_TTL
from utils.structured_logging import get_logger

logger = get_logger(__name__)


class SandboxMeta(TypedDict):
    """Metadata for cached sandbox."""

    sandbox_id: str
    created_at: float
    last_used: float


async def get_cached_sandbox(thread_id: int) -> Optional[str]:
    """Get cached sandbox_id for thread.

    Args:
        thread_id: Internal thread ID.

    Returns:
        sandbox_id if exists and valid, None otherwise.
    """
    if not thread_id:
        return None

    redis = await get_redis()
    key = sandbox_key(thread_id)

    try:
        data = await redis.get(key)
        if not data:
            logger.debug("sandbox_cache.miss", thread_id=thread_id)
            return None

        meta: SandboxMeta = json.loads(data)
        sandbox_id = meta.get("sandbox_id")

        logger.info(
            "sandbox_cache.hit",
            thread_id=thread_id,
            sandbox_id=sandbox_id,
            age_seconds=int(time.time() - meta.get("created_at", 0)),
        )
        return sandbox_id

    except Exception as e:
        logger.info(
            "sandbox_cache.get_error",
            thread_id=thread_id,
            error=str(e),
        )
        return None


async def cache_sandbox(thread_id: int, sandbox_id: str) -> bool:
    """Cache sandbox_id for thread.

    Args:
        thread_id: Internal thread ID.
        sandbox_id: E2B sandbox ID to cache.

    Returns:
        True if cached successfully, False otherwise.
    """
    if not thread_id or not sandbox_id:
        return False

    redis = await get_redis()
    key = sandbox_key(thread_id)
    now = time.time()

    meta: SandboxMeta = {
        "sandbox_id": sandbox_id,
        "created_at": now,
        "last_used": now,
    }

    try:
        await redis.setex(key, SANDBOX_TTL, json.dumps(meta))
        logger.info(
            "sandbox_cache.stored",
            thread_id=thread_id,
            sandbox_id=sandbox_id,
            ttl_seconds=SANDBOX_TTL,
        )
        return True

    except Exception as e:
        logger.info(
            "sandbox_cache.store_error",
            thread_id=thread_id,
            sandbox_id=sandbox_id,
            error=str(e),
        )
        return False


async def refresh_sandbox_ttl(thread_id: int) -> bool:
    """Refresh sandbox TTL after successful use.

    Updates last_used timestamp and resets TTL to full duration.

    Args:
        thread_id: Internal thread ID.

    Returns:
        True if refreshed successfully, False otherwise.
    """
    if not thread_id:
        return False

    redis = await get_redis()
    key = sandbox_key(thread_id)

    try:
        data = await redis.get(key)
        if not data:
            return False

        meta: SandboxMeta = json.loads(data)
        meta["last_used"] = time.time()

        await redis.setex(key, SANDBOX_TTL, json.dumps(meta))
        logger.debug(
            "sandbox_cache.ttl_refreshed",
            thread_id=thread_id,
            sandbox_id=meta.get("sandbox_id"),
        )
        return True

    except Exception as e:
        logger.info(
            "sandbox_cache.refresh_error",
            thread_id=thread_id,
            error=str(e),
        )
        return False


async def invalidate_sandbox(thread_id: int) -> bool:
    """Remove sandbox from cache.

    Call this when:
    - Sandbox execution fails (stale state)
    - Reconnect fails (sandbox expired)
    - User explicitly requests fresh environment

    Args:
        thread_id: Internal thread ID.

    Returns:
        True if invalidated (or didn't exist), False on error.
    """
    if not thread_id:
        return True

    redis = await get_redis()
    key = sandbox_key(thread_id)

    try:
        deleted = await redis.delete(key)
        logger.info(
            "sandbox_cache.invalidated",
            thread_id=thread_id,
            was_cached=bool(deleted),
        )
        return True

    except Exception as e:
        logger.info(
            "sandbox_cache.invalidate_error",
            thread_id=thread_id,
            error=str(e),
        )
        return False
