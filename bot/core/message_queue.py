"""Per-thread message queue manager for batch processing.

This module manages message queues per thread to handle:
1. Split messages (>4096 chars automatically split by Telegram)
2. Parallel messages sent while processing
3. Per-thread independent processing

Architecture:
- Each thread has its own queue (thread_id → queue state)
- Long messages (>4000 chars) trigger 300ms accumulation window
- Short messages are processed immediately
- During processing, new messages accumulate and process after completion

NO __init__.py - use direct import: from core.message_queue import MessageQueueManager
"""

import asyncio
from dataclasses import dataclass
from dataclasses import field
from typing import Callable, Dict, Optional

from aiogram import types
from utils.structured_logging import get_logger

logger = get_logger(__name__)


@dataclass
class MessageBatch:
    """Batch of messages for a thread.

    Attributes:
        messages: List of accumulated Telegram messages.
        processing: Whether this thread is currently processing.
        timer_task: Asyncio task for 300ms delay timer (or None).
    """

    messages: list[types.Message] = field(default_factory=list)
    processing: bool = False
    timer_task: Optional[asyncio.Task] = None


class MessageQueueManager:
    """Manages per-thread message queues for batching.

    Thread-safe message accumulation with smart processing:
    - Messages >4000 chars → wait 300ms for split parts
    - Messages ≤4000 chars → process immediately
    - During processing → accumulate for next batch

    Attributes:
        queues: Mapping from thread_id to MessageBatch.
        process_callback: Async function to process batch of messages.
    """

    def __init__(self, process_callback: Callable) -> None:
        """Initialize queue manager.

        Args:
            process_callback: Async function to process batch.
                              Signature: async def(thread_id: int,
                                                    messages: list[types.Message])
        """
        self.queues: Dict[int, MessageBatch] = {}
        self.process_callback = process_callback

        logger.info("message_queue.initialized")

    def _get_or_create_queue(self, thread_id: int) -> MessageBatch:
        """Get or create queue for thread.

        Args:
            thread_id: Database thread ID.

        Returns:
            MessageBatch for this thread.
        """
        if thread_id not in self.queues:
            self.queues[thread_id] = MessageBatch()
            logger.debug("message_queue.queue_created", thread_id=thread_id)

        return self.queues[thread_id]

    async def add_message(self, thread_id: int, message: types.Message) -> None:
        """Add message to thread queue and handle processing.

        Phase 1.4.3: Time-based split detection (not length-based).
        Telegram splits long messages into parts that arrive < 200ms apart.

        Logic:
        1. If thread is processing → accumulate for next batch
        2. Always accumulate + schedule 200ms timer
        3. If timer already exists → cancel + reschedule (more messages coming)
        4. When timer expires → process accumulated batch

        Args:
            thread_id: Database thread ID.
            message: Telegram message to add.
        """
        queue = self._get_or_create_queue(thread_id)
        message_length = len(message.text or "")

        logger.debug("message_queue.add_message",
                     thread_id=thread_id,
                     message_length=message_length,
                     processing=queue.processing,
                     batch_size=len(queue.messages),
                     has_timer=queue.timer_task is not None)

        # If currently processing → accumulate for next batch
        if queue.processing:
            queue.messages.append(message)
            logger.info("message_queue.accumulated_during_processing",
                        thread_id=thread_id,
                        batch_size=len(queue.messages))
            return

        # Always accumulate and wait for potential split parts
        # Telegram split messages arrive < 200ms apart
        queue.messages.append(message)

        # Cancel existing timer if any (more messages coming)
        if queue.timer_task and not queue.timer_task.done():
            queue.timer_task.cancel()
            logger.debug("message_queue.timer_cancelled",
                         thread_id=thread_id,
                         batch_size=len(queue.messages))

        # Schedule new timer (200ms)
        queue.timer_task = asyncio.create_task(
            self._wait_and_process(thread_id))

        logger.info("message_queue.message_scheduled",
                    thread_id=thread_id,
                    message_length=message_length,
                    batch_size=len(queue.messages))

    async def _wait_and_process(self, thread_id: int) -> None:
        """Wait 200ms and process accumulated messages.

        Phase 1.4.3: Time-based split detection.
        Telegram split messages arrive < 200ms apart, so we wait 200ms
        to accumulate all parts before processing.

        Args:
            thread_id: Database thread ID.
        """
        try:
            await asyncio.sleep(0.2)  # 200ms delay

            queue = self.queues[thread_id]
            messages = queue.messages
            queue.messages = []
            queue.timer_task = None

            logger.info("message_queue.timer_expired",
                        thread_id=thread_id,
                        batch_size=len(messages))

            await self._process_batch(thread_id, messages)

        except asyncio.CancelledError:
            logger.debug("message_queue.timer_cancelled_during_wait",
                         thread_id=thread_id)
            # Timer was cancelled, new timer scheduled

    async def _process_batch(self, thread_id: int,
                             messages: list[types.Message]) -> None:
        """Process batch of messages.

        Args:
            thread_id: Database thread ID.
            messages: List of Telegram messages to process as one batch.
        """
        if not messages:
            logger.warning("message_queue.empty_batch", thread_id=thread_id)
            return

        queue = self.queues[thread_id]
        queue.processing = True

        logger.info("message_queue.processing_started",
                    thread_id=thread_id,
                    batch_size=len(messages),
                    message_lengths=[len(msg.text or "") for msg in messages])

        try:
            # Call external processing callback with thread_id
            await self.process_callback(thread_id, messages)

            logger.info("message_queue.processing_complete",
                        thread_id=thread_id,
                        batch_size=len(messages))

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("message_queue.processing_failed",
                         thread_id=thread_id,
                         batch_size=len(messages),
                         error=str(e),
                         error_type=type(e).__name__,
                         exc_info=True)

            # Phase 1.4.3: Retry entire batch on failure
            logger.info("message_queue.retrying_batch", thread_id=thread_id)
            try:
                await self.process_callback(thread_id, messages)
                logger.info("message_queue.retry_success", thread_id=thread_id)
            except Exception as retry_error:  # pylint: disable=broad-exception-caught
                logger.error("message_queue.retry_failed",
                             thread_id=thread_id,
                             error=str(retry_error),
                             exc_info=True)
                # Give up after one retry

        finally:
            queue.processing = False

            # If messages accumulated during processing → process next batch
            if queue.messages:
                next_batch = queue.messages
                queue.messages = []

                logger.info("message_queue.processing_next_batch",
                            thread_id=thread_id,
                            next_batch_size=len(next_batch))

                await self._process_batch(thread_id, next_batch)

    def get_stats(self) -> dict:
        """Get queue statistics for monitoring.

        Returns:
            Dict with queue stats (total threads, processing count, etc).
        """
        processing_count = sum(1 for q in self.queues.values() if q.processing)
        waiting_count = sum(1 for q in self.queues.values() if q.messages)

        return {
            "total_threads": len(self.queues),
            "processing_threads": processing_count,
            "waiting_threads": waiting_count,
        }
