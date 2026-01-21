"""Redis key generation for caching.

This module provides functions to generate consistent Redis keys for all
cached data types. Keys are namespaced and structured for easy debugging
and monitoring.

Key schema:
    cache:user:{user_id}           -> User data (balance, model_id)
    cache:thread:{chat_id}:{user_id}:{thread_id} -> Thread
    cache:messages:{thread_id}     -> Message history
    cache:files:{thread_id}        -> Available files list
    file:bytes:{telegram_file_id}  -> Binary file content

NO __init__.py - use direct import:
    from cache.keys import user_key, thread_key, messages_key
"""

from typing import Optional


def user_key(user_id: int) -> str:
    """Generate key for user cache.

    Args:
        user_id: Telegram user ID.

    Returns:
        Redis key string (e.g., "cache:user:123456").
    """
    return f"cache:user:{user_id}"


def thread_key(
    chat_id: int,
    user_id: int,
    thread_id: Optional[int] = None,
) -> str:
    """Generate key for thread cache.

    Args:
        chat_id: Telegram chat ID.
        user_id: Telegram user ID.
        thread_id: Telegram thread/topic ID (0 for main chat).

    Returns:
        Redis key string (e.g., "cache:thread:123:456:0").
    """
    tid = thread_id if thread_id else 0
    return f"cache:thread:{chat_id}:{user_id}:{tid}"


def messages_key(thread_id: int) -> str:
    """Generate key for messages cache.

    Args:
        thread_id: Internal thread ID (from threads table).

    Returns:
        Redis key string (e.g., "cache:messages:789").
    """
    return f"cache:messages:{thread_id}"


def files_key(thread_id: int) -> str:
    """Generate key for files list cache.

    Args:
        thread_id: Internal thread ID (from threads table).

    Returns:
        Redis key string (e.g., "cache:files:789").
    """
    return f"cache:files:{thread_id}"


def file_bytes_key(telegram_file_id: str) -> str:
    """Generate key for binary file content cache.

    Args:
        telegram_file_id: Telegram file ID.

    Returns:
        Redis key string (e.g., "file:bytes:AgACAgIAAxk...").
    """
    return f"file:bytes:{telegram_file_id}"


# TTL constants (in seconds)
# All TTLs set to 1 hour for optimal cache hit rate
# Cache is properly invalidated/updated on data changes:
# - User: balance updated via update_cached_balance() after charge
# - Messages: invalidated via invalidate_messages() on new message
# - Thread: rarely changes, 1 hour is safe
# - Files: invalidated when new files uploaded
USER_TTL = 3600  # 1 hour (balance updated, not invalidated)
THREAD_TTL = 3600  # 1 hour (metadata rarely changes)
MESSAGES_TTL = 3600  # 1 hour (invalidated on new message)
FILES_TTL = 3600  # 1 hour (invalidated on new file)
FILE_BYTES_TTL = 3600  # 1 hour (file content immutable)
FILE_BYTES_MAX_SIZE = 20 * 1024 * 1024  # 20 MB

# Execution output cache (Phase 3.2+)
EXEC_FILE_TTL = 3600  # 1 hour (consumed once, then deleted)
EXEC_FILE_MAX_SIZE = 100 * 1024 * 1024  # 100 MB


def exec_file_key(temp_id: str) -> str:
    """Generate key for execution output file content.

    Args:
        temp_id: Temporary file ID (e.g., "exec_abc123_plot.png").

    Returns:
        Redis key string (e.g., "exec:file:exec_abc123_plot.png").
    """
    return f"exec:file:{temp_id}"


def exec_meta_key(temp_id: str) -> str:
    """Generate key for execution output file metadata.

    Args:
        temp_id: Temporary file ID (e.g., "exec_abc123_plot.png").

    Returns:
        Redis key string (e.g., "exec:meta:exec_abc123_plot.png").
    """
    return f"exec:meta:{temp_id}"
