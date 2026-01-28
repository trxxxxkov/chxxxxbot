"""Binary file cache for fast file retrieval.

This module provides caching for file content downloaded from Telegram.
Files are cached by their telegram_file_id for fast retrieval during
tool execution (transcribe_audio, execute_python file inputs).

Constraints:
- MAX_FILE_SIZE: 20MB (Redis not designed for large blobs)
- TTL: 3600 seconds (1 hour)

NO __init__.py - use direct import:
    from cache.file_cache import (
        get_cached_file, cache_file, invalidate_file
    )
"""

import time
from typing import Optional

from cache.client import get_redis
from cache.keys import file_bytes_key
from cache.keys import FILE_BYTES_MAX_SIZE
from cache.keys import FILE_BYTES_TTL
from utils.metrics import record_cache_operation
from utils.metrics import record_redis_operation_time
from utils.structured_logging import get_logger

logger = get_logger(__name__)


async def get_cached_file(telegram_file_id: str) -> Optional[bytes]:
    """Get cached file content.

    Args:
        telegram_file_id: Telegram file ID.

    Returns:
        File content as bytes if cached, None otherwise.
    """
    start_time = time.time()
    redis = await get_redis()

    if redis is None:
        return None

    try:
        key = file_bytes_key(telegram_file_id)
        data = await redis.get(key)

        elapsed = time.time() - start_time
        record_redis_operation_time("get", elapsed)

        if data is None:
            record_cache_operation("file", hit=False)
            logger.debug(
                "file_cache.miss",
                file_id=telegram_file_id[:20] + "...",
            )
            return None

        record_cache_operation("file", hit=True)
        logger.debug(
            "file_cache.hit",
            file_id=telegram_file_id[:20] + "...",
            size_bytes=len(data),
            elapsed_ms=elapsed * 1000,
        )

        return data

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.info(
            "file_cache.get_error",
            file_id=telegram_file_id[:20] + "...",
            error=str(e),
        )
        return None


async def cache_file(
    telegram_file_id: str,
    content: bytes,
    filename: Optional[str] = None,
) -> bool:
    """Cache file content.

    Args:
        telegram_file_id: Telegram file ID.
        content: File content as bytes.
        filename: Optional filename for logging.

    Returns:
        True if cached successfully, False otherwise.
    """
    # Check size limit
    if len(content) > FILE_BYTES_MAX_SIZE:
        logger.debug(
            "file_cache.skip_too_large",
            file_id=telegram_file_id[:20] + "...",
            filename=filename,
            size_bytes=len(content),
            max_size=FILE_BYTES_MAX_SIZE,
        )
        return False

    start_time = time.time()
    redis = await get_redis()

    if redis is None:
        return False

    try:
        key = file_bytes_key(telegram_file_id)
        await redis.setex(key, FILE_BYTES_TTL, content)

        elapsed = time.time() - start_time
        record_redis_operation_time("set", elapsed)

        logger.debug(
            "file_cache.set",
            file_id=telegram_file_id[:20] + "...",
            filename=filename,
            size_bytes=len(content),
            ttl=FILE_BYTES_TTL,
            elapsed_ms=elapsed * 1000,
        )

        return True

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.info(
            "file_cache.set_error",
            file_id=telegram_file_id[:20] + "...",
            filename=filename,
            error=str(e),
        )
        return False


async def invalidate_file(telegram_file_id: str) -> bool:
    """Invalidate cached file.

    Args:
        telegram_file_id: Telegram file ID.

    Returns:
        True if invalidated, False otherwise.
    """
    start_time = time.time()
    redis = await get_redis()

    if redis is None:
        return False

    try:
        key = file_bytes_key(telegram_file_id)
        deleted = await redis.delete(key)

        elapsed = time.time() - start_time
        record_redis_operation_time("delete", elapsed)

        logger.debug(
            "file_cache.invalidated",
            file_id=telegram_file_id[:20] + "...",
            deleted=deleted,
        )

        return deleted > 0

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.info(
            "file_cache.invalidate_error",
            file_id=telegram_file_id[:20] + "...",
            error=str(e),
        )
        return False
