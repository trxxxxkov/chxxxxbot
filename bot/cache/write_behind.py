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

# Retry configuration
MAX_RETRY_ATTEMPTS = 3  # max retries before discarding
RETRY_BACKOFF_BASE = 2  # exponential backoff base (seconds)


class WriteType(str, Enum):
    """Type of write operation."""

    MESSAGE = "message"
    USER_STATS = "user_stats"
    BALANCE_OP = "balance_op"
    FILE = "file"
    TOOL_CALL = "tool_call"


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
        # Redis unavailable - caller should fall back to direct DB write
        logger.info("write_behind.queue_failed", reason="redis_unavailable")
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


async def requeue_failed_items(failed_items: List[Dict[str, Any]]) -> int:
    """Re-queue failed items for retry with exponential backoff.

    Items that have exceeded MAX_RETRY_ATTEMPTS are discarded.

    Args:
        failed_items: List of write payloads that failed processing.

    Returns:
        Number of items successfully re-queued.
    """
    redis = await get_redis()
    if redis is None:
        return 0

    requeued = 0
    for item in failed_items:
        retry_count = item.get("retry_count", 0) + 1

        if retry_count > MAX_RETRY_ATTEMPTS:
            # Max retries exceeded - discard item
            logger.error(
                "write_behind.item_discarded_max_retries",
                write_type=item.get("type"),
                retry_count=retry_count,
                data_keys=list(item.get("data", {}).keys()),
            )
            continue

        # Add retry metadata
        item["retry_count"] = retry_count
        item["retry_after"] = time.time() + (RETRY_BACKOFF_BASE**retry_count)

        try:
            # Push to end of queue (will be processed after current items)
            await redis.rpush(WRITE_QUEUE_KEY, json.dumps(item))
            requeued += 1

            # Normal retry mechanism - item will be processed later
            logger.info(
                "write_behind.item_requeued",
                write_type=item.get("type"),
                retry_count=retry_count,
                backoff_seconds=RETRY_BACKOFF_BASE**retry_count,
            )

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error(
                "write_behind.requeue_error",
                write_type=item.get("type"),
                error=str(e),
            )

    return requeued


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


async def _batch_insert_messages(
    session,
    messages: List[Dict],
) -> tuple[int, List[Dict]]:
    """Batch insert messages to database using ON CONFLICT DO NOTHING.

    Uses PostgreSQL-specific INSERT ... ON CONFLICT DO NOTHING to gracefully
    handle duplicate messages (same chat_id, message_id). This handles race
    conditions where the same message might be queued multiple times.

    Args:
        session: Database session.
        messages: List of message dicts from queue.

    Returns:
        Tuple of (success_count, failed_items).
    """
    from datetime import datetime  # pylint: disable=import-outside-toplevel
    from datetime import timezone  # pylint: disable=import-outside-toplevel

    from db.models.message import \
        Message  # pylint: disable=import-outside-toplevel
    from db.models.message import \
        MessageRole  # pylint: disable=import-outside-toplevel
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    values_list = []
    failed = []

    for msg_data in messages:
        data = msg_data.get("data", {})
        try:
            # Convert ISO date string to Unix timestamp if needed
            date_value = data.get("date")
            if isinstance(date_value, str):
                date_value = int(datetime.fromisoformat(date_value).timestamp())
            elif date_value is None:
                date_value = int(datetime.now(timezone.utc).timestamp())

            values_list.append({
                "chat_id":
                    data["chat_id"],
                "message_id":
                    data["message_id"],
                "thread_id":
                    data["thread_id"],
                "from_user_id":
                    data.get("from_user_id"),
                "date":
                    date_value,
                "role":
                    MessageRole(data["role"]),
                "text_content":
                    data.get("text_content"),
                "input_tokens":
                    data.get("input_tokens", 0),
                "output_tokens":
                    data.get("output_tokens", 0),
                # Field mapping: queue uses cache_read/write_tokens,
                # Message model uses cache_read/creation_input_tokens
                "cache_read_input_tokens":
                    data.get("cache_read_tokens", 0),
                "cache_creation_input_tokens":
                    data.get("cache_write_tokens", 0),
                "thinking_tokens":
                    data.get("thinking_tokens", 0),
                "thinking_blocks":
                    data.get("thinking_blocks"),
                "model_id":
                    data.get("model_id"),
                "created_at":
                    date_value,
                # Set defaults for boolean/count fields
                "has_photos":
                    False,
                "has_documents":
                    False,
                "has_voice":
                    False,
                "has_video":
                    False,
                "attachment_count":
                    0,
                "attachments": [],
                "edit_count":
                    0,
            })
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error(
                "write_behind.message_prepare_error",
                error=str(e),
                data_keys=list(data.keys()),
            )
            failed.append(msg_data)

    if not values_list:
        return 0, failed

    # Use PostgreSQL INSERT ... ON CONFLICT DO NOTHING
    # This gracefully handles duplicate primary keys (chat_id, message_id)
    stmt = pg_insert(
        Message.__table__).values(values_list).on_conflict_do_nothing(
            index_elements=["chat_id", "message_id"])
    result = await session.execute(stmt)

    # rowcount tells us how many rows were actually inserted
    inserted_count = result.rowcount if result.rowcount >= 0 else len(
        values_list)

    if inserted_count < len(values_list):
        logger.debug(
            "write_behind.messages_duplicates_skipped",
            total=len(values_list),
            inserted=inserted_count,
            skipped=len(values_list) - inserted_count,
        )

    return inserted_count, failed


