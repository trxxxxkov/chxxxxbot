"""Thread and messages cache for fast LLM context retrieval.

This module provides caching for thread and message data that is frequently
accessed during Claude requests:
- Active thread lookup (by chat_id, user_id, thread_id)
- Message history (for LLM context)

Uses cache-aside pattern with TTL-based expiration.

TTLs (all 1 hour for optimal cache hit rate):
- Thread: 3600 seconds (rarely changes)
- Messages: 3600 seconds (appended in-place, invalidated on full rebuild)

Message updates use atomic Lua script to prevent race conditions
when multiple processes append messages concurrently.

NO __init__.py - use direct import:
    from cache.thread_cache import (
        get_cached_thread, cache_thread, invalidate_thread,
        get_cached_messages, cache_messages, invalidate_messages,
        append_message_atomic
    )
"""

import json
import time
from typing import Any, Optional

from cache.client import get_redis
from cache.keys import files_key
from cache.keys import FILES_TTL
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
        logger.info(
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
        logger.info(
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
        logger.info(
            "thread_cache.invalidate_error",
            chat_id=chat_id,
            user_id=user_id,
            error=str(e),
        )
        return False


# === Messages Cache ===

# Lua script for atomic message append
# Prevents race conditions when multiple processes append messages concurrently
# Uses cjson for JSON parsing (built into Redis)
APPEND_MESSAGE_LUA = """
local key = KEYS[1]
local new_message_json = ARGV[1]
local ttl = tonumber(ARGV[2])
local timestamp = ARGV[3]

-- Get existing data
local data = redis.call('GET', key)
if not data then
    return 0  -- Cache miss, caller should rebuild cache
end

-- Parse existing cache
local cached = cjson.decode(data)
local messages = cached.messages or {}

-- Append new message
local new_message = cjson.decode(new_message_json)
table.insert(messages, new_message)

-- Update cache
cached.messages = messages
cached.cached_at = tonumber(timestamp)

-- Save with TTL refresh
redis.call('SETEX', key, ttl, cjson.encode(cached))
return 1  -- Success
"""


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
        logger.info(
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
        logger.info(
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
        logger.info(
            "messages_cache.invalidate_error",
            thread_id=internal_thread_id,
            error=str(e),
        )
        return False


async def append_message_atomic(
    internal_thread_id: int,
    new_message: dict[str, Any],
) -> bool:
    """Atomically append a message to cached history.

    Uses Lua script to prevent race conditions when multiple processes
    append messages concurrently. This is the preferred method for
    adding messages to cache.

    Args:
        internal_thread_id: Internal thread ID (from database).
        new_message: Message dict to append.

    Returns:
        True if appended successfully, False if cache miss or error.
    """
    start_time = time.time()
    redis = await get_redis()

    if redis is None:
        return False

    try:
        key = messages_key(internal_thread_id)

        # Execute Lua script atomically
        result = await redis.eval(
            APPEND_MESSAGE_LUA,
            1,  # number of keys
            key,  # KEYS[1]
            json.dumps(new_message),  # ARGV[1] - new message as JSON
            str(MESSAGES_TTL),  # ARGV[2] - TTL
            str(time.time()),  # ARGV[3] - timestamp
        )

        elapsed = time.time() - start_time
        record_redis_operation_time("atomic_append", elapsed)

        if result == 0:
            # Cache miss - Lua script returned 0
            logger.debug(
                "messages_cache.atomic_append_miss",
                thread_id=internal_thread_id,
            )
            return False

        logger.debug(
            "messages_cache.atomic_append_success",
            thread_id=internal_thread_id,
            elapsed_ms=round(elapsed * 1000, 2),
        )

        return True

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.info(
            "messages_cache.atomic_append_error",
            thread_id=internal_thread_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return False


# Backward compatibility alias
async def update_cached_messages(
    internal_thread_id: int,
    new_message: dict[str, Any],
) -> bool:
    """Add a message to cached history (backward compatibility).

    This function is an alias for append_message_atomic().
    New code should use append_message_atomic() directly.

    Args:
        internal_thread_id: Internal thread ID (from database).
        new_message: Message dict to append.

    Returns:
        True if updated successfully, False if cache miss or error.
    """
    return await append_message_atomic(internal_thread_id, new_message)


# === Files Cache ===


async def get_cached_files(internal_thread_id: int) -> Optional[list[dict]]:
    """Get cached available files list for a thread.

    Args:
        internal_thread_id: Internal thread ID (from database).

    Returns:
        List of file dicts if found, None if not cached.
    """
    start_time = time.time()
    redis = await get_redis()

    if redis is None:
        return None

    try:
        key = files_key(internal_thread_id)
        data = await redis.get(key)

        elapsed = time.time() - start_time
        record_redis_operation_time("get", elapsed)

        if data is None:
            record_cache_operation("files", hit=False)
            logger.debug(
                "files_cache.miss",
                thread_id=internal_thread_id,
            )
            return None

        record_cache_operation("files", hit=True)
        cached = json.loads(data.decode("utf-8"))
        files = cached.get("files", [])

        logger.debug(
            "files_cache.hit",
            thread_id=internal_thread_id,
            file_count=len(files),
        )

        return files

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.info(
            "files_cache.get_error",
            thread_id=internal_thread_id,
            error=str(e),
        )
        return None


async def cache_files(
    internal_thread_id: int,
    files: list[dict[str, Any]],
) -> bool:
    """Cache available files list for a thread.

    Args:
        internal_thread_id: Internal thread ID (from database).
        files: List of file dicts with filename, file_type, claude_file_id, etc.

    Returns:
        True if cached successfully, False otherwise.
    """
    start_time = time.time()
    redis = await get_redis()

    if redis is None:
        return False

    try:
        key = files_key(internal_thread_id)
        data = {
            "thread_id": internal_thread_id,
            "files": files,
            "cached_at": time.time(),
        }

        await redis.setex(key, FILES_TTL, json.dumps(data))

        elapsed = time.time() - start_time
        record_redis_operation_time("set", elapsed)

        logger.debug(
            "files_cache.set",
            thread_id=internal_thread_id,
            file_count=len(files),
            ttl=FILES_TTL,
        )

        return True

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.info(
            "files_cache.set_error",
            thread_id=internal_thread_id,
            error=str(e),
        )
        return False


async def invalidate_files(internal_thread_id: int) -> bool:
    """Invalidate cached files list for a thread.

    Call this after any file is added or deleted from the thread.

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
        key = files_key(internal_thread_id)
        deleted = await redis.delete(key)

        elapsed = time.time() - start_time
        record_redis_operation_time("delete", elapsed)

        logger.debug(
            "files_cache.invalidated",
            thread_id=internal_thread_id,
            deleted=deleted,
        )

        return deleted > 0

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.info(
            "files_cache.invalidate_error",
            thread_id=internal_thread_id,
            error=str(e),
        )
        return False
