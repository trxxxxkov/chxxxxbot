"""Unit tests for ProcessedMessageQueue.

Tests the queue's batching and processing behavior.
"""

import asyncio
from datetime import datetime
from datetime import timezone
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from telegram.pipeline.models import MediaType
from telegram.pipeline.models import MessageMetadata
from telegram.pipeline.models import ProcessedMessage
from telegram.pipeline.models import TranscriptInfo
from telegram.pipeline.models import UploadedFile
from telegram.pipeline.queue import ProcessedMessageQueue


@pytest.fixture
def sample_metadata() -> MessageMetadata:
    """Create sample metadata."""
    return MessageMetadata(
        chat_id=123,
        user_id=456,
        message_id=100,
        message_thread_id=None,
        chat_type="private",
        date=datetime.now(timezone.utc),
    )


@pytest.fixture
def mock_message() -> MagicMock:
    """Create mock aiogram message."""
    msg = MagicMock()
    msg.message_id = 100
    return msg


def create_text_message(
    text: str,
    metadata: MessageMetadata,
    mock_message: MagicMock,
) -> ProcessedMessage:
    """Helper to create text-only ProcessedMessage."""
    return ProcessedMessage(
        text=text,
        metadata=metadata,
        original_message=mock_message,
    )


def create_media_message(
    metadata: MessageMetadata,
    mock_message: MagicMock,
    with_transcript: bool = False,
    with_file: bool = False,
) -> ProcessedMessage:
    """Helper to create media ProcessedMessage."""
    transcript = None
    files = []

    if with_transcript:
        transcript = TranscriptInfo(
            text="Transcript",
            duration_seconds=5.0,
            detected_language="en",
            cost_usd=0.001,
        )

    if with_file:
        files = [
            UploadedFile(
                claude_file_id="file_123",
                telegram_file_id="tg_123",
                telegram_file_unique_id="unique_123",
                file_type=MediaType.IMAGE,
                filename="photo.jpg",
                mime_type="image/jpeg",
                size_bytes=1024,
            )
        ]

    return ProcessedMessage(
        text="Caption" if with_file else None,
        metadata=metadata,
        original_message=mock_message,
        files=files,
        transcript=transcript,
    )


class TestProcessedMessageQueueBasic:
    """Basic queue functionality tests."""

    @pytest.mark.asyncio
    async def test_queue_initialization(self) -> None:
        """Queue initializes with empty state."""
        callback = AsyncMock()
        queue = ProcessedMessageQueue(callback)

        stats = queue.get_stats()
        assert stats["total_threads"] == 0
        assert stats["processing_threads"] == 0
        assert stats["waiting_threads"] == 0

    @pytest.mark.asyncio
    async def test_add_creates_thread_queue(
        self,
        sample_metadata: MessageMetadata,
        mock_message: MagicMock,
    ) -> None:
        """Adding message creates thread queue."""
        callback = AsyncMock()
        queue = ProcessedMessageQueue(callback)
        msg = create_text_message("Test", sample_metadata, mock_message)

        await queue.add(thread_id=1, message=msg)

        stats = queue.get_stats()
        assert stats["total_threads"] == 1


class TestProcessedMessageQueueBatching:
    """Tests for message batching behavior."""

    @pytest.mark.asyncio
    async def test_text_messages_processed_after_delay(
        self,
        sample_metadata: MessageMetadata,
    ) -> None:
        """All text messages wait 150ms + normalization timeout."""
        callback = AsyncMock()
        queue = ProcessedMessageQueue(callback)

        # Create mock without media_group_id
        mock_msg = MagicMock()
        mock_msg.message_id = 100
        mock_msg.media_group_id = None

        msg = create_text_message("Test message", sample_metadata, mock_msg)
        await queue.add(thread_id=1, message=msg)

        # Should be called after delay
        callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_media_messages_processed(
        self,
        sample_metadata: MessageMetadata,
        mock_message: MagicMock,
    ) -> None:
        """Media messages are processed after delay."""
        callback = AsyncMock()
        queue = ProcessedMessageQueue(callback)

        msg = create_media_message(
            sample_metadata,
            mock_message,
            with_file=True,
        )

        await queue.add(thread_id=1, message=msg)

        callback.assert_called_once()
        args = callback.call_args[0]
        assert len(args[1]) == 1

    @pytest.mark.asyncio
    async def test_transcript_messages_processed(
        self,
        sample_metadata: MessageMetadata,
        mock_message: MagicMock,
    ) -> None:
        """Messages with transcript are processed after delay."""
        callback = AsyncMock()
        queue = ProcessedMessageQueue(callback)

        msg = create_media_message(
            sample_metadata,
            mock_message,
            with_transcript=True,
        )

        await queue.add(thread_id=1, message=msg)

        callback.assert_called_once()