async def _batch_update_stats(
    session,
    stats: List[Dict],
) -> tuple[int, List[Dict]]:
    """Batch update user stats in database.

    Args:
        session: Database session.
        stats: List of stats update dicts from queue.

    Returns:
        Tuple of (success_count, failed_items).
    """
    from db.repositories.user_repository import \
        UserRepository  # pylint: disable=import-outside-toplevel

    user_repo = UserRepository(session)
    count = 0
    failed = []

    # Group by user_id
    by_user: Dict[int, Dict[str, int]] = {}
    user_items: Dict[int, List[Dict]] = {}  # Track original items per user

    for stat_data in stats:
        data = stat_data.get("data", {})
        user_id = data.get("user_id")
        if user_id is None:
            continue

        if user_id not in by_user:
            by_user[user_id] = {"messages": 0, "tokens": 0}
            user_items[user_id] = []

        by_user[user_id]["messages"] += data.get("messages", 0)
        by_user[user_id]["tokens"] += data.get("tokens", 0)
        user_items[user_id].append(stat_data)

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
            # Add all items for this user to failed list
            failed.extend(user_items.get(user_id, []))

    return count, failed


async def _batch_insert_balance_ops(
    session,
    balance_ops: List[Dict],
) -> tuple[int, List[Dict]]:
    """Batch insert balance operations to database.

    Args:
        session: Database session.
        balance_ops: List of balance operation dicts from queue.

    Returns:
        Tuple of (success_count, failed_items).
    """
    from decimal import Decimal  # pylint: disable=import-outside-toplevel

    from db.models.balance_operation import \
        BalanceOperation  # pylint: disable=import-outside-toplevel
    from db.models.balance_operation import \
        OperationType  # pylint: disable=import-outside-toplevel

    count = 0
    failed = []

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
            failed.append(op_data)

    return count, failed


async def _batch_insert_tool_calls(
    session,
    tool_calls: List[Dict],
) -> tuple[int, List[Dict]]:
    """Batch insert tool calls to database.

    Args:
        session: Database session.
        tool_calls: List of tool call dicts from queue.

    Returns:
        Tuple of (success_count, failed_items).
    """
    from decimal import Decimal  # pylint: disable=import-outside-toplevel

    from db.models.tool_call import \
        ToolCall  # pylint: disable=import-outside-toplevel

    count = 0
    failed = []

    for call_data in tool_calls:
        data = call_data.get("data", {})
        try:
            tool_call = ToolCall(
                user_id=data["user_id"],
                chat_id=data["chat_id"],
                thread_id=data.get("thread_id"),
                message_id=data.get("message_id"),
                tool_name=data["tool_name"],
                model_id=data["model_id"],
                input_tokens=data.get("input_tokens", 0),
                output_tokens=data.get("output_tokens", 0),
                cache_read_tokens=data.get("cache_read_tokens", 0),
                cache_creation_tokens=data.get("cache_creation_tokens", 0),
                cost_usd=Decimal(str(data["cost_usd"])),
                duration_ms=data.get("duration_ms"),
                success=data.get("success", True),
                error_message=data.get("error_message"),
            )
            session.add(tool_call)
            count += 1
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error(
                "write_behind.tool_call_insert_error",
                error=str(e),
                data_keys=list(data.keys()),
            )
            failed.append(call_data)

    return count, failed


