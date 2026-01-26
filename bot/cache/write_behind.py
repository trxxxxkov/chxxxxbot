"""Write-behind queue for async Postgres writes.

This module provides a write-behind pattern for database operations:
- Writes are queued in Redis for async processing
- Background task periodically flushes queue to Postgres
- Graceful shutdown ensures all writes are flushed

Write Types:
- MESSAGE: User and assistant messages
- USER_STATS: Token counts, message counts
- BALANCE_OP: Balance operations (use carefully!)

NO __init__.py - use direct import:
    from cache.write_behind import queue_write, WriteType
"""

import asyncio
from enum import Enum
import json
import time
from typing import Any, Dict, List, Optional

from cache.client import get_redis
from utils.metrics import record_redis_operation_time
from utils.metrics import record_write_flush
from utils.metrics import set_write_queue_depth
from utils.structured_logging import get_logger

logger = get_logger(__name__)

# Redis key for write queue
WRITE_QUEUE_KEY = "write:queue"

# Flush configuration
FLUSH_INTERVAL = 5  # seconds between flushes
BATCH_SIZE = 100  # max writes per flush


class WriteType(str, Enum):
    """Type of write operation."""

    MESSAGE = "message"
    USER_STATS = "user_stats"
    BALANCE_OP = "balance_op"
    FILE = "file"


async def queue_write(write_type: WriteType, data: Dict[str, Any]) -> bool:
    """Queue a write operation for background processing.

    Args:
        write_type: Type of write operation.
        data: Data to write (must be JSON-serializable).

    Returns:
        True if queued successfully, False otherwise.

    Example:
        await queue_write(WriteType.MESSAGE, {
            "chat_id": 123,
            "message_id": 456,
            "thread_id": 1,
            "role": "user",
            "text_content": "Hello",
        })
    """
    start_time = time.time()
    redis = await get_redis()

    if redis is None:
        logger.warning("write_behind.queue_failed", reason="redis_unavailable")
        return False

    try:
        payload = json.dumps({
            "type": write_type.value,
            "data": data,
            "queued_at": time.time(),
        })

        await redis.rpush(WRITE_QUEUE_KEY, payload)

        elapsed = time.time() - start_time
        record_redis_operation_time("rpush", elapsed)

        logger.debug(
            "write_behind.queued",
            write_type=write_type.value,
            data_keys=list(data.keys()),
        )

        return True

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error(
            "write_behind.queue_error",
            write_type=write_type.value,
            error=str(e),
        )
        return False


async def get_queue_depth() -> int:
    """Get current write queue depth.

    Returns:
        Number of pending writes in queue.
    """
    redis = await get_redis()
    if redis is None:
        return 0

    try:
        return await redis.llen(WRITE_QUEUE_KEY)
    except Exception:  # pylint: disable=broad-exception-caught
        return 0


async def flush_writes_batch() -> List[Dict[str, Any]]:
    """Get batch of writes from queue for processing.

    Returns:
        List of write payloads (up to BATCH_SIZE).
    """
    redis = await get_redis()
    if redis is None:
        return []

    writes = []
    try:
        for _ in range(BATCH_SIZE):
            data = await redis.lpop(WRITE_QUEUE_KEY)
            if data is None:
                break
            writes.append(json.loads(data))

        return writes

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("write_behind.get_batch_error", error=str(e))
        return writes


async def _batch_insert_messages(session, messages: List[Dict]) -> int:
    """Batch insert messages to database.

    Args:
        session: Database session.
        messages: List of message dicts from queue.

    Returns:
        Number of messages inserted.
    """
    from datetime import datetime  # pylint: disable=import-outside-toplevel
    from datetime import timezone  # pylint: disable=import-outside-toplevel

    from db.models.message import \
        Message  # pylint: disable=import-outside-toplevel
    from db.models.message import \
        MessageRole  # pylint: disable=import-outside-toplevel

    count = 0
    for msg_data in messages:
        data = msg_data.get("data", {})
        try:
            # Convert ISO date string to Unix timestamp if needed
            date_value = data.get("date")
            if isinstance(date_value, str):
                date_value = int(datetime.fromisoformat(date_value).timestamp())
            elif date_value is None:
                date_value = int(datetime.now(timezone.utc).timestamp())

            message = Message(
                chat_id=data["chat_id"],
                message_id=data["message_id"],
                thread_id=data["thread_id"],
                from_user_id=data.get("from_user_id"),
                date=date_value,
                role=MessageRole(data["role"]),
                text_content=data.get("text_content"),
                input_tokens=data.get("input_tokens", 0),
                output_tokens=data.get("output_tokens", 0),
                # Field mapping: queue uses cache_read/write_tokens,
                # Message model uses cache_read/creation_input_tokens
                cache_read_input_tokens=data.get("cache_read_tokens", 0),
                cache_creation_input_tokens=data.get("cache_write_tokens", 0),
                thinking_tokens=data.get("thinking_tokens", 0),
                thinking_blocks=data.get("thinking_blocks"),
            )
            session.add(message)
            count += 1
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error(
                "write_behind.message_insert_error",
                error=str(e),
                data_keys=list(data.keys()),
            )

    return count


