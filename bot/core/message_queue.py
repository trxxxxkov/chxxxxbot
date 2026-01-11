"""Per-thread message queue manager for batch processing.

Phase 1.6: Universal media architecture with MediaContent.

This module manages message queues per thread to handle:
1. Split messages (>4096 chars automatically split by Telegram)
2. Parallel messages sent while processing
3. Per-thread independent processing
4. Media messages with pre-processed content (transcripts/file_ids)

Architecture:
- Each thread has its own queue (thread_id → queue state)
- Text messages: 200ms batching window (for split detection)
- Media messages: immediate processing (no batching delay)
- During processing, new messages accumulate and process after completion

NO __init__.py - use direct import: from core.message_queue import MessageQueueManager
"""

import asyncio
from dataclasses import dataclass
from dataclasses import field
from typing import Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

from aiogram import types
from config import MESSAGE_BATCH_DELAY_MS
from utils.structured_logging import get_logger

if TYPE_CHECKING:
    from telegram.media_processor import MediaContent

logger = get_logger(__name__)


@dataclass
class MessageBatch:
    """Batch of messages for a thread.

    Phase 1.6: Universal media architecture.

    Attributes:
        messages: List of (Message, Optional[MediaContent]) tuples.
                  MediaContent is provided for media messages (voice/photo/etc).
        processing: Whether this thread is currently processing.
        timer_task: Asyncio task for 200ms delay timer (or None).
    """

    messages: List[Tuple[types.Message, Optional['MediaContent']]] = field(
        default_factory=list)
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
                              Signature: async def(
                                  thread_id: int,
                                  messages: List[Tuple[types.Message,
                                                       Optional[MediaContent]]])
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

    async def add_message(self,
                          thread_id: int,
                          message: types.Message,
                          media_content: Optional['MediaContent'] = None,
                          immediate: bool = False) -> None:
        """Add message to thread queue and handle processing.

        Phase 1.4.3: Time-based split detection (not length-based).
        Telegram splits long messages into parts that arrive < 200ms apart.

        Phase 1.6: Universal media architecture with MediaContent.
        All media types pass pre-processed content (transcripts/file_ids).

        Logic:
        1. If thread is processing → accumulate for next batch
        2. If immediate=True (media) → process without batching delay
        3. If immediate=False (text) → accumulate + 200ms timer for splits
        4. If timer already exists → cancel + reschedule (more messages coming)
        5. When timer expires → process accumulated batch

        Args:
            thread_id: Database thread ID.
            message: Telegram message to add.
            media_content: Optional pre-processed media (transcript/file_id).
            immediate: Process immediately without batching delay (for media).
        """
        queue = self._get_or_create_queue(thread_id)

        # Determine content length for logging
        content_length = 0
        if media_content and media_content.text_content:
            content_length = len(media_content.text_content)
        elif message.text:
            content_length = len(message.text)

        logger.debug("message_queue.add_message",
                     thread_id=thread_id,
                     content_length=content_length,
                     has_media=media_content is not None,
                     immediate=immediate,
                     processing=queue.processing,
                     batch_size=len(queue.messages),
                     has_timer=queue.timer_task is not None)

        # If currently processing → accumulate for next batch
        if queue.processing:
            queue.messages.append((message, media_content))
            logger.info("message_queue.accumulated_during_processing",
                        thread_id=thread_id,
                        batch_size=len(queue.messages),
                        has_media=media_content is not None)
            return

        # Accumulate message
        queue.messages.append((message, media_content))

        # Media messages: process immediately (no batching delay)
        if immediate:
            # Cancel any existing timer
            if queue.timer_task and not queue.timer_task.done():
                queue.timer_task.cancel()

            logger.info(
                "message_queue.immediate_processing",
                thread_id=thread_id,
                content_length=content_length,
                media_type=media_content.type.value if media_content else None)

            # Process immediately
            await self._wait_and_process(thread_id)
            return

        # Text messages: batching with 200ms delay for split detection
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
                    content_length=content_length,
                    batch_size=len(queue.messages))

    async def _wait_and_process(self, thread_id: int) -> None:
        """Wait and process accumulated messages.

        Phase 1.4.3: Time-based split detection.
        Telegram split messages arrive within MESSAGE_BATCH_DELAY_MS of each
        other, so we wait that long to accumulate all parts before processing.

        Args:
            thread_id: Database thread ID.
        """
        try:
            await asyncio.sleep(MESSAGE_BATCH_DELAY_MS / 1000)  # Convert ms to seconds

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

    async def _process_batch(
            self, thread_id: int,
            messages: List[Tuple[types.Message,
                                 Optional['MediaContent']]]) -> None:
        """Process batch of messages.

        Phase 1.6: Universal media architecture.

        Args:
            thread_id: Database thread ID.
            messages: List of (Message, Optional[MediaContent]) tuples.
        """
        if not messages:
            logger.warning("message_queue.empty_batch", thread_id=thread_id)
            return

        queue = self.queues[thread_id]
        queue.processing = True

        # Calculate content lengths for logging
        content_lengths = []
        for msg, media in messages:
            if media and media.text_content:
                content_lengths.append(len(media.text_content))
            elif msg.text:
                content_lengths.append(len(msg.text))
            else:
                content_lengths.append(0)

        logger.info("message_queue.processing_started",
                    thread_id=thread_id,
                    batch_size=len(messages),
                    content_lengths=content_lengths,
                    has_media=[m is not None for _, m in messages])

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