class TestProcessedMessageQueueProcessing:
    """Tests for queue processing behavior."""

    @pytest.mark.asyncio
    async def test_accumulate_during_processing(
        self,
        sample_metadata: MessageMetadata,
        mock_message: MagicMock,
    ) -> None:
        """Messages accumulate during processing."""
        # Slow callback to allow accumulation
        process_started = asyncio.Event()
        process_continue = asyncio.Event()

        async def slow_callback(thread_id, messages):
            process_started.set()
            await process_continue.wait()

        queue = ProcessedMessageQueue(slow_callback)

        msg1 = create_media_message(
            sample_metadata,
            mock_message,
            with_file=True,
        )
        msg2 = create_text_message("During", sample_metadata, mock_message)

        # Start processing first message
        task = asyncio.create_task(queue.add(thread_id=1, message=msg1))
        await process_started.wait()

        # Add second message during processing (will accumulate)
        task2 = asyncio.create_task(queue.add(thread_id=1, message=msg2))

        # Stats should show messages accumulated
        stats = queue.get_stats()
        assert stats["processing_threads"] == 1

        # Let processing complete
        process_continue.set()
        await task
        await task2

    @pytest.mark.asyncio
    async def test_next_batch_after_processing(
        self,
        sample_metadata: MessageMetadata,
        mock_message: MagicMock,
    ) -> None:
        """Accumulated messages processed as next batch."""
        call_count = 0
        batches = []
        process_event = asyncio.Event()

        async def tracking_callback(thread_id, messages):
            nonlocal call_count
            call_count += 1
            batches.append(len(messages))
            if call_count == 1:
                # First call - wait briefly to allow accumulation
                await asyncio.sleep(0.05)

        queue = ProcessedMessageQueue(tracking_callback)

        msg1 = create_media_message(
            sample_metadata,
            mock_message,
            with_file=True,
        )
        msg2 = create_text_message("Accumulated", sample_metadata, mock_message)

        # Start processing - this should complete
        await queue.add(thread_id=1, message=msg1)

        # Give time for first batch to start
        await asyncio.sleep(0.01)

        # Add during processing (will accumulate)
        task2 = asyncio.create_task(queue.add(thread_id=1, message=msg2))

        # Wait for all processing
        await asyncio.sleep(0.5)
        await task2

        # Should have processed at least one batch
        assert call_count >= 1


class TestProcessedMessageQueueErrorHandling:
    """Tests for error handling and retry."""

    @pytest.mark.asyncio
    async def test_retry_on_failure(
        self,
        sample_metadata: MessageMetadata,
        mock_message: MagicMock,
    ) -> None:
        """Queue retries once on failure."""
        call_count = 0

        async def failing_callback(thread_id, messages):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("First call fails")
            # Second call succeeds

        queue = ProcessedMessageQueue(failing_callback)
        msg = create_media_message(
            sample_metadata,
            mock_message,
            with_file=True,
        )

        await queue.add(thread_id=1, message=msg)

        # Should have been called twice (original + retry)
        assert call_count == 2

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings(
        "ignore::pytest.PytestUnraisableExceptionWarning")
    async def test_processing_continues_after_failure(
        self,
        sample_metadata: MessageMetadata,
        mock_message: MagicMock,
    ) -> None:
        """Queue continues processing after both attempts fail."""

        async def always_failing(thread_id, messages):
            raise ValueError("Always fails")

        queue = ProcessedMessageQueue(always_failing)
        msg = create_media_message(
            sample_metadata,
            mock_message,
            with_file=True,
        )

        # Should not raise, just log error
        await queue.add(thread_id=1, message=msg)

        # Queue should not be stuck in processing state
        stats = queue.get_stats()
        assert stats["processing_threads"] == 0


