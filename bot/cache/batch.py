"""Batch cache operations using Redis pipeline.

Phase 4.2: Reduces Redis roundtrips by fetching multiple keys at once.
Uses pipeline for parallel execution.

Usage:
    context = await get_user_context_batch(user_id, thread_id)
    if context.user:
        print(f"Balance: {context.user['balance']}")

NO __init__.py - use direct import:
    from cache.batch import get_user_context_batch, UserContext
"""

from dataclasses import dataclass
from decimal import Decimal
import json
import time
from typing import Optional

from cache.client import get_redis
from cache.keys import files_key
from cache.keys import messages_key
from cache.keys import thread_key
from cache.keys import user_key
from utils.metrics import record_cache_operation
from utils.metrics import record_redis_operation_time
from utils.structured_logging import get_logger

logger = get_logger(__name__)


@dataclass
class UserContext:
    """Batch-fetched user context from cache.

    All fields are None if cache miss for that key.
    """

    user: Optional[dict] = None
    thread: Optional[dict] = None
    messages: Optional[list] = None
    files: Optional[list] = None
    cache_hits: int = 0
    cache_misses: int = 0


async def get_user_context_batch(
    user_id: int,
    thread_id: int,
) -> UserContext:
    """Get all user context in single Redis roundtrip.

    Uses Redis pipeline to fetch user, thread, messages, and files
    in one network call instead of four separate calls.

    Args:
        user_id: Telegram user ID.
        thread_id: Internal thread ID (database ID).

    Returns:
        UserContext with all available cached data.
        Fields are None for cache misses.
    """
    start_time = time.time()
    redis = await get_redis()

    if redis is None:
        logger.debug("batch_cache.redis_unavailable")
        return UserContext(cache_misses=4)

    try:
        # Build keys
        keys = [
            user_key(user_id),
            thread_key(thread_id),
            messages_key(thread_id),
            files_key(thread_id),
        ]

        # Execute pipeline
        async with redis.pipeline(transaction=False) as pipe:
            for key in keys:
                pipe.get(key)
            results = await pipe.execute()

        elapsed = time.time() - start_time
        record_redis_operation_time("pipeline_get_4", elapsed)

        # Parse results
        context = UserContext()

        # User data
        if results[0]:
            context.user = json.loads(results[0].decode("utf-8"))
            context.cache_hits += 1
            record_cache_operation("user", hit=True)
        else:
            context.cache_misses += 1
            record_cache_operation("user", hit=False)

        # Thread data
        if results[1]:
            context.thread = json.loads(results[1].decode("utf-8"))
            context.cache_hits += 1
            record_cache_operation("thread", hit=True)
        else:
            context.cache_misses += 1
            record_cache_operation("thread", hit=False)

        # Messages
        if results[2]:
            data = json.loads(results[2].decode("utf-8"))
            context.messages = data.get("messages", [])
            context.cache_hits += 1
            record_cache_operation("messages", hit=True)
        else:
            context.cache_misses += 1
            record_cache_operation("messages", hit=False)

        # Files
        if results[3]:
            data = json.loads(results[3].decode("utf-8"))
            context.files = data.get("files", [])
            context.cache_hits += 1
            record_cache_operation("files", hit=True)
        else:
            context.cache_misses += 1
            record_cache_operation("files", hit=False)

        logger.debug(
            "batch_cache.context_fetched",
            user_id=user_id,
            thread_id=thread_id,
            cache_hits=context.cache_hits,
            cache_misses=context.cache_misses,
            elapsed_ms=round(elapsed * 1000, 2),
        )

        return context

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning(
            "batch_cache.pipeline_failed",
            user_id=user_id,
            thread_id=thread_id,
            error=str(e),
        )
        return UserContext(cache_misses=4)


async def set_user_context_batch(
    user_id: int,
    thread_id: int,
    user_data: Optional[dict] = None,
    thread_data: Optional[dict] = None,
    messages: Optional[list] = None,
    files: Optional[list] = None,
    user_ttl: int = 60,
    thread_ttl: int = 3600,
    messages_ttl: int = 3600,
    files_ttl: int = 3600,
) -> int:
    """Set multiple cache entries in single Redis roundtrip.

    Args:
        user_id: Telegram user ID.
        thread_id: Internal thread ID.
        user_data: User data to cache (optional).
        thread_data: Thread data to cache (optional).
        messages: Messages to cache (optional).
        files: Files to cache (optional).
        user_ttl: TTL for user cache.
        thread_ttl: TTL for thread cache.
        messages_ttl: TTL for messages cache.
        files_ttl: TTL for files cache.

    Returns:
        Number of keys set.
    """
    start_time = time.time()
    redis = await get_redis()

    if redis is None:
        logger.debug("batch_cache.redis_unavailable_for_set")
        return 0

    try:
        keys_set = 0

        async with redis.pipeline(transaction=False) as pipe:
            if user_data is not None:
                key = user_key(user_id)
                pipe.setex(key, user_ttl, json.dumps(user_data))
                keys_set += 1

            if thread_data is not None:
                key = thread_key(thread_id)
                pipe.setex(key, thread_ttl, json.dumps(thread_data))
                keys_set += 1

            if messages is not None:
                key = messages_key(thread_id)
                data = {"messages": messages, "cached_at": time.time()}
                pipe.setex(key, messages_ttl, json.dumps(data))
                keys_set += 1

            if files is not None:
                key = files_key(thread_id)
                data = {"files": files, "cached_at": time.time()}
                pipe.setex(key, files_ttl, json.dumps(data))
                keys_set += 1

            if keys_set > 0:
                await pipe.execute()

        elapsed = time.time() - start_time
        record_redis_operation_time(f"pipeline_set_{keys_set}", elapsed)

        logger.debug(
            "batch_cache.context_set",
            user_id=user_id,
            thread_id=thread_id,
            keys_set=keys_set,
            elapsed_ms=round(elapsed * 1000, 2),
        )

        return keys_set

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning(
            "batch_cache.pipeline_set_failed",
            user_id=user_id,
            thread_id=thread_id,
            error=str(e),
        )
        return 0