async def _batch_update_stats(session, stats: List[Dict]) -> int:
    """Batch update user stats in database.

    Args:
        session: Database session.
        stats: List of stats update dicts from queue.

    Returns:
        Number of stats updated.
    """
    from db.repositories.user_repository import \
        UserRepository  # pylint: disable=import-outside-toplevel

    user_repo = UserRepository(session)
    count = 0

    # Group by user_id
    by_user: Dict[int, Dict[str, int]] = {}
    for stat_data in stats:
        data = stat_data.get("data", {})
        user_id = data.get("user_id")
        if user_id is None:
            continue

        if user_id not in by_user:
            by_user[user_id] = {"messages": 0, "tokens": 0}

        by_user[user_id]["messages"] += data.get("messages", 0)
        by_user[user_id]["tokens"] += data.get("tokens", 0)

    # Update each user
    for user_id, totals in by_user.items():
        try:
            await user_repo.increment_stats(user_id,
                                            messages=totals["messages"],
                                            tokens=totals["tokens"])
            count += 1
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error(
                "write_behind.stats_update_error",
                user_id=user_id,
                error=str(e),
            )

    return count


async def _batch_insert_balance_ops(session, balance_ops: List[Dict]) -> int:
    """Batch insert balance operations to database.

    Args:
        session: Database session.
        balance_ops: List of balance operation dicts from queue.

    Returns:
        Number of operations inserted.
    """
    from decimal import Decimal  # pylint: disable=import-outside-toplevel

    from db.models.balance_operation import \
        BalanceOperation  # pylint: disable=import-outside-toplevel
    from db.models.balance_operation import \
        OperationType  # pylint: disable=import-outside-toplevel

    count = 0
    for op_data in balance_ops:
        data = op_data.get("data", {})
        try:
            operation = BalanceOperation(
                user_id=data["user_id"],
                operation_type=OperationType(data["operation_type"]),
                amount=Decimal(str(data["amount"])),
                balance_before=Decimal(str(data["balance_before"])),
                balance_after=Decimal(str(data["balance_after"])),
                related_message_id=data.get("related_message_id"),
                admin_user_id=data.get("admin_user_id"),
                description=data.get("description"),
            )
            session.add(operation)
            count += 1
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error(
                "write_behind.balance_op_insert_error",
                error=str(e),
                data_keys=list(data.keys()),
            )

    return count


async def flush_writes(session) -> int:
    """Flush queued writes to Postgres.

    Called by background task periodically.

    Args:
        session: Database session.

    Returns:
        Number of writes flushed.
    """
    flush_start = time.time()
    writes = await flush_writes_batch()

    if not writes:
        # Update queue depth metric (queue is empty)
        queue_depth = await get_queue_depth()
        set_write_queue_depth(queue_depth)
        return 0

    # Group by type
    messages = [w for w in writes if w.get("type") == WriteType.MESSAGE.value]
    stats = [w for w in writes if w.get("type") == WriteType.USER_STATS.value]
    balance_ops = [
        w for w in writes if w.get("type") == WriteType.BALANCE_OP.value
    ]

    # Process each type
    msg_count = 0
    stats_count = 0
    balance_count = 0

    if messages:
        msg_count = await _batch_insert_messages(session, messages)

    if stats:
        stats_count = await _batch_update_stats(session, stats)

    if balance_ops:
        balance_count = await _batch_insert_balance_ops(session, balance_ops)

    await session.commit()

    # Calculate flush duration and record metrics
    flush_duration = time.time() - flush_start

    # Record metrics per type
    if msg_count > 0:
        record_write_flush(flush_duration, "message", msg_count)
    if stats_count > 0:
        record_write_flush(flush_duration, "user_stats", stats_count)
    if balance_count > 0:
        record_write_flush(flush_duration, "balance_op", balance_count)

    # Update queue depth after flush
    queue_depth = await get_queue_depth()
    set_write_queue_depth(queue_depth)

    total = msg_count + stats_count + balance_count

    logger.info(
        "write_behind.flushed",
        total=total,
        messages=msg_count,
        stats=stats_count,
        balance_ops=balance_count,
        queue_items=len(writes),
        flush_duration_ms=round(flush_duration * 1000, 2),
        remaining_queue_depth=queue_depth,
    )

    return total


async def write_behind_task(log) -> None:
    """Background task to flush writes periodically.

    Args:
        log: Logger instance.

    Note:
        This task runs until cancelled. On cancellation, it performs
        a final flush to ensure all pending writes are persisted.
    """
    from db.engine import \
        get_session  # pylint: disable=import-outside-toplevel

    log.info("write_behind.task_started", interval=FLUSH_INTERVAL)

    while True:
        try:
            await asyncio.sleep(FLUSH_INTERVAL)

            async with get_session() as session:
                flushed = await flush_writes(session)

                if flushed > 0:
                    log.debug(
                        "write_behind.task_flush_complete",
                        flushed=flushed,
                    )

        except asyncio.CancelledError:
            # Final flush on shutdown
            log.info("write_behind.shutdown_flush_start")
            try:
                async with get_session() as session:
                    # Flush multiple times to drain queue
                    total_flushed = 0
                    while True:
                        flushed = await flush_writes(session)
                        if flushed == 0:
                            break
                        total_flushed += flushed

                    log.info("write_behind.shutdown_flush_complete",
                             total=total_flushed)
            except Exception as e:  # pylint: disable=broad-exception-caught
                log.error("write_behind.shutdown_flush_error", error=str(e))
            break

        except Exception as e:  # pylint: disable=broad-exception-caught
            log.error(
                "write_behind.task_error",
                error=str(e),
                exc_info=True,
            )
