"""Thread and messages cache for fast LLM context retrieval.

This module provides caching for thread and message data that is frequently
accessed during Claude requests:
- Active thread lookup (by chat_id, user_id, thread_id)
- Message history (for LLM context)

Uses cache-aside pattern with TTL-based expiration.

TTLs:
- Thread: 600 seconds (10 minutes)
- Messages: 300 seconds (5 minutes)

NO __init__.py - use direct import:
    from cache.thread_cache import (
        get_cached_thread, cache_thread, invalidate_thread,
        get_cached_messages, cache_messages, invalidate_messages
    )
"""

import json
import time
from typing import Any, Optional

from cache.client import get_redis
from cache.keys import messages_key
from cache.keys import MESSAGES_TTL
from cache.keys import thread_key
from cache.keys import THREAD_TTL
from utils.metrics import record_cache_operation
from utils.metrics import record_redis_operation_time
from utils.structured_logging import get_logger

logger = get_logger(__name__)


# === Thread Cache ===
async def get_cached_thread(
    chat_id: int,
    user_id: int,
    thread_id: Optional[int] = None,
) -> Optional[dict]:
    """Get cached thread data.

    Args:
        chat_id: Telegram chat ID.
        user_id: Telegram user ID.
        thread_id: Telegram thread/topic ID (None for main chat).

    Returns:
        Thread data dict if found, None if not cached.
    """
    start_time = time.time()
    redis = await get_redis()

    if redis is None:
        return None

    try:
        key = thread_key(chat_id, user_id, thread_id)
        data = await redis.get(key)

        elapsed = time.time() - start_time
        record_redis_operation_time("get", elapsed)

        if data is None:
            record_cache_operation("thread", hit=False)
            logger.debug(
                "thread_cache.miss",
                chat_id=chat_id,
                user_id=user_id,
                thread_id=thread_id,
            )
            return None

        record_cache_operation("thread", hit=True)
        cached = json.loads(data.decode("utf-8"))

        logger.debug(
            "thread_cache.hit",
            chat_id=chat_id,
            user_id=user_id,
            thread_id=thread_id,
            internal_id=cached.get("id"),
        )

        return cached

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning(
            "thread_cache.get_error",
            chat_id=chat_id,
            user_id=user_id,
            error=str(e),
        )
        return None


async def cache_thread(
    chat_id: int,
    user_id: int,
    thread_id: Optional[int],
    internal_id: int,
    title: Optional[str] = None,
    files_context: Optional[str] = None,
) -> bool:
    """Cache thread data.

    Args:
        chat_id: Telegram chat ID.
        user_id: Telegram user ID.
        thread_id: Telegram thread/topic ID (None for main chat).
        internal_id: Internal thread ID (from database).
        title: Thread title.
        files_context: Files context string.

    Returns:
        True if cached successfully, False otherwise.
    """
    start_time = time.time()
    redis = await get_redis()

    if redis is None:
        return False

    try:
        key = thread_key(chat_id, user_id, thread_id)
        data = {
            "id": internal_id,
            "chat_id": chat_id,
            "user_id": user_id,
            "thread_id": thread_id,
            "title": title,
            "files_context": files_context,
            "cached_at": time.time(),
        }

        await redis.setex(key, THREAD_TTL, json.dumps(data))

        elapsed = time.time() - start_time
        record_redis_operation_time("set", elapsed)

        logger.debug(
            "thread_cache.set",
            chat_id=chat_id,
            user_id=user_id,
            thread_id=thread_id,
            internal_id=internal_id,
            ttl=THREAD_TTL,
        )

        return True

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning(
            "thread_cache.set_error",
            chat_id=chat_id,
            user_id=user_id,
            error=str(e),
        )
        return False


async def invalidate_thread(
    chat_id: int,
    user_id: int,
    thread_id: Optional[int] = None,
) -> bool:
    """Invalidate cached thread data.

    Args:
        chat_id: Telegram chat ID.
        user_id: Telegram user ID.
        thread_id: Telegram thread/topic ID (None for main chat).

    Returns:
        True if invalidated, False otherwise.
    """
    start_time = time.time()
    redis = await get_redis()

    if redis is None:
        return False

    try:
        key = thread_key(chat_id, user_id, thread_id)
        deleted = await redis.delete(key)

        elapsed = time.time() - start_time
        record_redis_operation_time("delete", elapsed)

        logger.debug(
            "thread_cache.invalidated",
            chat_id=chat_id,
            user_id=user_id,
            thread_id=thread_id,
            deleted=deleted,
        )

        return deleted > 0

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning(
            "thread_cache.invalidate_error",
            chat_id=chat_id,
            user_id=user_id,
            error=str(e),
        )
        return False


# === Messages Cache ===


async def get_cached_messages(internal_thread_id: int) -> Optional[list[dict]]:
    """Get cached message history for a thread.

    Args:
        internal_thread_id: Internal thread ID (from database).

    Returns:
        List of message dicts if found, None if not cached.
    """
    start_time = time.time()
    redis = await get_redis()

    if redis is None:
        return None

    try:
        key = messages_key(internal_thread_id)
        data = await redis.get(key)

        elapsed = time.time() - start_time
        record_redis_operation_time("get", elapsed)

        if data is None:
            record_cache_operation("messages", hit=False)
            logger.debug(
                "messages_cache.miss",
                thread_id=internal_thread_id,
            )
            return None

        record_cache_operation("messages", hit=True)
        cached = json.loads(data.decode("utf-8"))
        messages = cached.get("messages", [])

        logger.debug(
            "messages_cache.hit",
            thread_id=internal_thread_id,
            message_count=len(messages),
        )

        return messages

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning(
            "messages_cache.get_error",
            thread_id=internal_thread_id,
            error=str(e),
        )
        return None


async def cache_messages(
    internal_thread_id: int,
    messages: list[dict[str, Any]],
) -> bool:
    """Cache message history for a thread.

    Args:
        internal_thread_id: Internal thread ID (from database).
        messages: List of message dicts with role, text_content, etc.

    Returns:
        True if cached successfully, False otherwise.
    """
    start_time = time.time()
    redis = await get_redis()

    if redis is None:
        return False

    try:
        key = messages_key(internal_thread_id)
        data = {
            "thread_id": internal_thread_id,
            "messages": messages,
            "cached_at": time.time(),
        }

        await redis.setex(key, MESSAGES_TTL, json.dumps(data))

        elapsed = time.time() - start_time
        record_redis_operation_time("set", elapsed)

        logger.debug(
            "messages_cache.set",
            thread_id=internal_thread_id,
            message_count=len(messages),
            ttl=MESSAGES_TTL,
        )

        return True

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning(
            "messages_cache.set_error",
            thread_id=internal_thread_id,
            error=str(e),
        )
        return False


async def invalidate_messages(internal_thread_id: int) -> bool:
    """Invalidate cached message history for a thread.

    Call this after any message is added to the thread.

    Args:
        internal_thread_id: Internal thread ID (from database).

    Returns:
        True if invalidated, False otherwise.
    """
    start_time = time.time()
    redis = await get_redis()

    if redis is None:
        return False

    try:
        key = messages_key(internal_thread_id)
        deleted = await redis.delete(key)

        elapsed = time.time() - start_time
        record_redis_operation_time("delete", elapsed)

        logger.debug(
            "messages_cache.invalidated",
            thread_id=internal_thread_id,
            deleted=deleted,
        )

        return deleted > 0

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning(
            "messages_cache.invalidate_error",
            thread_id=internal_thread_id,
            error=str(e),
        )
        return False