async def flush_writes(session) -> int:
    """Flush queued writes to Postgres with retry support.

    Called by background task periodically. Failed items are re-queued
    with exponential backoff for retry.

    Args:
        session: Database session.

    Returns:
        Number of writes successfully flushed.
    """
    flush_start = time.time()
    writes = await flush_writes_batch()

    if not writes:
        # Update queue depth metric (queue is empty)
        queue_depth = await get_queue_depth()
        set_write_queue_depth(queue_depth)
        return 0

    # Filter out items that are not yet ready for retry
    current_time = time.time()
    ready_writes = []
    delayed_writes = []

    for w in writes:
        retry_after = w.get("retry_after", 0)
        if retry_after <= current_time:
            ready_writes.append(w)
        else:
            delayed_writes.append(w)

    # Re-queue delayed items immediately (they'll be skipped again)
    if delayed_writes:
        await requeue_failed_items(delayed_writes)

    if not ready_writes:
        queue_depth = await get_queue_depth()
        set_write_queue_depth(queue_depth)
        return 0

    # Group by type
    messages = [
        w for w in ready_writes if w.get("type") == WriteType.MESSAGE.value
    ]
    stats = [
        w for w in ready_writes if w.get("type") == WriteType.USER_STATS.value
    ]
    balance_ops = [
        w for w in ready_writes if w.get("type") == WriteType.BALANCE_OP.value
    ]
    tool_calls = [
        w for w in ready_writes if w.get("type") == WriteType.TOOL_CALL.value
    ]

    # Process each type, collecting failed items
    msg_count = 0
    stats_count = 0
    balance_count = 0
    tool_count = 0
    all_failed: List[Dict] = []

    if messages:
        msg_count, msg_failed = await _batch_insert_messages(session, messages)
        all_failed.extend(msg_failed)

    if stats:
        stats_count, stats_failed = await _batch_update_stats(session, stats)
        all_failed.extend(stats_failed)

    if balance_ops:
        balance_count, balance_failed = await _batch_insert_balance_ops(
            session, balance_ops)
        all_failed.extend(balance_failed)

    if tool_calls:
        tool_count, tool_failed = await _batch_insert_tool_calls(
            session, tool_calls)
        all_failed.extend(tool_failed)

    # Try to commit
    try:
        await session.commit()
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error(
            "write_behind.commit_failed",
            error=str(e),
            items_count=len(ready_writes),
        )
        # Rollback and re-queue all items for retry
        await session.rollback()
        all_failed = ready_writes

    # Re-queue failed items for retry (normal retry mechanism)
    if all_failed:
        requeued = await requeue_failed_items(all_failed)
        logger.info(
            "write_behind.items_requeued",
            failed_count=len(all_failed),
            requeued_count=requeued,
        )

    # Calculate flush duration and record metrics
    flush_duration = time.time() - flush_start

    # Record metrics per type (only successful)
    if msg_count > 0:
        record_write_flush(flush_duration, "message", msg_count)
    if stats_count > 0:
        record_write_flush(flush_duration, "user_stats", stats_count)
    if balance_count > 0:
        record_write_flush(flush_duration, "balance_op", balance_count)
    if tool_count > 0:
        record_write_flush(flush_duration, "tool_call", tool_count)

    # Update queue depth after flush
    queue_depth = await get_queue_depth()
    set_write_queue_depth(queue_depth)

    total = msg_count + stats_count + balance_count + tool_count

    logger.info(
        "write_behind.flushed",
        total=total,
        messages=msg_count,
        stats=stats_count,
        balance_ops=balance_count,
        tool_calls=tool_count,
        queue_items=len(ready_writes),
        failed_items=len(all_failed),
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

    log.debug("write_behind.task_started", interval=FLUSH_INTERVAL)

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
            log.debug("write_behind.shutdown_flush_start")
            try:
                async with get_session() as session:
                    # Flush multiple times to drain queue
                    total_flushed = 0
                    while True:
                        flushed = await flush_writes(session)
                        if flushed == 0:
                            break
                        total_flushed += flushed

                    log.debug("write_behind.shutdown_flush_complete",
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
