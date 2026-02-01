"""Data retention cleanup service.

Automatically removes old data according to retention policy:
- messages: 90 days
- tool_calls: 90 days
- user_files: 90 days (metadata only, files have 24h TTL)
- threads: 90 days of inactivity (only if empty)

Runs once per day at 3:00 AM UTC.
"""

import asyncio
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from db.engine import get_session
from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import text
from utils.structured_logging import get_logger

# Retention periods in days
RETENTION_MESSAGES = 90
RETENTION_TOOL_CALLS = 90
RETENTION_USER_FILES = 90
RETENTION_THREADS = 90

# Batch size for deletions (to avoid long locks)
BATCH_SIZE = 500


async def cleanup_messages(session, cutoff_timestamp: int, logger) -> int:
    """Delete messages older than cutoff.

    Args:
        session: Database session.
        cutoff_timestamp: Unix timestamp cutoff.
        logger: Logger instance.

    Returns:
        Number of deleted records.
    """
    total_deleted = 0

    while True:
        # Delete in batches using subquery
        result = await session.execute(
            text("""
                DELETE FROM messages
                WHERE (chat_id, message_id) IN (
                    SELECT chat_id, message_id FROM messages
                    WHERE date < :cutoff
                    LIMIT :batch_size
                )
            """), {
                "cutoff": cutoff_timestamp,
                "batch_size": BATCH_SIZE
            })
        await session.commit()

        deleted = result.rowcount
        total_deleted += deleted

        if deleted < BATCH_SIZE:
            break

        # Small delay between batches
        await asyncio.sleep(0.1)

    if total_deleted > 0:
        logger.info(
            "cleanup.messages",
            deleted=total_deleted,
            cutoff_days=RETENTION_MESSAGES,
        )

    return total_deleted


async def cleanup_tool_calls(session, cutoff_date: datetime, logger) -> int:
    """Delete tool_calls older than cutoff.

    Args:
        session: Database session.
        cutoff_date: Datetime cutoff.
        logger: Logger instance.

    Returns:
        Number of deleted records.
    """
    total_deleted = 0

    while True:
        result = await session.execute(
            text("""
                DELETE FROM tool_calls
                WHERE id IN (
                    SELECT id FROM tool_calls
                    WHERE created_at < :cutoff
                    LIMIT :batch_size
                )
            """), {
                "cutoff": cutoff_date,
                "batch_size": BATCH_SIZE
            })
        await session.commit()

        deleted = result.rowcount
        total_deleted += deleted

        if deleted < BATCH_SIZE:
            break

        await asyncio.sleep(0.1)

    if total_deleted > 0:
        logger.info(
            "cleanup.tool_calls",
            deleted=total_deleted,
            cutoff_days=RETENTION_TOOL_CALLS,
        )

    return total_deleted


async def cleanup_user_files(session, cutoff_date: datetime, logger) -> int:
    """Delete user_files metadata older than cutoff.

    Note: Actual files in Claude Files API have 24h TTL.
    This cleans up the database metadata.

    Args:
        session: Database session.
        cutoff_date: Datetime cutoff.
        logger: Logger instance.

    Returns:
        Number of deleted records.
    """
    total_deleted = 0

    while True:
        result = await session.execute(
            text("""
                DELETE FROM user_files
                WHERE id IN (
                    SELECT id FROM user_files
                    WHERE uploaded_at < :cutoff
                    LIMIT :batch_size
                )
            """), {
                "cutoff": cutoff_date,
                "batch_size": BATCH_SIZE
            })
        await session.commit()

        deleted = result.rowcount
        total_deleted += deleted

        if deleted < BATCH_SIZE:
            break

        await asyncio.sleep(0.1)

    if total_deleted > 0:
        logger.info(
            "cleanup.user_files",
            deleted=total_deleted,
            cutoff_days=RETENTION_USER_FILES,
        )

    return total_deleted


async def cleanup_empty_threads(session, cutoff_date: datetime, logger) -> int:
    """Delete empty threads that haven't been updated in retention period.

    Only deletes threads that:
    - Have no messages
    - Haven't been updated in RETENTION_THREADS days

    Args:
        session: Database session.
        cutoff_date: Datetime cutoff.
        logger: Logger instance.

    Returns:
        Number of deleted records.
    """
    # Delete threads with no messages and old updated_at
    result = await session.execute(
        text("""
            DELETE FROM threads
            WHERE id IN (
                SELECT t.id FROM threads t
                LEFT JOIN messages m ON m.thread_id = t.id
                WHERE t.updated_at < :cutoff
                GROUP BY t.id
                HAVING COUNT(m.message_id) = 0
            )
        """), {"cutoff": cutoff_date})
    await session.commit()

    deleted = result.rowcount

    if deleted > 0:
        logger.info(
            "cleanup.empty_threads",
            deleted=deleted,
            cutoff_days=RETENTION_THREADS,
        )

    return deleted


async def run_cleanup(logger) -> dict:
    """Run full cleanup cycle.

    Args:
        logger: Logger instance.

    Returns:
        Dict with counts of deleted records per table.
    """
    now = datetime.now(timezone.utc)

    # Calculate cutoffs
    cutoff_date_90 = now - timedelta(days=90)
    cutoff_timestamp_90 = int(cutoff_date_90.timestamp())

    results = {
        "messages": 0,
        "tool_calls": 0,
        "user_files": 0,
        "threads": 0,
    }

    try:
        async with get_session() as session:
            # Order matters due to FK constraints
            # messages don't block anything
            results["messages"] = await cleanup_messages(
                session, cutoff_timestamp_90, logger)

            results["tool_calls"] = await cleanup_tool_calls(
                session, cutoff_date_90, logger)

            results["user_files"] = await cleanup_user_files(
                session, cutoff_date_90, logger)

            # Threads last (after messages deleted)
            results["threads"] = await cleanup_empty_threads(
                session, cutoff_date_90, logger)

        total = sum(results.values())
        if total > 0:
            logger.info("cleanup.completed", **results, total=total)
        else:
            logger.debug("cleanup.nothing_to_delete")

    except Exception as e:
        logger.error("cleanup.error", error=str(e), exc_info=True)

    return results


async def cleanup_task(logger) -> None:
    """Background task that runs cleanup once per day at 3:00 AM UTC.

    Args:
        logger: Logger instance.
    """
    while True:
        try:
            # Calculate time until next 3:00 AM UTC
            now = datetime.now(timezone.utc)
            next_run = now.replace(hour=3, minute=0, second=0, microsecond=0)

            if next_run <= now:
                next_run += timedelta(days=1)

            wait_seconds = (next_run - now).total_seconds()

            logger.debug(
                "cleanup.scheduled",
                next_run=next_run.isoformat(),
                wait_hours=round(wait_seconds / 3600, 1),
            )

            await asyncio.sleep(wait_seconds)

            # Run cleanup
            logger.info("cleanup.starting")
            await run_cleanup(logger)

        except asyncio.CancelledError:
            logger.debug("cleanup.task_cancelled")
            break
        except Exception as e:
            logger.error("cleanup.task_error", error=str(e), exc_info=True)
            # Wait an hour before retrying on error
            await asyncio.sleep(3600)