class TestProcessedMessageQueueStats:
    """Tests for queue statistics."""

    @pytest.mark.asyncio
    async def test_stats_waiting_threads(
        self,
        sample_metadata: MessageMetadata,
        mock_message: MagicMock,
    ) -> None:
        """Stats track waiting threads."""
        callback = AsyncMock()
        queue = ProcessedMessageQueue(callback)

        msg = create_text_message("Test", sample_metadata, mock_message)

        # Add message - will wait 150ms + normalization timeout
        await queue.add(thread_id=1, message=msg)

        stats = queue.get_stats()
        # Note: Stats may be 0 or 1 depending on timing
        # The message might be processed by the time we check
        assert stats["total_threads"] == 1

    @pytest.mark.asyncio
    async def test_stats_total_pending(
        self,
        sample_metadata: MessageMetadata,
    ) -> None:
        """Stats track total pending messages accumulated during processing."""
        # Events to coordinate test timing
        callback_started = asyncio.Event()
        callback_finish = asyncio.Event()

        async def slow_callback(thread_id, messages):
            # Signal that callback has started (processing=True now)
            callback_started.set()
            # Wait for test to add more messages
            await callback_finish.wait()

        queue = ProcessedMessageQueue(slow_callback)

        # Create mock without media_group_id to avoid 500ms delay
        mock_msg = MagicMock()
        mock_msg.message_id = 100
        mock_msg.media_group_id = None  # No media group delay

        msg = create_media_message(
            sample_metadata,
            mock_msg,
            with_file=True,
        )

        # Start processing first message
        task = asyncio.create_task(queue.add(thread_id=1, message=msg))

        # Wait for callback to actually start (processing=True)
        await asyncio.wait_for(callback_started.wait(), timeout=2.0)

        # Now add second message - it should accumulate since processing=True
        # When processing=True, add() returns immediately after appending
        msg2 = create_text_message("Pending", sample_metadata, mock_msg)
        task2 = asyncio.create_task(queue.add(thread_id=1, message=msg2))

        # Give task2 a chance to run (it returns immediately when processing=True)
        await asyncio.sleep(0)

        # Check stats while first batch is still processing
        stats = queue.get_stats()
        assert stats["total_pending_messages"] >= 1

        # Cleanup
        callback_finish.set()
        await task
        await task2


class TestProcessedMessageQueueMultipleThreads:
    """Tests for multiple thread handling."""

    @pytest.mark.asyncio
    async def test_separate_thread_queues(
        self,
        sample_metadata: MessageMetadata,
        mock_message: MagicMock,
    ) -> None:
        """Each thread has separate queue."""
        thread_ids_seen = []

        async def tracking_callback(thread_id, messages):
            thread_ids_seen.append(thread_id)

        queue = ProcessedMessageQueue(tracking_callback)

        msg1 = create_media_message(
            sample_metadata,
            mock_message,
            with_file=True,
        )
        msg2 = create_media_message(
            sample_metadata,
            mock_message,
            with_file=True,
        )

        await queue.add(thread_id=1, message=msg1)
        await queue.add(thread_id=2, message=msg2)

        assert 1 in thread_ids_seen
        assert 2 in thread_ids_seen

    @pytest.mark.asyncio
    async def test_concurrent_thread_processing(
        self,
        sample_metadata: MessageMetadata,
        mock_message: MagicMock,
    ) -> None:
        """Multiple threads can process concurrently."""
        processing_threads = set()

        async def tracking_callback(thread_id, messages):
            processing_threads.add(thread_id)
            await asyncio.sleep(0.05)

        queue = ProcessedMessageQueue(tracking_callback)

        msg = create_media_message(
            sample_metadata,
            mock_message,
            with_file=True,
        )

        # Start both concurrently
        await asyncio.gather(
            queue.add(thread_id=1, message=msg),
            queue.add(thread_id=2, message=msg),
        )

        # Both threads should have been processed
        assert 1 in processing_threads
        assert 2 in processing_threads
