"""Message queue for unified pipeline.

This module provides the ProcessedMessageQueue that works with ProcessedMessage
objects where all I/O is already complete.

Key difference from core.message_queue:
- No UploadTracker needed (files already uploaded)
- Works with ProcessedMessage instead of raw Message + MediaContent
- Simpler design: just batching, no synchronization

NO __init__.py - use direct import:
    from telegram.pipeline.queue import ProcessedMessageQueue
"""

import asyncio
from dataclasses import dataclass
from dataclasses import field
import time
from typing import Awaitable, Callable, Dict, List, Optional, TYPE_CHECKING

from config import MESSAGE_BATCH_DELAY_MS
from utils.structured_logging import get_logger

if TYPE_CHECKING:
    from telegram.pipeline.models import ProcessedMessage
    from telegram.pipeline.tracker import NormalizationTracker

logger = get_logger(__name__)


@dataclass
class MessageBatch:
    """Batch of processed messages for a thread.

    All messages in the batch have completed I/O - files are uploaded,
    transcriptions are done.

    Attributes:
        messages: List of ProcessedMessage objects.
        processing: Whether this thread is currently processing.
        timer_task: Asyncio task for batch delay timer.
    """

    messages: List['ProcessedMessage'] = field(default_factory=list)
    processing: bool = False
    timer_task: Optional[asyncio.Task] = None


class ProcessedMessageQueue:
    """Queue manager for ProcessedMessage objects.

    This queue handles message batching for the unified pipeline.
    Unlike the old queue, it doesn't need UploadTracker because
    all files are already uploaded before messages enter the queue.

    Batching strategy:
    - Text-only messages: 200ms delay to collect split parts
    - Media messages: Immediate processing (no batching delay)
    - During processing: Accumulate for next batch

    Usage:
        async def process_batch(thread_id: int, messages: list[ProcessedMessage]):
            # Process the batch
            pass

        queue = ProcessedMessageQueue(process_batch)
        await queue.add(thread_id, processed_message)
    """

    def __init__(
        self,
        process_callback: Callable[[int, List['ProcessedMessage']],
                                   'Awaitable[None]'],
    ) -> None:
        """Initialize queue manager.

        Args:
            process_callback: Async function to process batch.
                Signature: async def(thread_id: int, messages: list[ProcessedMessage])
        """
        self._queues: Dict[int, MessageBatch] = {}
        self._process_callback = process_callback
        logger.info("processed_queue.initialized")

    def _get_or_create_queue(self, thread_id: int) -> MessageBatch:
        """Get or create queue for thread.

        Args:
            thread_id: Database thread ID.

        Returns:
            MessageBatch for this thread.
        """
        if thread_id not in self._queues:
            self._queues[thread_id] = MessageBatch()
            logger.debug("processed_queue.queue_created", thread_id=thread_id)
        return self._queues[thread_id]

    async def add(
        self,
        thread_id: int,
        message: 'ProcessedMessage',
        immediate: bool = False,
    ) -> None:
        """Add message to queue.

        Args:
            thread_id: Database thread ID.
            message: ProcessedMessage (all I/O complete).
            immediate: Process immediately without batching delay.
        """
        queue = self._get_or_create_queue(thread_id)

        # Determine if this should be immediate based on media
        # Media messages don't need batching - they're not split
        should_be_immediate = immediate or message.has_media

        logger.debug(
            "processed_queue.add",
            thread_id=thread_id,
            has_text=bool(message.text),
            has_media=message.has_media,
            immediate=should_be_immediate,
            processing=queue.processing,
            batch_size=len(queue.messages),
        )

        # If currently processing, accumulate for next batch
        if queue.processing:
            queue.messages.append(message)
            logger.info(
                "processed_queue.accumulated_during_processing",
                thread_id=thread_id,
                batch_size=len(queue.messages),
            )
            return

        # Add to queue
        queue.messages.append(message)

        # Immediate processing (media or explicit)
        if should_be_immediate:
            if queue.timer_task and not queue.timer_task.done():
                queue.timer_task.cancel()

            logger.info(
                "processed_queue.immediate",
                thread_id=thread_id,
                has_media=message.has_media,
            )
            await self._process_batch(thread_id)
            return

        # Text messages: batch with delay for split detection
        if queue.timer_task and not queue.timer_task.done():
            queue.timer_task.cancel()
            logger.debug(
                "processed_queue.timer_cancelled",
                thread_id=thread_id,
                batch_size=len(queue.messages),
            )

        queue.timer_task = asyncio.create_task(
            self._wait_and_process(thread_id))

        logger.info(
            "processed_queue.scheduled",
            thread_id=thread_id,
            batch_size=len(queue.messages),
            delay_ms=MESSAGE_BATCH_DELAY_MS,
        )

    async def _wait_and_process(self, thread_id: int) -> None:
        """Wait for batch delay then process.

        Waits for:
        1. Batch delay (200ms) to collect split messages
        2. Any pending normalizations in the same chat

        Args:
            thread_id: Database thread ID.
        """
        try:
            await asyncio.sleep(MESSAGE_BATCH_DELAY_MS / 1000)

            # Wait for any pending normalizations in this chat
            # This handles cases like forwarded photo+text arriving separately
            queue = self._queues.get(thread_id)
            if queue and queue.messages:
                chat_id = queue.messages[0].metadata.chat_id
                await self._wait_for_pending_normalizations(chat_id)

            await self._process_batch(thread_id)

        except asyncio.CancelledError:
            logger.debug(
                "processed_queue.timer_cancelled_during_wait",
                thread_id=thread_id,
            )

    async def _wait_for_pending_normalizations(
        self,
        chat_id: int,
        timeout: float = 5.0,
    ) -> None:
        """Wait for pending normalizations in a chat.

        This allows messages that arrive together (e.g., forwarded text+photo)
        to be processed in the same batch even if one takes longer to normalize.

        Args:
            chat_id: Telegram chat ID.
            timeout: Maximum seconds to wait for pending messages.
        """
        # Import here to avoid circular dependency
        from telegram.pipeline.tracker import \
            get_tracker  # pylint: disable=import-outside-toplevel

        tracker = get_tracker()

        if not tracker.has_pending(chat_id):
            return

        pending_count = tracker.get_pending_count(chat_id)
        logger.info(
            "processed_queue.waiting_for_normalizations",
            chat_id=chat_id,
            pending_count=pending_count,
        )

        completed = await tracker.wait_for_chat(chat_id, timeout=timeout)

        if completed:
            logger.info(
                "processed_queue.normalizations_complete",
                chat_id=chat_id,
            )
        else:
            logger.warning(
                "processed_queue.normalizations_timeout",
                chat_id=chat_id,
                timeout=timeout,
            )

    async def _process_batch(self, thread_id: int) -> None:
        """Process accumulated messages.

        Args:
            thread_id: Database thread ID.
        """
        queue = self._queues.get(thread_id)
        if not queue:
            return

        # Take messages and clear
        messages = queue.messages
        queue.messages = []
        queue.timer_task = None

        if not messages:
            logger.warning("processed_queue.empty_batch", thread_id=thread_id)
            return

        queue.processing = True
        processing_start = time.perf_counter()

        # Calculate queue wait times for each message
        queue_wait_times = []
        for msg in messages:
            queue_wait_ms = (processing_start - msg.queued_at) * 1000
            queue_wait_times.append(round(queue_wait_ms, 2))

        logger.info(
            "processed_queue.processing_start",
            thread_id=thread_id,
            batch_size=len(messages),
            message_types=[
                "media" if m.has_media else "text" for m in messages
            ],
            queue_wait_ms=queue_wait_times,
            avg_queue_wait_ms=round(
                sum(queue_wait_times) /
                len(queue_wait_times), 2) if queue_wait_times else 0,
        )

        try:
            await self._process_callback(thread_id, messages)

            processing_ms = (time.perf_counter() - processing_start) * 1000
            logger.info(
                "processed_queue.processing_complete",
                thread_id=thread_id,
                batch_size=len(messages),
                processing_ms=round(processing_ms, 2),
            )

        except Exception as e:  # pylint: disable=broad-exception-caught
            processing_ms = (time.perf_counter() - processing_start) * 1000
            logger.error(
                "processed_queue.processing_failed",
                thread_id=thread_id,
                batch_size=len(messages),
                processing_ms=round(processing_ms, 2),
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True,
            )

            # Retry once
            retry_start = time.perf_counter()
            logger.info("processed_queue.retrying", thread_id=thread_id)
            try:
                await self._process_callback(thread_id, messages)
                retry_ms = (time.perf_counter() - retry_start) * 1000
                logger.info("processed_queue.retry_success",
                            thread_id=thread_id,
                            retry_ms=round(retry_ms, 2))
            except Exception as retry_error:  # pylint: disable=broad-exception-caught
                retry_ms = (time.perf_counter() - retry_start) * 1000
                logger.error(
                    "processed_queue.retry_failed",
                    thread_id=thread_id,
                    retry_ms=round(retry_ms, 2),
                    error=str(retry_error),
                    exc_info=True,
                )

        finally:
            queue.processing = False

            # Process next batch if messages accumulated
            if queue.messages:
                next_batch_size = len(queue.messages)
                logger.info(
                    "processed_queue.next_batch",
                    thread_id=thread_id,
                    next_batch_size=next_batch_size,
                )
                await self._process_batch(thread_id)

    def get_stats(self) -> dict:
        """Get queue statistics.

        Returns:
            Dict with queue stats.
        """
        processing_count = sum(1 for q in self._queues.values() if q.processing)
        waiting_count = sum(1 for q in self._queues.values() if q.messages)
        total_pending = sum(len(q.messages) for q in self._queues.values())

        return {
            "total_threads": len(self._queues),
            "processing_threads": processing_count,
            "waiting_threads": waiting_count,
            "total_pending_messages": total_pending,
        }
